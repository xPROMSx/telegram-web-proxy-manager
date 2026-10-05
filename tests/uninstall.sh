#!/usr/bin/env bash
# Real parser, ownership metadata, no-follow filesystem and certificate checks.
# NSS, services/listeners/firewall and issuance are isolated fixture boundaries.
# Certbot deletion uses the installed real CLI, only on private local lineages.
# shellcheck disable=SC2317
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
ROOT=$PWD
# shellcheck source=telemt-web-manager.sh
source ./telemt-web-manager.sh
(( EUID == 0 )) || die 'Run uninstall fixtures as root'
if [[ ${1:-} != --inside ]]; then exec unshare --mount --propagation private bash "$0" --inside; fi
sandbox=$(mktemp -d)
finish_fixture() {
    local result=$?
    if (( result )) && [[ -n ${case_dir:-} && -f $case_dir/uninstall.log ]]; then
        grep -E '^(ERROR:|Safety validation|CRITICAL:|Rolling back)' "$case_dir/uninstall.log" >&2 || true
        printf 'FAIL - uninstall fixture %s\n' "$scenario" >&2
    fi
    if [[ -n ${blocker:-} ]]; then kill "$blocker" 2>/dev/null || true; wait "$blocker" 2>/dev/null || true; fi
    if [[ -n ${DATA:-} ]] && mountpoint -q "$DATA/state/offender"; then umount "$DATA/state/offender"; fi
    if [[ ${scenario:-} == mount && -d ${DATA:-} ]]; then umount "$DATA" || true; fi
    rm -rf -- "$sandbox"
    exit "$result"
}
trap finish_fixture EXIT
openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj /CN=proxy.example.com \
    -addext subjectAltName=DNS:proxy.example.com -keyout "$sandbox/key" -out "$sandbox/cert" >/dev/null 2>&1
mkdir "$sandbox/tools"
for tool in getent useradd userdel groupadd groupdel; do ln -s "$ROOT/tests/account_fixture.py" "$sandbox/tools/$tool"; done
# Scope ownership scanning to the fixture filesystem; production scans mounts.
cat >"$sandbox/tools/find" <<'PY'
#!/usr/bin/env python3
import os, subprocess, sys
args=sys.argv[1:]
if '-uid' in args: args[0]=os.environ['UNINSTALL_FIXTURE_ROOT']
sys.exit(subprocess.call(['/usr/bin/find',*args]))
PY
chmod 0755 "$sandbox/tools/find"
export PATH="$sandbox/tools:$PATH"
eval "$(declare -f uninstall_quiet | sed '1s/uninstall_quiet/real_uninstall_quiet/')"
eval "$(declare -f uninstall_remove_files | sed '1s/uninstall_remove_files/real_uninstall_remove_files/')"
eval "$(declare -f uninstall_remove_account | sed '1s/uninstall_remove_account/real_uninstall_remove_account/')"
eval "$(declare -f backup_begin | sed '1s/backup_begin/real_backup_begin/')"
eval "$(declare -f helper | sed '1s/helper/real_helper/')"
runtime_fixture() { python3 "$ROOT/tests/uninstall_runtime_fixture.py" "$@"; }
helper() {
    if [[ ${variation:-} == metadata-fail && $1 == uninstall-backup ]]; then return 1; fi
    if [[ $1 == update-gate-contract && $scenario == *-generation ]]; then
        python3 "$ROOT/tests/update_state_fixture.py" contract "$case_dir"; return
    fi
    real_helper "$@"
}
# A synchronous child runs after ownership validation and while service-active
# is still set. Completion, rather than elapsed time, gates backup and stop.
backup_begin() {
    if [[ -f $TMP/uninstall-plan.json ]]; then
        if [[ $scenario == runtime-churn* ]]; then
            runtime_fixture churn "$DATA" "$TMP/uninstall-plan.json" "$case_dir/active" "$case_dir/barrier"
        elif [[ ${variation:-} == drift-* ]]; then
            [[ -f $case_dir/active ]]
            printf '\n# deterministic concurrent static drift\n' >>"$drift_target"
            runtime_fixture save "$DATA" "$case_dir/refusal-tree"
        fi
    fi
    real_backup_begin
    if [[ -f $TMP/uninstall-plan.json ]]; then printf '%s' "$BACKUP" >"$case_dir/last-backup"; fi
}
chown() {
    local owner=$1; shift
    case $owner in root:telemt) owner=0:424242;; telemt:telemt) owner=424242:424242;; esac
    command chown "$owner" "$@"
}
nginx_test() { return 0; }
nginx_reload() { printf reload >>"$case_dir/reloads"; }
nginx_runtime_identity() { return 0; }
nginx_port_owned() { return 0; }
acme_probe() { helper acme-state "$NGINX_ROOT" "$DOMAIN" "$ACME_ROOT"; }
ss() {
    if [[ $* == *'sport = :80'* && $kind == webroot ]]; then printf nginx;
    elif [[ $* == *18080* && -f $case_dir/active ]]; then printf telemt;
    elif [[ $* == *7444* && -f $NGINX_ROOT/conf.d/telemt-web-manager.conf ]]; then printf nginx; fi
}
nft() { return 0; }
iptables-save() { return 0; }
ip6tables-save() { return 0; }
systemctl() {
    printf '%s\n' "$*" >>"$case_dir/services"
    case $1 in
        show)
            if [[ $* == *FragmentPath* && -f $UNIT ]]; then printf '%s\n' "$UNIT";
            elif [[ $* == *DropInPaths* && $scenario == dropin ]]; then printf foreign.conf;
            elif [[ $* == *DropInPaths* && $scenario == *-generation && -f ${UNIT}.d/50-telemt-web-manager-update.conf ]]; then
                printf '%s' "${UNIT}.d/50-telemt-web-manager-update.conf";
            elif [[ $* == *ActiveState* ]]; then
                if [[ -f $case_dir/active ]]; then printf active; else printf inactive; fi
            fi;;
        is-active) if [[ $* == *nginx* ]]; then return 0; else [[ -f $case_dir/active ]]; fi;;
        is-enabled) if [[ -f $case_dir/enabled ]]; then printf enabled; else printf disabled; return 1; fi;;
        enable) touch "$case_dir/enabled"; if [[ $* == *--now* ]]; then touch "$case_dir/active"; fi;;
        disable)
            rm -f "$case_dir/enabled"
            if [[ $* == *--now* ]]; then
                if [[ $scenario == runtime-* ]]; then runtime_fixture check-pre-backup "$DATA" "$BACKUP" || return 1; fi
                if [[ ${variation:-} != active-after-stop ]]; then rm -f "$case_dir/active"; fi
                if [[ ${variation:-} == stop-fail ]]; then return 1; fi
                if [[ $scenario == runtime-churn* ]]; then
                    runtime_fixture finalize "$DATA" || return 1
                    runtime_fixture save "$DATA" "$case_dir/stopped-tree" || return 1
                    files_snapshot | sort >"$case_dir/before-files" || return 1
                elif [[ ${variation:-} == snapshot-fail ]]; then
                    printf 'allocation fault' >"$BACKUP/objects-stopped"
                elif [[ ${variation:-} == stopped-mount ]]; then
                    mkdir "$DATA/state/offender"
                    mount --bind "$case_dir/mount-source" "$DATA/state/offender" || return 1
                elif [[ ${variation:-} == stopped-* ]]; then
                    runtime_fixture unsafe "$DATA" "${variation#stopped-}" || return 1
                fi
                if [[ $scenario == runtime-refusals ]]; then runtime_fixture save "$DATA" "$case_dir/refusal-tree" || return 1; fi
            fi;;
        start|restart) touch "$case_dir/active";;
    esac
}
dns_preflight() { helper domain "$DOMAIN"; helper ipv4 "$PUBLIC_IP"; }
socks_probe() { return 0; }
initialize_update_state() {
    if [[ $scenario == *-generation ]]; then
        python3 "$ROOT/tests/update_state_fixture.py" baseline "$case_dir"
    fi
    # Existing legacy cases deliberately use a synthetic baseline binary.
    return 0
}
wait_ready() { [[ -f $case_dir/active ]]; }
path_health() { helper runtime-contract "$CONFIG" "$DATA"; helper config-info "$CONFIG" >/dev/null; }
recent_logs() { return 0; }
download_candidate() {
    CANDIDATE="$TMP/candidate"
    if [[ $scenario == *-generation ]]; then
        cp "${TELEMT_UPDATE_ARTIFACTS:?Verified official baseline required}/baseline" "$CANDIDATE"
        [[ $(sha256sum "$CANDIDATE" | cut -d' ' -f1) == 53da315a9f61975913235f72c4adb413313089b966ffcca700653b4663d3d964 ]]
        chmod 0755 "$CANDIDATE"; return
    fi
    # Keep production's version and strict supplied-config probe assertions.
    printf '#!/bin/sh\nversion=%s\n' "$SUPPORTED_TELEMT_VERSION" >"$CANDIDATE"
    cat >>"$CANDIDATE" <<'EOF'
case $1 in
 --version) printf 'telemt %s\n' "$version";;
 healthcheck) ! grep -q '^__telemt_web_manager_unknown_contract' "$2";;
 *) exit 1;;
esac
EOF
    chmod 0755 "$CANDIDATE"
}
create_lineage() {
    local host=$1 auth=$2
    mkdir -p "$CERT_ROOT/live/$host" "$CERT_ROOT/archive/$host" "$CERT_ROOT/renewal"
    for part in cert chain fullchain privkey; do
        if [[ $part == privkey ]]; then cp "$sandbox/key" "$CERT_ROOT/archive/$host/${part}1.pem";
        else cp "$sandbox/cert" "$CERT_ROOT/archive/$host/${part}1.pem"; fi
        ln -s "../../archive/$host/${part}1.pem" "$CERT_ROOT/live/$host/$part.pem"
    done
    {
        printf 'version = 2.9.0\narchive_dir = %s/archive/%s\n' "$CERT_ROOT" "$host"
        for part in cert chain fullchain privkey; do printf '%s = %s/live/%s/%s.pem\n' "$part" "$CERT_ROOT" "$host" "$part"; done
        printf '[renewalparams]\nauthenticator = %s\nserver = https://acme.invalid/directory\n' "$auth"
        if [[ $auth == webroot ]]; then printf 'webroot_path = %s,\n[[webroot_map]]\n%s = %s\n' "$ACME_ROOT" "$host" "$ACME_ROOT"; fi
    } >"$CERT_ROOT/renewal/$host.conf"
}
certbot() {
    if [[ $1 == delete ]]; then
        if [[ $scenario == delete-failure && $* != *--help* ]]; then return 1; fi
        command certbot --config-dir "$CERT_ROOT" --work-dir "$case_dir/certbot-work" \
            --logs-dir "$case_dir/certbot-logs" "$@"
    else
        [[ $1 == certonly ]] || return 1
        printf issued >>"$case_dir/issuance"
        create_lineage "$DOMAIN" "$kind"
    fi
}
uninstall_quiet() {
    real_uninstall_quiet || return 1
    [[ $scenario != failure-A ]]
}
uninstall_remove_files() {
    if [[ $scenario == runtime-* ]]; then touch "$case_dir/removal-called"; fi
    [[ $scenario != failure-B && $scenario != failure-legacy ]] || return 1
    if [[ $scenario == runtime-churn* ]]; then runtime_fixture check-backup "$DATA" "$BACKUP" "$case_dir/stopped-tree" || return 1; fi
    real_uninstall_remove_files || return 1
    if [[ $scenario == signal ]]; then kill -TERM "$BASHPID"; fi
    [[ $scenario != failure-C && $scenario != failure-C-generation && $scenario != runtime-churn-rollback ]]
}
uninstall_remove_account() {
    real_uninstall_remove_account || return 1
    [[ $scenario != failure-D ]]
}
files_snapshot() {
    for extra in "$case_dir/original-toml" "$case_dir/foreign-owned"; do if [[ -f $extra ]]; then sha256sum "$extra"; fi; done
    command find "$CONFIG_DIR" "$DATA" "$STATE" "$NGINX_ROOT" -type f -exec sha256sum {} +; sha256sum "$BIN" "$UNIT" "$RENEW_HOOK"
    if [[ -d ${UNIT}.d ]]; then command find "${UNIT}.d" -type f -exec sha256sum {} +; fi
    if [[ -f ${UNIT%/*}/telemt-web-manager-recovery.service ]]; then sha256sum "${UNIT%/*}/telemt-web-manager-recovery.service"; fi; }
foreign_snapshot() { command find "$CERT_ROOT/archive/foreign.example.com" "$CERT_ROOT/live/foreign.example.com" "$CERT_ROOT/renewal/foreign.example.com.conf" "$CERT_ROOT/accounts" -type f -exec sha256sum {} + | sort; }
cert_snapshot() { command find "$CERT_ROOT" -type f -exec sha256sum {} + | sort; }
runtime_refusals() {
    local result variation drift_target='' before_services backup
    mkdir "$case_dir/mount-source"
    for variation in metadata-fail stop-fail active-after-stop snapshot-fail \
        drift-binary drift-config drift-unit drift-manifest drift-link drift-index drift-certificate drift-vhost drift-stream \
        stopped-symlink stopped-hardlink stopped-fifo stopped-socket stopped-mount stopped-owner stopped-mode stopped-xattr stopped-char stopped-block; do
        case $variation in
            drift-binary) drift_target=$BIN;; drift-config) drift_target=$CONFIG;; drift-unit) drift_target=$UNIT;;
            drift-manifest) drift_target=$STATE/manifest.json;; drift-link) drift_target=$STATE/web-link.txt;;
            drift-index) drift_target=$DATA/public/index.html;; drift-certificate) drift_target=$STATE/certificate.json;;
            drift-vhost) drift_target=$NGINX_ROOT/conf.d/telemt-web-manager.conf;;
            drift-stream) drift_target=$NGINX_ROOT/stream-enabled/stream.conf;;
        esac
        if [[ $variation == drift-* ]]; then cp "$drift_target" "$case_dir/static-original"; fi
        # Golden evidence includes the intentional concurrent edit. The manager
        # must leave it intact, never silently restore an older pre-stop copy.
        files_snapshot | sort >"$case_dir/refusal-files"
        runtime_fixture save "$DATA" "$case_dir/refusal-tree"
        nss_before=$(cat "$FIXTURE_ACCOUNTS/passwd" "$FIXTURE_ACCOUNTS/group")
        before_services=$(wc -l <"$case_dir/services")
        cp "$case_dir/reloads" "$case_dir/refusal-reloads"
        mkdir -p "$TMP"; rm -f "$case_dir/removal-called" "$case_dir/last-backup"
        set +e
        (set -Eeuo pipefail; trap cleanup EXIT; take_lock; uninstall_manager) >"$case_dir/uninstall.log" 2>&1
        result=$?; set -e
        [[ $result != 0 && -f $BIN && -f $UNIT && -f $STATE/manifest.json && -f $STATE/web-link.txt ]]
        [[ -f $case_dir/active && -f $case_dir/enabled && ! -e $case_dir/removal-called ]]
        [[ $(cat "$FIXTURE_ACCOUNTS/passwd" "$FIXTURE_ACCOUNTS/group") == "$nss_before" ]]
        cmp "$case_dir/before-cert" <(cert_snapshot)
        cmp "$case_dir/refusal-reloads" "$case_dir/reloads"
        if grep -qE 'CRITICAL:|Telemt uninstall succeeded' "$case_dir/uninstall.log"; then die 'Unexpected successful uninstall or failed rollback'; fi
        runtime_fixture check "$DATA" "$case_dir/refusal-tree"
        if [[ $variation == drift-* ]]; then
            cp "$case_dir/static-original" "$case_dir/static-expected"
            printf '\n# deterministic concurrent static drift\n' >>"$case_dir/static-expected"
            cmp "$case_dir/static-expected" "$drift_target"
            cat "$case_dir/static-original" >"$drift_target"
            rm "$case_dir/static-original" "$case_dir/static-expected"
        fi
        if [[ $variation == stopped-* ]]; then
            if [[ $variation == stopped-mount ]]; then umount "$DATA/state/offender"; rmdir "$DATA/state/offender"
            else rm "$DATA/state/offender"; fi
        fi
        cmp "$case_dir/refusal-files" <(files_snapshot | sort)
        if [[ $variation == metadata-fail || $variation == drift-* && $variation != drift-vhost && $variation != drift-stream ]]; then
            if tail -n +"$((before_services+1))" "$case_dir/services" | grep -Eq '^(disable|stop|start|daemon-reload)'; then die 'Service mutated before durable metadata'; fi
        else
            tail -n +"$((before_services+1))" "$case_dir/services" | grep -q '^start telemt.service'
        fi
        backup=$(cat "$case_dir/last-backup")
        if [[ $variation != metadata-fail && $variation != drift-* ]]; then
            jq -e '.phase == "pre-stop" and .service.active == "active" and .service.enabled == "enabled" and (.removal_started != true)' "$backup/uninstall.json" >/dev/null
        fi
        printf 'ok - runtime %s refusal: no deletion; DATA/static/Nginx/account/certificate intact; prior service restored\n' "$variation"
    done
}
for scenario in preserve-standalone preserve-webroot stopped expired delete delete-failure \
    failure-A failure-B failure-C failure-D failure-groupdel failure-legacy failure-live-uid signal legacy-preserve missing malformed schema vhost stream unit dropin symlink mount account foreign-state foreign-lineage shared-files lock \
    runtime-churn runtime-churn-rollback runtime-refusals preserve-generation delete-generation failure-C-generation; do
    case_dir="$sandbox/$scenario"; mkdir "$case_dir"
    export UNINSTALL_FIXTURE_ROOT=$case_dir FIXTURE_ACCOUNTS="$case_dir/accounts"
    BIN="$case_dir/bin/telemt" CONFIG_DIR="$case_dir/config" CONFIG="$CONFIG_DIR/telemt.toml"
    UNIT="$case_dir/telemt.service" DATA="$case_dir/data" STATE="$case_dir/state"
    NGINX_ROOT="$case_dir/nginx" CERT_ROOT="$case_dir/certs" ACME_ROOT="$case_dir/acme"
    RENEW_HOOK="$CERT_ROOT/renewal-hooks/deploy/telemt-web-manager" BACKUP_ROOT="$case_dir/backups"
    LOCK="$case_dir/lock" TMP="$case_dir/tmp"
    if [[ $scenario == *-generation ]]; then
        BIN="$case_dir/usr/local/bin/telemt" CONFIG_DIR="$case_dir/etc/telemt" CONFIG="$CONFIG_DIR/telemt.toml"
        UNIT="$case_dir/etc/systemd/system/telemt.service" DATA="$case_dir/var/lib/telemt" STATE="$case_dir/var/lib/telemt-web-manager"
        BACKUP_ROOT="$case_dir/root/telemt-backups"
        mkdir -p "$case_dir/usr/local/bin" "$case_dir/etc/systemd/system" "$case_dir/var/lib" "$case_dir/root"
    fi
    mkdir -p "$TMP" "$case_dir/bin" "$case_dir/manager/lib"
    cp "$ROOT/telemt-web-manager.sh" "$case_dir/manager/telemt-web-manager.sh"
    cp "$ROOT/lib/safety.py" "$case_dir/manager/lib/safety.py"
    chmod 0755 "$case_dir/manager/telemt-web-manager.sh"
    BASE_DIR="$case_dir/manager" HELPER="$case_dir/manager/lib/safety.py"
    printf '#!/bin/sh\nexec "%s/telemt-web-manager.sh" "$@"\n' "$BASE_DIR" >"$case_dir/bin/telemt-web-manager"
    chmod 0755 "$case_dir/bin/telemt-web-manager"
    DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10 EMAIL=operator@example.com AGREE_TOS=1
    kind=webroot
    if [[ $scenario == preserve-standalone ]]; then kind=standalone; cp -r tests/fixtures/nginx "$NGINX_ROOT";
    else cp -r tests/fixtures/nginx-3x-ui "$NGINX_ROOT"; fi
    mkdir -p "$NGINX_ROOT/conf.d"
    set +e
    (set -Eeuo pipefail; trap cleanup EXIT; install_manager) >"$case_dir/install.log" 2>&1
    result=$?; set -e
    if (( result )); then cat "$case_dir/install.log"; exit 1; fi
    if [[ $scenario == *-generation ]]; then python3 "$ROOT/tests/update_state_fixture.py" create "$case_dir"; fi
    [[ -f $STATE/manifest.json && -f $STATE/certificate.json && $(cat "$case_dir/issuance") == issued ]]
    if [[ $scenario == runtime-* ]]; then runtime_fixture seed "$DATA"; fi
    if [[ $scenario == runtime-churn-rollback ]]; then
        for object in "$BIN" "$CONFIG_DIR" "$UNIT" "$STATE" "$NGINX_ROOT"; do
            runtime_fixture save "$object" "$case_dir/control-$(basename "$object").json"
        done
    fi
    if [[ $scenario == legacy-preserve || $scenario == failure-legacy ]]; then rm "$STATE/certificate.json"; fi
    # Preserve an unrelated lineage and Certbot account; never call an ACME server.
    create_lineage foreign.example.com standalone
    mkdir "$CERT_ROOT/accounts"; printf foreign >"$CERT_ROOT/accounts/keep"
    blocker=''
    if [[ $scenario == failure-live-uid ]]; then
        # A real process with the managed numeric UID; the manager must refuse
        # deletion and must never blindly kill an arbitrary UID process.
        setpriv --reuid 424242 --regid 424242 --clear-groups python3 -c \
            'import os,signal; os.write(3,b"ready\n"); os.close(3); signal.pause()' 3>"$DATA/state/uid-ready" &
        blocker=$!
        for ((attempt=0; attempt<1000; attempt++)); do
            grep -qx ready "$DATA/state/uid-ready" && break
            sleep 0.01
        done
        grep -qx ready "$DATA/state/uid-ready" && kill -0 "$blocker"
    fi
    files_snapshot | sort >"$case_dir/before-files"
    cert_snapshot >"$case_dir/before-cert"
    foreign_snapshot >"$case_dir/before-foreign"
    if [[ $scenario == runtime-refusals ]]; then
        CONFIRM_UNINSTALL=1 DELETE_CERTIFICATE=0
        runtime_refusals
        [[ $("$case_dir/bin/telemt-web-manager" --help) == *"Telemt WEB Manager $SCRIPT_VERSION"* ]]
        cmp "$ROOT/telemt-web-manager.sh" "$BASE_DIR/telemt-web-manager.sh"
        cmp "$ROOT/lib/safety.py" "$HELPER"
        rm -rf "$case_dir"
        continue
    fi
    case $scenario in
        failure-groupdel) export FIXTURE_GROUPDEL_FAIL=1;;
        mount) mount --bind "$DATA" "$DATA";;
        stopped) rm "$case_dir/active" "$case_dir/enabled";;
        expired)
            openssl req -x509 -key "$sandbox/key" -days 1 -subj /CN=proxy.example.com \
                -addext subjectAltName=DNS:proxy.example.com -out "$CERT_ROOT/archive/$DOMAIN/fullchain1.pem" >/dev/null 2>&1
            cert_snapshot >"$case_dir/before-cert";;
        missing) rm "$STATE/manifest.json";;
        malformed) printf 'bad json' >"$STATE/manifest.json";;
        schema) jq '.schema=99' "$STATE/manifest.json" >"$case_dir/m"; cp "$case_dir/m" "$STATE/manifest.json";;
        vhost) printf '# manual\n' >>"$NGINX_ROOT/conf.d/telemt-web-manager.conf";;
        stream) sed -i 's/127.0.0.1:7444/127.0.0.1:7445/' "$NGINX_ROOT/stream-enabled/stream.conf";;
        unit) printf '# changed\n' >>"$UNIT";;
        symlink) mv "$CONFIG" "$case_dir/original-toml"; ln -s "$case_dir/original-toml" "$CONFIG";;
        account) sed -i 's/424242/424243/g' "$FIXTURE_ACCOUNTS/passwd";;
        foreign-state) jq '.domain="foreign.example.com"' "$STATE/certificate.json" >"$case_dir/m"; cp "$case_dir/m" "$STATE/certificate.json";;
        foreign-lineage) sed -i "s@$CERT_ROOT/archive/$DOMAIN@$CERT_ROOT/archive/foreign.example.com@" "$CERT_ROOT/renewal/$DOMAIN.conf";;
        shared-files) printf shared >"$case_dir/foreign-owned"; command chown 424242:424242 "$case_dir/foreign-owned";;
        lock) helper lock-path "$LOCK" >/dev/null; exec 8<>"$LOCK"; flock -n 8;;
    esac
    # Snapshot the deliberately changed state for pre-mutation refusals too.
    command find "$case_dir" -path "$TMP" -prune -o -path "$BACKUP_ROOT" -prune -o -type f -print | sort >"$case_dir/pre-paths"
    files_snapshot | sort >"$case_dir/before-refusal"
    cert_snapshot >"$case_dir/before-refusal-cert"
    backup_before=$(command find "$BACKUP_ROOT" -type f -exec sha256sum {} + | sort)
    nss_before=$(cat "$FIXTURE_ACCOUNTS/passwd" "$FIXTURE_ACCOUNTS/group")
    prior_services=$(wc -l <"$case_dir/services")
    mkdir -p "$TMP"; CONFIRM_UNINSTALL=1 DELETE_CERTIFICATE=0
    if [[ $scenario == delete || $scenario == delete-generation || $scenario == delete-failure || $scenario == foreign-lineage ]]; then DELETE_CERTIFICATE=1; fi
    set +e
    (set -Eeuo pipefail; trap cleanup EXIT; trap 'exit 130' INT; trap 'exit 143' TERM HUP;
     take_lock; uninstall_manager) >"$case_dir/uninstall.log" 2>&1
    result=$?
    set -e
    case $scenario in
        runtime-churn)
            [[ $result == 0 && ! -e $DATA && ! -e $BIN && ! -e $UNIT && ! -e $CONFIG_DIR && ! -e $STATE/manifest.json && ! -e $STATE/web-link.txt ]]
            [[ ! -e $FIXTURE_ACCOUNTS/passwd && ! -e $FIXTURE_ACCOUNTS/group && -f $STATE/certificate.json ]]
            [[ ! -e $case_dir/active && ! -e $case_dir/enabled ]]
            grep -qx 'churn complete before stop' "$case_dir/barrier"
            cmp "$case_dir/before-cert" <(cert_snapshot)
            [[ $(cat "$case_dir/issuance") == issued ]]
            helper acme-state "$NGINX_ROOT" "$DOMAIN" "$ACME_ROOT"
            printf 'ok - deterministic ACTIVE runtime rewrite/create/atomic replace/nested create/delete; complete STOPPED backup incl final shutdown write; uninstall succeeds without retry/sleep\n';;
        preserve-*|legacy-preserve|stopped|expired)
            [[ $result == 0 && ! -e $CONFIG_DIR && ! -e $DATA && ! -e $BIN && ! -e $UNIT && ! -e $STATE/manifest.json && ! -e $STATE/web-link.txt ]]
            [[ ! -e $FIXTURE_ACCOUNTS/passwd && ! -e $FIXTURE_ACCOUNTS/group && -f $STATE/certificate.json && -f $RENEW_HOOK ]]
            if [[ $scenario == preserve-generation ]]; then
                [[ ! -e $STATE/telemt-release.json && ! -e $STATE/telemt-generation.json && ! -e $STATE/update-journal.json && ! -e ${UNIT}.d && ! -e ${UNIT%/*}/telemt-web-manager-recovery.service ]]
            fi
            cmp "$case_dir/before-cert" <(cert_snapshot)
            if [[ $kind == webroot ]]; then helper acme-state "$NGINX_ROOT" "$DOMAIN" "$ACME_ROOT"; fi
            if [[ $scenario == preserve-* ]]; then
                mkdir "$TMP"
                set +e
                (set -Eeuo pipefail; trap cleanup EXIT; install_manager) >"$case_dir/reinstall.log" 2>&1
                result=$?; set -e
                if (( result )); then cat "$case_dir/reinstall.log"; exit 1; fi
                [[ $(cat "$case_dir/issuance") == issued && -f $STATE/manifest.json && -f $STATE/web-link.txt ]]
                cmp "$case_dir/before-cert" <(cert_snapshot)
                helper runtime-contract "$CONFIG" "$DATA"
                printf 'ok - managed install -> uninstall keep %s certificate -> fresh same-domain install; ZERO new issuance, same key/serial/renewal; WEB contract recreated\n' "$kind"
            else printf 'ok - managed %s deployment uninstalled without Telemt health/certificate-expiry gate\n' "$scenario"; fi;;
        delete|delete-generation|delete-failure)
            [[ ! -e $BIN && ! -e $STATE/manifest.json && ! -e $FIXTURE_ACCOUNTS/passwd ]]
            if [[ $scenario == delete || $scenario == delete-generation ]]; then
                [[ $result == 0 && ! -e $CERT_ROOT/live/$DOMAIN && ! -e $STATE && ! -e $ACME_ROOT && ! -e $NGINX_ROOT/conf.d/telemt-web-manager-acme.conf ]]
                [[ ! -e $RENEW_HOOK ]]
                printf 'ok - installed real Certbot delete removes EXACT local lineage and unused webroot/state; foreign lineage/account unchanged\n'
            else
                [[ $result != 0 && -f $STATE/certificate.json && -d $ACME_ROOT && -f $CERT_ROOT/live/$DOMAIN/fullchain.pem ]]
                grep -q 'Telemt uninstall succeeded. Certificate cleanup failed' "$case_dir/uninstall.log"
                printf 'ok - certificate deletion failure retains ownership evidence and DOES NOT resurrect Telemt\n'
            fi
            cmp "$case_dir/before-foreign" <(foreign_snapshot)
            [[ $(cat "$CERT_ROOT/accounts/keep") == foreign ]];;
        failure-*|signal|runtime-churn-rollback)
            if [[ $scenario == signal ]]; then [[ $result == 143 ]]; fi
            [[ $result != 0 && -f $case_dir/active && -f $case_dir/enabled && -f $FIXTURE_ACCOUNTS/passwd && -f $FIXTURE_ACCOUNTS/group ]]
            cmp "$case_dir/before-files" <(files_snapshot | sort)
            cmp "$case_dir/before-cert" <(cert_snapshot)
            if grep -q CRITICAL "$case_dir/uninstall.log"; then cat "$case_dir/uninstall.log"; exit 1; fi
            if [[ $scenario == runtime-churn-rollback ]]; then
                [[ $(cat "$FIXTURE_ACCOUNTS/passwd" "$FIXTURE_ACCOUNTS/group") == "$nss_before" ]]
                grep -qx 'churn complete before stop' "$case_dir/barrier"
                runtime_fixture check "$DATA" "$case_dir/stopped-tree"
                for object in "$BIN" "$CONFIG_DIR" "$UNIT" "$STATE" "$NGINX_ROOT"; do
                    runtime_fixture check "$object" "$case_dir/control-$(basename "$object").json"
                done
                printf 'ok - authoritative STOPPED tree rollback: exact membership/bytes/modes/UID/GID incl create/replace/delete/final shutdown write\n'
            fi
            printf 'ok - uninstall %s rollback restores exact files/Nginx/link/manifest/account/service state; certificate unchanged\n' "$scenario";;
        *)
            [[ $result != 0 && -e $BIN && -e $DATA && -e $FIXTURE_ACCOUNTS/passwd ]]
            [[ $(command find "$BACKUP_ROOT" -type f -exec sha256sum {} + | sort) == "$backup_before" ]]
            [[ $(cat "$FIXTURE_ACCOUNTS/passwd" "$FIXTURE_ACCOUNTS/group") == "$nss_before" ]]
            cmp "$case_dir/before-refusal" <(files_snapshot | sort)
            cmp "$case_dir/before-refusal-cert" <(cert_snapshot)
            ! tail -n +"$((prior_services+1))" "$case_dir/services" | grep -Eq '^(disable|stop|start|reload|daemon-reload)'
            printf 'ok - uninstall %s ownership/lock refusal BEFORE destructive mutation\n' "$scenario";;
    esac
    if [[ $scenario == *-generation ]]; then
        python3 "$ROOT/tests/update_state_fixture.py" retained "$case_dir"
        if [[ $scenario == failure-C-generation || $scenario == preserve-generation ]]; then
            helper update-gate-contract
            [[ -f $STATE/telemt-release.json && -f $STATE/telemt-generation.json && -f $STATE/update-journal.json ]]
            if [[ $scenario == failure-C-generation ]]; then
                printf 'ok - v0.2 uninstall rollback restores exact receipt/journal/generation/gate/recovery and prior service; root-owned LKG retained\n'
            else
                printf 'ok - v0.2 uninstall-preserve-cert -> fresh Install recreates baseline receipt/generation/gate BEFORE start; ZERO issuance, root-owned LKG retained\n'
            fi
        else
            [[ ! -e $STATE/telemt-release.json && ! -e $STATE/telemt-generation.json && ! -e $STATE/update-journal.json && ! -e ${UNIT}.d && ! -e ${UNIT%/*}/telemt-web-manager-recovery.service ]]
            printf 'ok - v0.2 uninstall removes exact update controls; root-normalized sealed LKG/evidence retained and account cleanup remains strict\n'
        fi
    fi
    if [[ -n $blocker ]]; then kill -0 "$blocker"; kill "$blocker"; wait "$blocker" || true; blocker=''; fi
    unset FIXTURE_GROUPDEL_FAIL
    if [[ $scenario == mount ]]; then umount "$DATA"; fi
    [[ $("$case_dir/bin/telemt-web-manager" --help) == *"Telemt WEB Manager $SCRIPT_VERSION"* ]]
    cmp "$ROOT/telemt-web-manager.sh" "$BASE_DIR/telemt-web-manager.sh"
    cmp "$ROOT/lib/safety.py" "$HELPER"
    # This fixture uses inert NSS, so discard its remaining files between cases.
    if [[ $scenario == lock ]]; then flock -u 8; exec 8>&-; fi
    rm -rf "$case_dir"
done
