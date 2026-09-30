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
for scenario in free webroot foreign conflict invalid-nginx failed-certbot; do
    case_dir="$sandbox/$scenario"; mkdir "$case_dir"
    TMP="$case_dir/tmp" NGINX_ROOT="$case_dir/nginx" ACME_ROOT="$case_dir/acme"
    CERT_ROOT="$case_dir/certs" BACKUP_ROOT="$case_dir/backups"
    mkdir "$TMP"; cp -r "$fixture" "$NGINX_ROOT"; mkdir -p "$NGINX_ROOT/conf.d"
    DOMAIN=proxy.example.com EMAIL=operator@example.com AGREE_TOS=1
    if [[ $scenario == conflict ]]; then
        # SC2016: retain literal Nginx variables, not shell expansions.
        # shellcheck disable=SC2016
        printf 'server { listen 80; server_name proxy.example.com; return 301 https://$host$request_uri; }\n' >"$NGINX_ROOT/sites-enabled/conflict.conf"
    fi
    cp -r "$NGINX_ROOT" "$case_dir/original"
    ss() { if [[ $scenario != free ]]; then printf occupied; fi; }
    nginx_runtime_identity() { return 0; }
    nginx_port_owned() { [[ $scenario != foreign ]]; }
    nginx_test() { [[ $scenario != invalid-nginx || ! -e $NGINX_ROOT/conf.d/telemt-web-manager-acme.conf ]]; }
    nginx_reload() { printf reload >>"$case_dir/reloads"; }
    systemctl() { return 0; }
    acme_probe() { [[ -d $ACME_ROOT/.well-known/acme-challenge ]]; }
    certbot() {
        [[ $* == *--non-interactive* && $* == *--cert-name* ]] || return 1
        if [[ $scenario == free ]]; then
            [[ $* == *--standalone* ]] || return 1
        else
            [[ $* == *--webroot-path* && $* == *"$ACME_ROOT"* && $* != *--standalone* ]] || return 1
        fi
        printf invoked >"$case_dir/certbot-called"
        [[ $scenario != failed-certbot ]] || return 1
        mkdir -p "$CERT_ROOT/live/$DOMAIN" "$CERT_ROOT/renewal"
        cp "$sandbox/cert" "$CERT_ROOT/live/$DOMAIN/fullchain.pem"
        cp "$sandbox/key" "$CERT_ROOT/live/$DOMAIN/privkey.pem"
        printf '[renewalparams]\nauthenticator = webroot\nwebroot_path = %s,\n[[webroot_map]]\n%s = %s\n' \
            "$ACME_ROOT" "$DOMAIN" "$ACME_ROOT" >"$CERT_ROOT/renewal/$DOMAIN.conf"
    }
    set +e
    (ensure_certificate) >"$case_dir/manager.log" 2>&1
    result=$?
    set -e
    case $scenario in
        free)
            [[ $result == 0 && -f $case_dir/certbot-called ]]
            diff -r "$case_dir/original" "$NGINX_ROOT";;
        webroot)
            [[ $result == 0 && -f $NGINX_ROOT/conf.d/telemt-web-manager-acme.conf && -d $TMP ]]
            helper renewal-contract "$CERT_ROOT" "$DOMAIN" "$ACME_ROOT"
            before=$(sha256sum "$NGINX_ROOT/conf.d/telemt-web-manager-acme.conf")
            (issue_webroot_certificate) >"$case_dir/repeated.log" 2>&1
            [[ $(sha256sum "$NGINX_ROOT/conf.d/telemt-web-manager-acme.conf") == "$before" ]]
            [[ $(grep -c "server_name $DOMAIN;" "$NGINX_ROOT/conf.d/telemt-web-manager-acme.conf") == 1 ]]
            rm "$NGINX_ROOT/conf.d/telemt-web-manager-acme.conf"
            diff -r "$case_dir/original" "$NGINX_ROOT";;
        *)
            [[ $result != 0 ]]
            diff -r "$case_dir/original" "$NGINX_ROOT"
            if [[ $scenario != failed-certbot ]]; then [[ ! -e $case_dir/certbot-called ]]; fi;;
    esac
    printf 'ok - ACME %s\n' "$scenario"
done
