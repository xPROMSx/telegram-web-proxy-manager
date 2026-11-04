#!/usr/bin/env bash
# Roll back the real upstream include tree at write/validation/reload boundaries.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
fixture=${1:?Fixture directory required}
for failure in write test reload; do
    (
        # shellcheck source=telemt-web-manager.sh
        source ./telemt-web-manager.sh
        sandbox=$(mktemp -d)
        trap 'rm -rf -- "$sandbox"' EXIT
        NGINX_ROOT="$sandbox/nginx" TMP="$sandbox/tmp" BACKUP_ROOT="$sandbox/backups"
        DOMAIN=proxy.example.com
        cp -rp "$fixture" "$NGINX_ROOT"
        mkdir "$TMP"
        cp -rp "$NGINX_ROOT" "$sandbox/original"
        nginx_plan
        eval "$(declare -f atomic_copy | sed '1s/atomic_copy/fixture_atomic_copy/')"
        atomic_copy() {
            if [[ $failure == write && $2 == "$NGINX_ROOT/conf.d/telemt-web-manager.conf" ]]; then
                return 1
            fi
            fixture_atomic_copy "$@"
        }
        nginx_test() { [[ $failure != test || ! -e $NGINX_ROOT/conf.d/telemt-web-manager.conf ]]; }
        nginx_reload() { [[ $failure != reload || ! -e $NGINX_ROOT/conf.d/telemt-web-manager.conf ]]; }
        systemctl() { return 0; }
        set +e
        (set -Eeuo pipefail; trap cleanup EXIT; backup_begin; ARMED=1 INSTALLING=1; apply_nginx) >"$sandbox/rollback.log" 2>&1
        rc=$?
        set -e
        [[ $rc != 0 ]]
        diff -r "$sandbox/original" "$NGINX_ROOT"
        printf 'ok - upstream topology %s failure restores every config byte\n' "$failure"
    )
done
