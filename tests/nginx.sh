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
cp -r tests/fixtures/nginx "$test_dir/nginx"
mkdir "$test_dir/nginx/conf.d" "$test_dir/logs"
python3 lib/safety.py nginx-plan "$test_dir/nginx" proxy.example.com "$test_dir/plan.json"
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
import sys
t = Path(sys.argv[1])
for p in (t/'nginx').rglob('*.conf'):
    text = p.read_text().replace('listen 443;', 'listen 127.0.0.1:14443;')
    text = text.replace(':7444', ':17444').replace(':18080', ':18081')
    text = text.replace('/etc/letsencrypt/live/proxy.example.com/fullchain.pem', str(t/'cert.pem'))
    text = text.replace('/etc/letsencrypt/live/proxy.example.com/privkey.pem', str(t/'key.pem'))
    p.write_text(text)
p = t/'nginx/nginx.conf'
p.write_text('load_module /usr/lib/nginx/modules/ngx_stream_module.so;\n'
             + f'pid {t}/nginx.pid;\nerror_log {t}/logs/error.log;\n'
             + p.read_text())
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
printf 'ok - real Nginx stream/PROXY/TLS/HTTP1.1 and canonical X-Forwarded-For\n'
