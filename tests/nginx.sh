#!/usr/bin/env bash
# Real Nginx integration on private test ports. No production config is read/written.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
root=$PWD
test_dir=$(mktemp -d)
# Root-run distro guests still use unprivileged Nginx workers. Inert assets only.
chmod 0755 "$test_dir"
nginx_pid='' origin_pid=''
finish() {
    if [[ -n $nginx_pid ]]; then kill "$nginx_pid" 2>/dev/null || true; wait "$nginx_pid" 2>/dev/null || true; fi
    if [[ -n $origin_pid ]]; then kill "$origin_pid" 2>/dev/null || true; wait "$origin_pid" 2>/dev/null || true; fi
    rm -rf -- "$test_dir"
}
trap finish EXIT
cp -r "${1:-tests/fixtures/nginx}" "$test_dir/nginx"
# Mandatory package bytes, copied inside the same include trust boundary.
cp /etc/nginx/mime.types "$test_dir/nginx/mime.types"
sed -i 's/http {/http { include mime.types;/' "$test_dir/nginx/nginx.conf"
mkdir -p "$test_dir/nginx/conf.d" "$test_dir/logs" "$test_dir/temp"
mkdir -p "$test_dir/acme/.well-known/acme-challenge"
printf challenge-fixture >"$test_dir/acme/.well-known/acme-challenge/probe"
python3 lib/safety.py acme-plan "$test_dir/nginx" proxy.example.com "$test_dir/acme-plan.json" "$test_dir/acme"
python3 - "$test_dir/acme-plan.json" <<'PY'
import json, pathlib, sys
for edit in json.loads(pathlib.Path(sys.argv[1]).read_text())['edits']:
    pathlib.Path(edit['path']).write_text(edit['content'])
PY
python3 lib/safety.py nginx-plan "$test_dir/nginx" proxy.example.com "$test_dir/plan.json" "$test_dir/acme"
python3 - "$test_dir/plan.json" "$test_dir/nginx/mime.types" <<'PY'
import hashlib, json, pathlib, sys
path = pathlib.Path(sys.argv[2])
assert path.read_bytes() == pathlib.Path('/etc/nginx/mime.types').read_bytes()
assert json.loads(pathlib.Path(sys.argv[1]).read_text())['snapshot'][str(path)] == hashlib.sha256(path.read_bytes()).hexdigest()
PY
printf 'ok - real Ubuntu package mime.types parsed and integrity-snapshotted in Nginx/ACME plans\n'
python3 - "$test_dir/plan.json" <<'PY'
import json, pathlib, sys
for edit in json.loads(pathlib.Path(sys.argv[1]).read_text())['edits']:
    pathlib.Path(edit['path']).write_text(edit['content'])
PY
for name in proxy panel reality; do
    openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=$name.example.com" \
        -addext "subjectAltName=DNS:$name.example.com" \
        -keyout "$test_dir/$name.key.pem" -out "$test_dir/$name.cert.pem" >/dev/null 2>&1
done
cat "$test_dir/"*.cert.pem >"$test_dir/ca.pem"
python3 - "$test_dir" <<'PY'
from pathlib import Path
import re, sys
t = Path(sys.argv[1])
for p in (t/'nginx').rglob('*'):
    if not p.is_file():
        continue
    text = re.sub(r'listen\s+443;', 'listen 127.0.0.1:14443;', p.read_text())
    text = re.sub(r'listen\s+\[::\]:443;', 'listen [::1]:14443;', text)
    text = re.sub(r'listen\s+80;', 'listen 127.0.0.1:18082;', text)
    text = re.sub(r'listen\s+\[::\]:80;', 'listen [::1]:18082;', text)
    text = text.replace(':7444', ':17444').replace(':18080', ':18081')
    text = re.sub(r'(?<![0-9])7443(?![0-9])', '17443', text)
    text = re.sub(r'(?<![0-9])8443(?![0-9])', '18443', text)
    text = re.sub(r'(?<![0-9])9443(?![0-9])', '19443', text)
    name = ('proxy' if p.name == 'telemt-web-manager.conf' else
            'reality' if 'server_name reality.example.com;' in text else 'panel')
    text = re.sub(r'(ssl_certificate\s+)[^;]+;', lambda m: m[1] + str(t/f'{name}.cert.pem') + ';', text)
    text = re.sub(r'(ssl_certificate_key\s+)[^;]+;', lambda m: m[1] + str(t/f'{name}.key.pem') + ';', text)
    p.write_text(text)
stream = next(p for p in (t/'nginx').rglob('stream.conf'))
planned = stream.read_text()
(t/'planned-stream').write_text(planned)
# Keep the initial SNI table active until the first verified TLS refusal.
stream.write_text(re.sub(r'^.*proxy\.example\.com.*\n', '', planned, flags=re.M))
if (t/'nginx/sites-enabled').exists():
    # Inert stand-in for Xray's existing PROXY-to-TLS REALITY forwarding only.
    stream.write_text(stream.read_text() +
        '\nserver { listen 127.0.0.1:18443 proxy_protocol; proxy_pass 127.0.0.1:19443; }\n')
    (t/'planned-stream').write_text(planned +
        '\nserver { listen 127.0.0.1:18443 proxy_protocol; proxy_pass 127.0.0.1:19443; }\n')
else:
    for name, port in (('panel', 18443), ('reality', 19443)):
        (t/f'nginx/conf.d/fixture-{name}.conf').write_text(
            f'server {{ listen 127.0.0.1:{port} ssl proxy_protocol; server_name {name}.example.com; '
            f'ssl_certificate {t}/{name}.cert.pem; ssl_certificate_key {t}/{name}.key.pem; '
            f'location / {{ return 200 "{name}\\n"; }} }}\n')
(t/'active-stream-path').write_text(str(stream))
p = t/'nginx/nginx.conf'
temporary_paths = ''.join(f'{kind}_temp_path {t}/temp/{kind};\n' for kind in
                         ('client_body', 'proxy', 'fastcgi', 'uwsgi', 'scgi'))
p.write_text('load_module /usr/lib/nginx/modules/ngx_stream_module.so;\n'
             + f'pid {t}/nginx.pid;\nerror_log {t}/logs/error.log;\n'
             + p.read_text().replace('http {', f'http {{\n{temporary_paths}access_log {t}/logs/access.log;'))
PY
/usr/sbin/nginx -t -p "$test_dir/" -c "$test_dir/nginx/nginx.conf"
python3 "$root/tests/origin.py" >"$test_dir/origin.log" 2>&1 &
origin_pid=$!
/usr/sbin/nginx -p "$test_dir/" -c "$test_dir/nginx/nginx.conf" -g 'daemon off;' >"$test_dir/nginx.log" 2>&1 &
nginx_pid=$!
# Wait for the OLD route, never for a randomly timed successful reload.
ready=0
for (( attempt=0; attempt<50; attempt++ )); do
    code=0
    curl --noproxy '*' -s --max-time 1 --cacert "$test_dir/ca.pem" \
        --resolve proxy.example.com:14443:127.0.0.1 https://proxy.example.com:14443/ \
        -o /dev/null || code=$?
    if [[ $code == 60 ]]; then ready=1; break; fi
    sleep 0.1
done
[[ $ready == 1 ]]
# Distinct certificates prove that the active table still selects REALITY.
certificate_route() {
    local sni=$1 expected=$2
    timeout 5 openssl s_client -connect 127.0.0.1:14443 -servername "$sni" \
        -CAfile "$test_dir/ca.pem" -verify_return_error -verify_hostname "$expected.example.com" \
        </dev/null >"$test_dir/peer" 2>"$test_dir/tls.log"
    [[ $(openssl x509 -in "$test_dir/peer" -noout -fingerprint -sha256) == \
       "$(openssl x509 -in "$test_dir/$expected.cert.pem" -noout -fingerprint -sha256)" ]]
}
certificate_route proxy.example.com reality
certificate_route panel.example.com panel
certificate_route reality.example.com reality
certificate_route unknown.example.com reality
# Exercise the production Fresh Install path checker with real verified HTTPS.
# Only lifecycle identity and port/address transport are fixture adapters.
# shellcheck source=telemt-web-manager.sh
source ./telemt-web-manager.sh
DOMAIN=proxy.example.com
nginx_test() { /usr/sbin/nginx -t -p "$test_dir/" -c "$test_dir/nginx/nginx.conf" >/dev/null 2>&1; }
service_active() { return 0; }
listener_ready() { return 0; }
process_identity() { return 0; }
socks_probe() { return 0; }
activated=0 reload_requested=0
# Acknowledge the installer's reload while holding the old workers' SNI table.
nginx_reload() { reload_requested=1; }
http_ok() {
    local arg code=0
    local -a args=()
    for arg in "$@"; do
        arg=${arg//:443/:14443}
        arg=${arg//:18080/:18081}
        # The "public" fixture endpoint has explicit test DNS on loopback.
        [[ $arg != "https://$DOMAIN/" ]] || arg="https://$DOMAIN:14443/"
        args+=("$arg")
    done
    local output
    output=$(curl --noproxy '*' -s --connect-timeout 5 --max-time 20 \
        --cacert "$test_dir/ca.pem" -H "X-Forwarded-For: 127.0.0.1" --resolve "$DOMAIN:14443:127.0.0.1" \
        --output /dev/null --write-out '%{http_code}' "${args[@]}") || code=$?
    if [[ $* == *https://* && $activated == 0 ]]; then
        [[ $code == 60 ]] || return 97
        printf 'ok - controlled first HTTPS request rejected the REALITY certificate (curl 60)\n'
        [[ $reload_requested == 1 ]] || return 96
        kill -HUP "$nginx_pid"
        activated=1
        return 1
    fi
    [[ $code == 0 && $output == 200 ]]
}
# Correct configuration is on disk before reload returns; activation is delayed.
cp "$test_dir/planned-stream" "$(cat "$test_dir/active-stream-path")"
nginx_reload
result=0
path_health fresh || result=$?
[[ $activated == 1 ]]
ready=0
for (( attempt=0; attempt<50; attempt++ )); do
    if curl --noproxy '*' -fsS --max-time 1 --cacert "$test_dir/ca.pem" \
        --resolve proxy.example.com:14443:127.0.0.1 https://proxy.example.com:14443/ \
        -o "$test_dir/body" 2>/dev/null && grep -qx canonical "$test_dir/body"; then
        ready=1; break
    fi
    sleep 0.1
done
[[ $ready == 1 ]]
printf 'ok - activated Telegram route now verifies TLS and returns HTTP 200; path_health status=%s\n' "$result"
[[ $result == 0 ]]
certificate_route proxy.example.com proxy
certificate_route panel.example.com panel
certificate_route reality.example.com reality
certificate_route unknown.example.com reality
printf 'ok - controlled SNI reload: production Fresh HTTPS readiness; distinct Telegram/panel/REALITY certificates; default preserved\n'
curl --noproxy '*' -fsS --max-time 5 --cacert "$test_dir/ca.pem" \
    --resolve proxy.example.com:14443:127.0.0.1 \
    -H 'X-Forwarded-For: 203.0.113.10, 203.0.113.11' \
    https://proxy.example.com:14443/ -o "$test_dir/body"
grep -qx canonical "$test_dir/body"
curl --noproxy '*' -fsS --max-time 5 --resolve proxy.example.com:18082:127.0.0.1 \
    http://proxy.example.com:18082/.well-known/acme-challenge/probe -o "$test_dir/challenge"
[[ $(cat "$test_dir/challenge") == challenge-fixture ]]
[[ $(curl --noproxy '*' -s --max-time 5 -o /dev/null -w '%{http_code}' \
    --resolve proxy.example.com:18082:127.0.0.1 http://proxy.example.com:18082/other) == 404 ]]
if [[ -f $test_dir/nginx/sites-enabled/80.conf ]]; then
    [[ $(curl --noproxy '*' -s --max-time 5 -o /dev/null -w '%{http_code}' \
        --resolve panel.example.com:18082:127.0.0.1 http://panel.example.com:18082/) == 301 ]]
fi
if grep -q '\[::1\]:14443' "$test_dir/nginx/stream-enabled/stream.conf" 2>/dev/null; then
    curl --noproxy '*' -fsS --max-time 5 --cacert "$test_dir/ca.pem" \
        --resolve 'proxy.example.com:14443:[::1]' \
        -H 'X-Forwarded-For: 203.0.113.10, 203.0.113.11' \
        https://proxy.example.com:14443/ -o "$test_dir/ipv6-body"
    grep -qx canonical "$test_dir/ipv6-body"
fi
printf 'ok - real Nginx stream/PROXY/TLS/HTTP1.1, canonical XFF and persistent ACME webroot\n'
