#!/usr/bin/env bash
# Roll back the real upstream include tree with only nginx validation mocked.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
fixture=${1:?Fixture directory required}
# shellcheck source=telemt-web-manager.sh
source ./telemt-web-manager.sh
sandbox=$(mktemp -d)
trap 'rm -rf -- "$sandbox"' EXIT
NGINX_ROOT="$sandbox/nginx" TMP="$sandbox/tmp" BACKUP_ROOT="$sandbox/backups"
DOMAIN=proxy.example.com
cp -r "$fixture" "$NGINX_ROOT"
mkdir "$TMP"
cp -r "$NGINX_ROOT" "$sandbox/original"
nginx_plan
nginx_test() { [[ ! -e $NGINX_ROOT/conf.d/telemt-web-manager.conf ]]; }
nginx_reload() { return 0; }
systemctl() { return 0; }
set +e
(trap cleanup EXIT; backup_begin; ARMED=1 INSTALLING=1; apply_nginx) >"$sandbox/rollback.log" 2>&1
rc=$?
set -e
[[ $rc != 0 ]]
diff -r "$sandbox/original" "$NGINX_ROOT"
printf 'ok - upstream topology validation failure restores every config byte\n'
