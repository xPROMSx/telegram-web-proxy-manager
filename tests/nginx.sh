#!/usr/bin/env bash
# Real Nginx integration on private test ports. No production config is read/written.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
root=$PWD
test_dir=$(mktemp -d)
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
mkdir -p "$test_dir/nginx/conf.d" "$test_dir/logs"
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
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=proxy.example.com \
    -addext subjectAltName=DNS:proxy.example.com \
    -keyout "$test_dir/key.pem" -out "$test_dir/cert.pem" >/dev/null 2>&1
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
    text = text.replace(':7444', ':17444').replace(':18080', ':18081')
    text = re.sub(r'(ssl_certificate\s+)[^;]+;', lambda m: m[1] + str(t/'cert.pem') + ';', text)
    text = re.sub(r'(ssl_certificate_key\s+)[^;]+;', lambda m: m[1] + str(t/'key.pem') + ';', text)
    p.write_text(text)
p = t/'nginx/nginx.conf'
p.write_text('load_module /usr/lib/nginx/modules/ngx_stream_module.so;\n'
             + f'pid {t}/nginx.pid;\nerror_log {t}/logs/error.log;\n'
             + p.read_text().replace('http {', f'http {{\naccess_log {t}/logs/access.log;'))
PY
/usr/sbin/nginx -t -p "$test_dir/" -c "$test_dir/nginx/nginx.conf"
python3 "$root/tests/origin.py" >"$test_dir/origin.log" 2>&1 &
origin_pid=$!
/usr/sbin/nginx -p "$test_dir/" -c "$test_dir/nginx/nginx.conf" -g 'daemon off;' >"$test_dir/nginx.log" 2>&1 &
nginx_pid=$!
ready=0
for (( attempt=0; attempt<50; attempt++ )); do
    if curl --noproxy '*' -s --max-time 1 --cacert "$test_dir/cert.pem" \
        --resolve proxy.example.com:14443:127.0.0.1 \
        -H 'X-Forwarded-For: 203.0.113.10, 203.0.113.11' \
        https://proxy.example.com:14443/ -o "$test_dir/body" && grep -qx canonical "$test_dir/body"; then
        ready=1; break
    fi
    sleep 0.1
done
[[ $ready == 1 ]]
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
    curl --noproxy '*' -fsS --max-time 5 --cacert "$test_dir/cert.pem" \
        --resolve 'proxy.example.com:14443:[::1]' \
        -H 'X-Forwarded-For: 203.0.113.10, 203.0.113.11' \
        https://proxy.example.com:14443/ -o "$test_dir/ipv6-body"
    grep -qx canonical "$test_dir/ipv6-body"
fi
printf 'ok - real Nginx stream/PROXY/TLS/HTTP1.1, canonical XFF and persistent ACME webroot\n'
