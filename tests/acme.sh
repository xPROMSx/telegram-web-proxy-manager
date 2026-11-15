#!/usr/bin/env bash
# Certbot/service mocks with the real planner, filesystem transactions and cert validation.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
# shellcheck source=telemt-web-manager.sh
source ./telemt-web-manager.sh
sandbox=$(mktemp -d)
trap 'rm -rf -- "$sandbox"' EXIT
fixture=${1:-tests/fixtures/nginx-3x-ui}
openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj /CN=proxy.example.com \
    -addext subjectAltName=DNS:proxy.example.com -keyout "$sandbox/key" -out "$sandbox/cert" >/dev/null 2>&1
failures=0
for scenario in free webroot foreign conflict invalid-nginx failed-certbot interrupted-certbot pending-config post-validation post-renewal foreign-existing probe-fail unsafe-webroot unowned-webroot probe-reload-ready probe-rollback-retry probe-wrong-token probe-failed-token empty-webroot unowned-challenge-file unowned-link unowned-marker unowned-directory; do
    # Run cases independently so both issuance regressions report RED before fixes.
    set +e
    (
    set -Eeuo pipefail
    case_dir="$sandbox/$scenario"; mkdir "$case_dir"
    TMP="$case_dir/tmp" NGINX_ROOT="$case_dir/nginx" ACME_ROOT="$case_dir/acme"
    STATE="$case_dir/state" CERT_ROOT="$case_dir/certs" BACKUP_ROOT="$case_dir/backups"
    mkdir "$TMP"
    if [[ $scenario == free ]]; then
        cp -r --preserve=mode tests/fixtures/nginx "$NGINX_ROOT"
    else
        cp -r --preserve=mode "$fixture" "$NGINX_ROOT"
    fi
    mkdir -p "$NGINX_ROOT/conf.d"
    DOMAIN=proxy.example.com EMAIL=operator@example.com AGREE_TOS=1
    if [[ $scenario == conflict ]]; then
        # SC2016: retain literal Nginx variables, not shell expansions.
        # shellcheck disable=SC2016
        printf 'server { listen 80; server_name proxy.example.com; return 301 https://$host$request_uri; }\n' >"$NGINX_ROOT/sites-enabled/conflict.conf"
    fi
    if [[ $scenario == foreign-existing ]]; then
        mkdir -p "$CERT_ROOT/live/$DOMAIN" "$CERT_ROOT/renewal"
        cp "$sandbox/cert" "$CERT_ROOT/live/$DOMAIN/fullchain.pem"
        cp "$sandbox/key" "$CERT_ROOT/live/$DOMAIN/privkey.pem"
        printf '[renewalparams]\nauthenticator = standalone\n' >"$CERT_ROOT/renewal/$DOMAIN.conf"
    fi
    if [[ $scenario == unsafe-webroot ]]; then
        mkdir "$case_dir/foreign-root"; printf keep >"$case_dir/foreign-root/keep"
        ln -s "$case_dir/foreign-root" "$ACME_ROOT"
    elif [[ $scenario == unowned-webroot ]]; then
        mkdir "$ACME_ROOT"; printf keep >"$ACME_ROOT/keep"
    fi
    case $scenario in
        empty-webroot) mkdir "$ACME_ROOT";;
        unowned-challenge-file|unowned-link|unowned-marker|unowned-directory)
            mkdir -p "$ACME_ROOT/.well-known/acme-challenge"
            case $scenario in
                unowned-challenge-file) printf keep >"$ACME_ROOT/.well-known/acme-challenge/keep";;
                unowned-link) ln -s "$case_dir/absent" "$ACME_ROOT/.well-known/acme-challenge/link";;
                unowned-marker) printf 'other.example.com\n' >"$ACME_ROOT/.telemt-web-manager";;
                unowned-directory) mkdir "$ACME_ROOT/foreign";;
            esac
            cp -a "$ACME_ROOT" "$case_dir/original-acme";;
    esac
    cp -r --preserve=mode "$NGINX_ROOT" "$case_dir/original"
    ss() { if [[ $scenario != free && $scenario != pending-config ]]; then printf occupied; fi; }
    nginx_runtime_identity() { return 0; }
    nginx_port_owned() { [[ $scenario != foreign ]]; }
    nginx_test() { [[ $scenario != invalid-nginx || ! -e $NGINX_ROOT/conf.d/telemt-web-manager-acme.conf ]]; }
    nginx_reload() { printf reload >>"$case_dir/reloads"; }
    systemctl() {
        case $1 in stop|disable|restart) printf forbidden >"$case_dir/forbidden-service-mutation"; return 1;; esac
        return 0
    }
    probe_ready=0
    curl() {
        local url=${!#} attempt
        printf '%s\n' "$*" >>"$case_dir/curl-calls"
        attempt=$(wc -l <"$case_dir/curl-calls")
        if [[ " $* " != *" --resolve $DOMAIN:80:127.0.0.1 "* ||
              " $* " != *" --noproxy * "* || " $* " != *" --proto =http "* ||
              " $* " != *' -fsS '* || " $* " == *' --insecure '* || " $* " == *' -k '* ||
              $url != "http://$DOMAIN/.well-known/acme-challenge/twm-"* ]]; then
            touch "$case_dir/invalid-curl"; return 2
        fi
        case $scenario in
            probe-fail) printf 'curl: (22) HTTP 404\n' >&2; return 22;;
            probe-reload-ready) if (( attempt <= 2 )); then return 22; fi;;
            probe-rollback-retry) if (( ! probe_ready )); then return 22; fi;;
            probe-wrong-token) printf wrong-token; return 0;;
        esac
        cat "$ACME_ROOT/.well-known/acme-challenge/${url##*/}"
        [[ $scenario != probe-failed-token ]]
    }
    # Called indirectly by the production probe; never wait in fault-injection cases.
    # shellcheck disable=SC2317
    sleep() { printf '%s\n' "$*" >>"$case_dir/sleeps"; }
    certbot() {
        [[ $* == *--non-interactive* && $* == *--cert-name* ]] || return 1
        if [[ $scenario == free ]]; then
            [[ $* == *--standalone* ]] || return 1
        else
            [[ $* == *--webroot-path* && $* == *"$ACME_ROOT"* && $* != *--standalone* ]] || return 1
        fi
        printf 'invoked\n' >>"$case_dir/certbot-called"
        if [[ $scenario == interrupted-certbot ]]; then kill -TERM "$BASHPID"; return 1; fi
        [[ $scenario != failed-certbot ]] || return 1
        mkdir -p "$CERT_ROOT/live/$DOMAIN" "$CERT_ROOT/renewal"
        cp "$sandbox/cert" "$CERT_ROOT/live/$DOMAIN/fullchain.pem"
        cp "$sandbox/key" "$CERT_ROOT/live/$DOMAIN/privkey.pem"
        if [[ $scenario == free ]]; then
            printf '[renewalparams]\nauthenticator = standalone\n' >"$CERT_ROOT/renewal/$DOMAIN.conf"
        else
            local recorded_root=$ACME_ROOT
            if [[ $scenario == post-renewal ]]; then recorded_root="$case_dir/foreign-webroot"; fi
            printf '[renewalparams]\nauthenticator = webroot\nwebroot_path = %s,\n[[webroot_map]]\n%s = %s\n' \
                "$recorded_root" "$DOMAIN" "$recorded_root" >"$CERT_ROOT/renewal/$DOMAIN.conf"
        fi
        if [[ $scenario == post-validation ]]; then
            # Certbot succeeds, then the certificate fails the >7-day policy.
            openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=proxy.example.com \
                -addext subjectAltName=DNS:proxy.example.com \
                -keyout "$CERT_ROOT/live/$DOMAIN/privkey.pem" \
                -out "$CERT_ROOT/live/$DOMAIN/fullchain.pem" >/dev/null 2>&1
        fi
    }
    set +e
    (set -Eeuo pipefail; ensure_certificate) >"$case_dir/manager.log" 2>&1
    result=$?
    set -e
    if [[ ( $scenario == free || $scenario == webroot ) && $result != 0 ]]; then
        # Fixture diagnostics only: manager errors contain no fixture key material.
        grep -E '^ERROR:|^Safety validation|^CRITICAL:' "$case_dir/manager.log" >&2 || true
        printf 'FAIL - ACME %s returned %s\n' "$scenario" "$result" >&2
        exit 1
    fi
    case $scenario in
        free)
            [[ $result == 0 && -f $case_dir/certbot-called ]]
            diff -r "$case_dir/original" "$NGINX_ROOT";;
        webroot|probe-reload-ready|empty-webroot)
            [[ $result == 0 && -f $NGINX_ROOT/conf.d/telemt-web-manager-acme.conf && -d $TMP ]]
            if [[ $scenario == probe-reload-ready ]]; then
                [[ $(wc -l <"$case_dir/curl-calls") == 3 && $(wc -l <"$case_dir/sleeps") == 2 ]]
            fi
            helper renewal-contract "$CERT_ROOT" "$DOMAIN" "$ACME_ROOT"
            before=$(sha256sum "$NGINX_ROOT/conf.d/telemt-web-manager-acme.conf")
            (ensure_certificate) >"$case_dir/repeated.log" 2>&1
            [[ $(wc -l <"$case_dir/certbot-called") == 1 ]]
            [[ $(sha256sum "$NGINX_ROOT/conf.d/telemt-web-manager-acme.conf") == "$before" ]]
            [[ $(grep -c "server_name $DOMAIN;" "$NGINX_ROOT/conf.d/telemt-web-manager-acme.conf") == 1 ]]
            rm "$NGINX_ROOT/conf.d/telemt-web-manager-acme.conf"
            diff -r "$case_dir/original" "$NGINX_ROOT";;
        post-validation|post-renewal)
            [[ $result != 0 && -f $case_dir/certbot-called ]]
            [[ -f $CERT_ROOT/live/$DOMAIN/fullchain.pem && -f $CERT_ROOT/renewal/$DOMAIN.conf ]]
            [[ ! -e $NGINX_ROOT/conf.d/telemt-web-manager-acme.conf && ! -e $ACME_ROOT/.telemt-web-manager ]]
            diff -r "$case_dir/original" "$NGINX_ROOT"
            # Fix only the initial defect as an administrator would. Retry must
            # independently refuse the surviving lineage with missing ACME state.
            cp "$sandbox/cert" "$CERT_ROOT/live/$DOMAIN/fullchain.pem"
            cp "$sandbox/key" "$CERT_ROOT/live/$DOMAIN/privkey.pem"
            printf '[renewalparams]\nauthenticator = webroot\nwebroot_path = %s,\n[[webroot_map]]\n%s = %s\n' \
                "$ACME_ROOT" "$DOMAIN" "$ACME_ROOT" >"$CERT_ROOT/renewal/$DOMAIN.conf"
            before=$(sha256sum "$CERT_ROOT/live/$DOMAIN/"*.pem "$CERT_ROOT/renewal/$DOMAIN.conf")
            for attempt in 1 2; do
                set +e
                (set -Eeuo pipefail; ensure_certificate) >"$case_dir/retry-$attempt.log" 2>&1
                result=$?
                set -e
                [[ $result != 0 ]]
                grep -q 'Managed webroot renewal is incomplete; certificate retained' "$case_dir/retry-$attempt.log"
                [[ $(sha256sum "$CERT_ROOT/live/$DOMAIN/"*.pem "$CERT_ROOT/renewal/$DOMAIN.conf") == "$before" ]]
                [[ $(wc -l <"$case_dir/certbot-called") == 1 ]]
                diff -r "$case_dir/original" "$NGINX_ROOT"
            done;;
        *)
            [[ $result != 0 ]]
            diff -r "$case_dir/original" "$NGINX_ROOT"
            if [[ $scenario != failed-certbot && $scenario != interrupted-certbot ]]; then [[ ! -e $case_dir/certbot-called ]]; fi
            if [[ $scenario == interrupted-certbot ]]; then [[ $result == 143 ]]; fi;;
    esac
    case $scenario in
        probe-fail|probe-rollback-retry|probe-wrong-token|probe-failed-token)
            [[ $(grep -c '^ERROR: ACME webroot is not served correctly by local Nginx$' "$case_dir/manager.log") == 1 ]]
            [[ -z $(find "$ACME_ROOT" -type f -print) ]]
            if [[ $scenario == probe-fail ]]; then
                [[ $(wc -l <"$case_dir/curl-calls") == 10 && $(wc -l <"$case_dir/sleeps") == 9 ]]
                [[ $(grep -Fxc '0.5' "$case_dir/sleeps") == 9 ]]
                [[ $(grep -Fc -- '--connect-timeout 0.5 --max-time 0.5' "$case_dir/curl-calls") == 10 ]]
                [[ $(grep -c '^curl:' "$case_dir/manager.log") == 0 ]]
            elif [[ $scenario == probe-rollback-retry ]]; then
                [[ -d $ACME_ROOT/.well-known/acme-challenge && ! -e $ACME_ROOT/.telemt-web-manager ]]
                probe_ready=1
                set +e
                (set -Eeuo pipefail; ensure_certificate) >"$case_dir/retry.log" 2>&1
                result=$?
                set -e
                if (( result )); then
                    grep -E '^ERROR:|^Safety validation' "$case_dir/retry.log" >&2 || true
                fi
                [[ $result == 0 && -f $case_dir/certbot-called ]]
                [[ $(cat "$ACME_ROOT/.telemt-web-manager") == "$DOMAIN" ]]
                helper renewal-contract "$CERT_ROOT" "$DOMAIN" "$ACME_ROOT"
            fi;;
        unowned-challenge-file|unowned-link|unowned-marker|unowned-directory)
            grep -qx 'ERROR: Unmanaged ACME webroot' "$case_dir/manager.log"
            diff -r --no-dereference "$case_dir/original-acme" "$ACME_ROOT";;
    esac
    if [[ $scenario == unsafe-webroot ]]; then [[ $(cat "$case_dir/foreign-root/keep") == keep && -L $ACME_ROOT ]]; fi
    if [[ $scenario == unowned-webroot ]]; then [[ $(cat "$ACME_ROOT/keep") == keep ]]; fi
    [[ ! -e $case_dir/forbidden-service-mutation && ! -e $case_dir/invalid-curl ]]
    [[ ! -d $ACME_ROOT || -z $(find "$ACME_ROOT" -name 'twm-*' -print) ]]
    printf 'ok - ACME %s\n' "$scenario"
    )
    case_result=$?
    set -e
    if (( case_result )); then
        printf 'FAIL - ACME %s (exit %s)\n' "$scenario" "$case_result" >&2
        failures=$((failures+1))
    fi
done
(( failures == 0 )) || exit 1

# Exercise Fresh -> site plan -> ACME plan on the current foreign HTTP bytes.
# Keep orchestration mocks in this suite; nginx.sh independently runs the real
# Nginx/token probe and remains bounded for the existing QEMU timeout.
if [[ $# == 0 ]]; then
    current="$sandbox/current-http"
    cp -r tests/fixtures/nginx "$current"
    mkdir -p "$current/sites-enabled" "$current/conf.d"
    cp tests/fixtures/nginx-http80-3x.conf "$current/sites-enabled/80.conf"
    sed -i 's/http {/http { include sites-enabled\/*.conf;/' "$current/nginx.conf"
    bash tests/fresh.sh "$current"
fi
