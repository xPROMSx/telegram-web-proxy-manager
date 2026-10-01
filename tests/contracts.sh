#!/usr/bin/env bash
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
# shellcheck source=telemt-web-manager.sh
source ./telemt-web-manager.sh
test_dir=$(mktemp -d)
trap 'rm -rf -- "$test_dir"' EXIT
DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10
secret=$(openssl rand -hex 16)
generate_config "$secret" >"$test_dir/config.toml"
unset secret
generate_unit >"$test_dir/unit"
helper runtime-contract "$test_dir/config.toml" "$DATA"
sed 's|quota_state_path = .*|quota_state_path = "/tmp/unsafe-quota"|' "$test_dir/config.toml" >"$test_dir/unsafe.toml"
if helper runtime-contract "$test_dir/unsafe.toml" "$DATA" >"$test_dir/rejection.log" 2>&1; then exit 1; fi
python3 - "$test_dir" <<'PY'
from pathlib import Path
import sys, tomllib
t = Path(sys.argv[1])
c = tomllib.loads((t/'config.toml').read_text())
unit = dict(line.split('=', 1) for line in (t/'unit').read_text().splitlines() if '=' in line)
state = Path(unit['ReadWritePaths'])
assert str(state) == '/var/lib/telemt/state'
assert c['general']['config_strict'] is True
assert c['general']['disable_colors'] is True
assert c['general']['data_path'] == unit['WorkingDirectory'] == '/var/lib/telemt'
for key in ('beobachten_file', 'quota_state_path', 'unknown_dc_log_path',
            'proxy_secret_path', 'proxy_config_v4_cache_path', 'proxy_config_v6_cache_path'):
    assert Path(c['general'][key]).is_relative_to(state), key
assert Path(c['network']['cache_public_ip_path']).is_relative_to(state)
assert Path(c['censorship']['tls_front_dir']).is_relative_to(state)
assert c['general']['unknown_dc_file_log_enabled'] is False
assert c['general']['use_middle_proxy'] is False
assert c['censorship']['tls_emulation'] is False
assert c['logging']['destination'] == 'stderr'
assert unit['User'] == unit['Group'] == 'telemt'
assert unit['CapabilityBoundingSet'] == unit['AmbientCapabilities'] == 'CAP_NET_ADMIN'
assert unit['ProtectSystem'] == 'strict'
assert unit['ExecStart'] == '/usr/local/bin/telemt /etc/telemt/telemt.toml'
assert unit['RestrictAddressFamilies'] == 'AF_INET AF_INET6 AF_UNIX AF_NETLINK'
assert int(unit['TimeoutStopSec']) == 180
PY
printf 'ok - strict config and all active/inactive state paths match the narrow systemd sandbox\n'
