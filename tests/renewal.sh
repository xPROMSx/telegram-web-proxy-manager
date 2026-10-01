#!/usr/bin/env bash
# Root-owned temporary fixtures only; services and sockets are mocked.
# OS mocks are invoked indirectly by sourced manager functions.
# shellcheck disable=SC2317
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
# shellcheck source=telemt-web-manager.sh
source ./telemt-web-manager.sh
[[ $EUID == 0 ]] || die 'Run this fixture as root (sudo bash tests/renewal.sh)'
sandbox=$(mktemp -d)
trap 'rm -rf -- "$sandbox"' EXIT
TMP="$sandbox/tmp" CERT_ROOT="$sandbox/certs" STATE="$sandbox/state"
ACME_ROOT="$sandbox/acme" NGINX_ROOT="$sandbox/nginx"
RENEW_HOOK="$CERT_ROOT/renewal-hooks/deploy/telemt-web-manager"
DOMAIN=proxy.example.com
mkdir -p "$TMP" "$STATE" "$CERT_ROOT/renewal" "$(dirname "$RENEW_HOOK")" "$CERT_ROOT/live/$DOMAIN"
printf '{"schema":1,"domain":"proxy.example.com","acme_webroot":""}\n' >"$STATE/manifest.json"
printf '[renewalparams]\nauthenticator = standalone\n' >"$CERT_ROOT/renewal/$DOMAIN.conf"
openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj /CN=proxy.example.com \
    -addext subjectAltName=DNS:proxy.example.com -keyout "$CERT_ROOT/live/$DOMAIN/privkey.pem" \
    -out "$CERT_ROOT/live/$DOMAIN/fullchain.pem" >/dev/null 2>&1
reset_hook() { rm -f "$RENEW_HOOK"; generate_renewal_hook >"$RENEW_HOOK"; chmod 0750 "$RENEW_HOOK"; }
reset_hook
fixture_sockets=''
ss() { [[ $* == '-H -ltn sport = :80' ]]; printf '%s' "$fixture_sockets"; }
assert_rejected() {
    local label=$1 result
    shift
    set +e
    (set -Eeuo pipefail; "$@") >"$sandbox/refusal.log" 2>&1
    result=$?
    set -e
    [[ $result != 0 ]] || die "Expected refusal: $label"
    printf 'ok - %s rejected\n' "$label"
}
certificate_health_contract
printf 'ok - standalone free port 80 and exact generated hook accepted\n'
for fixture_sockets in 'LISTEN 0 128 127.0.0.1:80 0.0.0.0:*' 'LISTEN 0 128 0.0.0.0:80 0.0.0.0:*' \
    'LISTEN 0 128 [::]:80 [::]:*' 'LISTEN 0 128 [::1]:80 [::]:*'; do
    assert_rejected "standalone listener $fixture_sockets" certificate_renewal_contract
    grep -q 'Standalone Certbot renewal requires free TCP port 80' "$sandbox/refusal.log"
done
fixture_sockets=''
ss() { return 1; }
assert_rejected 'socket inspection failure' certificate_renewal_contract
ss() { [[ $* == '-H -ltn sport = :80' ]]; printf '%s' "$fixture_sockets"; }
# Real planner/state validation: webroot must allow the Nginx port-80 listener.
cp -r tests/fixtures/nginx-3x-ui "$NGINX_ROOT"
mkdir -p "$NGINX_ROOT/conf.d" "$ACME_ROOT/.well-known/acme-challenge"
printf '%s\n' "$DOMAIN" >"$ACME_ROOT/.telemt-web-manager"
helper acme-plan "$NGINX_ROOT" "$DOMAIN" "$TMP/acme-plan.json" "$ACME_ROOT"
jq -rj '.edits[0].content' "$TMP/acme-plan.json" >"$NGINX_ROOT/conf.d/telemt-web-manager-acme.conf"
printf '[renewalparams]\nauthenticator = webroot\nwebroot_path = %s,\n' "$ACME_ROOT" >"$CERT_ROOT/renewal/$DOMAIN.conf"
jq --arg acme "$ACME_ROOT" '.acme_webroot=$acme' "$STATE/manifest.json" >"$TMP/manifest"
cp "$TMP/manifest" "$STATE/manifest.json"
nginx_port_owned() { [[ $1 == 80 ]]; }
ss() { die 'Webroot must not use standalone socket check'; }
certificate_health_contract
printf 'ok - webroot with occupied Nginx port 80 accepted\n'
printf '[renewalparams]\nauthenticator = standalone\n' >"$CERT_ROOT/renewal/$DOMAIN.conf"
printf '{"schema":1,"domain":"proxy.example.com","acme_webroot":""}\n' >"$STATE/manifest.json"
ss() { return 0; }
for scenario in missing symlink changed extra-command group-writable other-writable non-executable special-mode executable-path wrong-path; do
    reset_hook
    case $scenario in
        missing) rm "$RENEW_HOOK";;
        symlink) cp "$RENEW_HOOK" "$sandbox/hook-target"; rm "$RENEW_HOOK"; ln -s "$sandbox/hook-target" "$RENEW_HOOK";;
        changed) sed -i 's/reload/restart/' "$RENEW_HOOK";;
        extra-command) printf '/usr/bin/true\n' >>"$RENEW_HOOK";;
        group-writable) chmod 0770 "$RENEW_HOOK";;
        other-writable) chmod 0752 "$RENEW_HOOK";;
        non-executable) chmod 0640 "$RENEW_HOOK";;
        special-mode) chmod 4750 "$RENEW_HOOK";;
        executable-path) sed -i 's@/usr/sbin/nginx@/usr/local/sbin/nginx@' "$RENEW_HOOK";;
        wrong-path) RENEW_HOOK="$sandbox/other-hook"; generate_renewal_hook >"$RENEW_HOOK"; chmod 0750 "$RENEW_HOOK";;
    esac
    assert_rejected "deploy hook $scenario" renewal_deploy_hook_contract
    RENEW_HOOK="$CERT_ROOT/renewal-hooks/deploy/telemt-web-manager"
done
reset_hook
chown 65534 "$RENEW_HOOK"
assert_rejected 'deploy hook wrong owner' renewal_deploy_hook_contract
reset_hook
# Test the actual check orchestration with only unrelated runtime diagnostics mocked.
load_installation() { certificate_health_contract; }
binary_version() { printf '%s' "$SUPPORTED_TELEMT_VERSION"; }
listener_ready() { return 0; }
path_health() { return 0; }
recent_logs() { return 0; }
scheduler=none
systemctl() {
    case $1 in
        is-enabled) [[ ( $scheduler == certbot && $3 == certbot.timer ) ||
                      ( $scheduler == snap && $3 == snap.certbot.renew.timer ) ]];;
        show) if [[ $* == *MainPID* && $* == *--value* ]]; then printf '%s\n' "$$"; fi;;
        *) printf forbidden >"$sandbox/service-mutation"; return 1;;
    esac
}
before=$(sha256sum "$CERT_ROOT/live/$DOMAIN/"*.pem "$CERT_ROOT/renewal/$DOMAIN.conf" "$RENEW_HOOK" "$STATE/manifest.json")
for scheduler in certbot snap none; do
    check_manager >"$sandbox/check.log" 2>&1
    case $scheduler in
        certbot) grep -q 'Renewal scheduler detected: certbot.timer' "$sandbox/check.log";;
        snap) grep -q 'Renewal scheduler detected: snap.certbot.renew.timer' "$sandbox/check.log";;
        none) grep -q 'WARNING: no known Certbot timer detected' "$sandbox/check.log";;
    esac
    grep -q 'Check result: OK' "$sandbox/check.log"
    [[ $(sha256sum "$CERT_ROOT/live/$DOMAIN/"*.pem "$CERT_ROOT/renewal/$DOMAIN.conf" "$RENEW_HOOK" "$STATE/manifest.json") == "$before" ]]
    printf 'ok - scheduler %s check succeeds without Certbot state changes\n' "$scheduler"
done
printf '/usr/bin/true\n' >>"$RENEW_HOOK"
before=$(sha256sum "$CERT_ROOT/live/$DOMAIN/"*.pem "$CERT_ROOT/renewal/$DOMAIN.conf" "$RENEW_HOOK" "$STATE/manifest.json")
for action in check_manager update_manager repair_manager; do
    assert_rejected "$action altered hook" "$action"
    [[ $(sha256sum "$CERT_ROOT/live/$DOMAIN/"*.pem "$CERT_ROOT/renewal/$DOMAIN.conf" "$RENEW_HOOK" "$STATE/manifest.json") == "$before" ]]
done
reset_hook
ss() { printf 'LISTEN 0 128 [::]:80 [::]:*'; }
assert_rejected 'check standalone occupied port 80' check_manager
[[ ! -e $sandbox/service-mutation ]]
