#!/usr/bin/env bash
# Telemt WEB Manager. MIT. Requires Bash 5 and Python 3.11+.
set +x
set -Eeuo pipefail
umask 077
export LC_ALL=C
readonly SCRIPT_VERSION=0.1.0
BASE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
HELPER="$BASE_DIR/lib/safety.py"
BIN=/usr/local/bin/telemt
CONFIG=/etc/telemt/telemt.toml
UNIT=/etc/systemd/system/telemt.service
STATE=/var/lib/telemt-web-manager
DATA=/var/lib/telemt
ACME_ROOT=/var/lib/telemt-web-manager-acme
CERT_ROOT=/etc/letsencrypt
CONFIG_DIR=/etc/telemt
RENEW_HOOK=/etc/letsencrypt/renewal-hooks/deploy/telemt-web-manager
NGINX_ROOT=/etc/nginx
BACKUP_ROOT=/root/telemt-backups
LOCK=/run/lock/telemt-web-manager.lock
TMP='' BACKUP='' DOMAIN='' PUBLIC_IP='' SOCKS='' RELEASE='' CANDIDATE=''
ARMED=0 INSTALLING=0 NGINX_CHANGED=0
CERT_ONLY=0 PLAN_MODE=web
declare -a CHANGED=() ORIGINAL=()

say() { printf '%s\n' "$*"; }
die() { say "ERROR: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null || die "Missing dependency: $1 (see README)"; }
helper() { python3 "$HELPER" "$@"; }
service_active() { systemctl is-active --quiet telemt.service; }
restart_service() { systemctl restart telemt.service; }
nginx_test() { nginx -t >"$TMP/nginx-test.log" 2>&1; }
nginx_reload() { systemctl reload nginx; }
now() { date +%s; }
pause() { sleep 1; }

nginx_runtime_identity() {
    local pid command
    pid=$(systemctl show nginx.service -p MainPID --value)
    [[ $pid =~ ^[1-9][0-9]*$ && -r /proc/$pid/cmdline ]] || return 1
    command=$(tr '\0' ' ' <"/proc/$pid/cmdline")
    [[ $command == 'nginx: master process '* && $command != *' -c'* && $command != *' -p'* ]] || return 1
    nginx -V 2>&1 | grep -q -- '--conf-path=/etc/nginx/nginx.conf' || return 1
    nginx_port_owned 443
}

process_identity() {
    local pid uid gid caps
    pid=$(systemctl show telemt.service -p MainPID --value)
    [[ $pid =~ ^[1-9][0-9]*$ ]] || return 1
    uid=$(id -u telemt)
    gid=$(id -g telemt)
    [[ $(awk '/^Uid:/ {print $2 ":" $3 ":" $4 ":" $5}' "/proc/$pid/status") == "$uid:$uid:$uid:$uid" ]] || return 1
    [[ $(awk '/^Gid:/ {print $2 ":" $3 ":" $4 ":" $5}' "/proc/$pid/status") == "$gid:$gid:$gid:$gid" ]] || return 1
    caps=$(awk '/^CapEff:/ {print $2}' "/proc/$pid/status")
    [[ $caps == 0000000000001000 ]]
}

managed_permissions() {
    local file mode
    for file in "$BIN" "$CONFIG" "$UNIT" "$STATE" "$STATE/manifest.json" "$DATA" "$CONFIG_DIR"; do
        [[ -e $file && ! -L $file && $(stat -c %u "$file") == 0 ]] || return 1
        mode=$(stat -c %a "$file")
        (( (8#$mode & 0022) == 0 )) || return 1
    done
    mode=$(stat -c %a "$CONFIG")
    (( (8#$mode & 0007) == 0 )) || return 1
    [[ -d $DATA/state && ! -L $DATA/state && $(stat -c %u "$DATA/state") == "$(id -u telemt)" && $(stat -c %a "$DATA/state") == 750 ]] || return 1
    [[ $(stat -c %a "$STATE") == 700 ]]
}

atomic_copy() {
    local source=$1 destination=$2 stage
    helper safe-path "$destination" || return 1
    stage=$(mktemp "${destination}.twm.XXXXXX") || return 1
    if cp --preserve=mode,ownership,timestamps -- "$source" "$stage" && mv -fT -- "$stage" "$destination"; then
        return 0
    fi
    rm -f -- "$stage"
    return 1
}

backup_begin() {
    helper safe-path "$BACKUP_ROOT" || die 'Unsafe backup path'
    install -d -m 0700 "$BACKUP_ROOT"
    BACKUP=$(mktemp -d "$BACKUP_ROOT/$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")
    say "Backup: $BACKUP"
}

backup_nginx_context() {
    local path
    install -d -m 0700 "$BACKUP/nginx-snapshot"
    while IFS= read -r path; do
        cp --parents --preserve=mode,ownership,timestamps -- "$path" "$BACKUP/nginx-snapshot"
    done < <(jq -r '.snapshot | keys[]' "$TMP/nginx-plan.json")
    cp "$TMP/nginx-plan.json" "$BACKUP/nginx-plan.json"
}

track_file() {
    local destination=$1 index=${#CHANGED[@]}
    helper safe-path "$destination" || die "Unsafe destination path"
    if [[ -e $destination ]]; then
        [[ -f $destination ]] || die "Destination is not a regular file"
        cp -a -- "$destination" "$BACKUP/$index"
        ORIGINAL+=("$BACKUP/$index")
    else
        ORIGINAL+=("")
    fi
    CHANGED+=("$destination")
    printf '%s\t%s\n' "$index" "$destination" >>"$BACKUP/files.tsv"
}

rollback() {
    local index failed=0
    say 'Rolling back managed changes.' >&2
    if (( INSTALLING && ! CERT_ONLY )); then systemctl disable --now telemt.service >/dev/null 2>&1 || true; fi
    for ((index=${#CHANGED[@]}-1; index>=0; index--)); do
        if [[ -n ${ORIGINAL[index]} ]]; then
            atomic_copy "${ORIGINAL[index]}" "${CHANGED[index]}" || failed=1
        else
            rm -f -- "${CHANGED[index]}" || failed=1
        fi
    done
    if (( CERT_ONLY )); then
        :
    elif (( INSTALLING )); then
        systemctl daemon-reload || failed=1
    else
        restart_service && wait_ready 90 || failed=1
    fi
    if (( NGINX_CHANGED )); then nginx_test && nginx_reload || failed=1; fi
    if (( failed )); then say "CRITICAL: rollback incomplete; restore using $BACKUP/files.tsv" >&2; fi
    return "$failed"
}

cleanup() {
    local code=$?
    trap - EXIT INT TERM HUP
    if (( ARMED )); then rollback || code=1; fi
    if [[ -n $TMP && -d $TMP ]]; then rm -rf -- "$TMP"; fi
    exit "$code"
}

take_lock() {
    local identity mode=${1:-exclusive}
    identity=$(helper lock-path "$LOCK") || die 'Unsafe lock path'
    exec 9<>"$LOCK"
    [[ $(stat -Lc '%d:%i' /proc/self/fd/9) == "$identity" && ! -L $LOCK ]] || die 'Lock path changed'
    if [[ $mode == shared ]]; then
        flock -sn 9 || die 'Manager mutation in progress'
    else
        flock -n 9 || die 'Another manager invocation holds the lock'
    fi
}

preflight() {
    (( EUID == 0 )) || die 'Run as root; this manager never invokes sudo'
    [[ ${BASH_VERSINFO[0]} -ge 5 ]] || die 'Bash 5+ required'
    [[ -d /run/systemd/system ]] || die 'systemd is required'
    # shellcheck source=/dev/null
    source /etc/os-release
    [[ $ID == ubuntu && ( $VERSION_ID == 24.04 || $VERSION_ID == 26.04 ) ]] || die 'Supported OS: Ubuntu 24.04 / 26.04'
    case $(uname -m) in x86_64|aarch64|arm64) ;; *) die 'Unsupported architecture';; esac
    local dep
    for dep in curl tar openssl jq dig python3 nginx certbot flock systemctl ss sha256sum timeout iptables ip6tables nft; do need "$dep"; done
    python3 -c 'import tomllib' || die 'Python 3.11+ required'
}

fetch_release() {
    curl --proto '=https' --tlsv1.2 -fsS --connect-timeout 10 --max-time 60 --retry 2 \
        https://api.github.com/repos/telemt/telemt/releases/latest -o "$TMP/release.json" || return 1
    RELEASE=$(jq -er 'select(.draft == false and .prerelease == false) | .tag_name' "$TMP/release.json") || return 1
    [[ $RELEASE =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
}

download_candidate() {
    local arch asset url digest actual
    arch=$(uname -m); [[ $arch != arm64 ]] || arch=aarch64
    asset="telemt-$arch-linux-gnu.tar.gz"
    jq -e --arg name "$asset" '[.assets[] | select(.name == $name)] | length == 1' "$TMP/release.json" >/dev/null || die 'Ambiguous/missing release asset'
    url=$(jq -er --arg name "$asset" '.assets[] | select(.name == $name) | .browser_download_url' "$TMP/release.json")
    digest=$(jq -er --arg name "$asset" '.assets[] | select(.name == $name) | .digest' "$TMP/release.json")
    [[ $url == "https://github.com/telemt/telemt/releases/download/$RELEASE/$asset" && $digest =~ ^sha256:[a-f0-9]{64}$ ]] || die 'Official SHA256 digest/asset URL unavailable'
    curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fLsS --connect-timeout 10 --max-time 180 --max-filesize 134217728 --retry 2 "$url" -o "$TMP/asset.tar.gz"
    actual=$(sha256sum "$TMP/asset.tar.gz"); actual=${actual%% *}
    [[ sha256:$actual == "$digest" ]] || die 'SHA256 mismatch; candidate will not execute'
    timeout 60 python3 "$HELPER" extract-binary "$TMP/asset.tar.gz" "$TMP/telemt" || die 'Unknown/unsafe/oversized archive layout'
    chmod 0755 "$TMP/telemt"
    CANDIDATE="$TMP/telemt"
    [[ $(binary_version "$CANDIDATE") == "$RELEASE" ]] || die 'Candidate version mismatch'
}


binary_version() {
    local version
    version=$(timeout 10 "$1" --version 2>/dev/null) || return 1
    [[ $version =~ ^[Tt]elemt[[:space:]]([0-9]+\.[0-9]+\.[0-9]+)$ ]] || return 1
    printf '%s\n' "${BASH_REMATCH[1]}"
}

candidate_healthcheck() {
    # Its diagnostics can quote TOML secrets. Keep neither stdout nor stderr.
    (cd "$DATA" && timeout 60 "$1" healthcheck "$2") >/dev/null 2>&1
}

dns_preflight() {
    helper domain "$DOMAIN"
    helper ipv4 "$PUBLIC_IP"
    dig +time=3 +tries=1 +short A "$DOMAIN" >"$TMP/dns-a"
    dig +time=3 +tries=1 +short AAAA "$DOMAIN" >"$TMP/dns-aaaa"
    helper dns "$TMP/dns-a" "$TMP/dns-aaaa" "$PUBLIC_IP" || die 'DNS A/AAAA validation failed before installation'
}

socks_probe() {
    [[ -z $SOCKS || $SOCKS == direct ]] && return 0
    helper socks-address "$SOCKS" || return 1
    # SOCKS handshake plus verified Telegram TLS tests actual Telegram egress.
    curl --noproxy '' --proxy "socks5h://$SOCKS" --proto '=https' -fsS \
        --connect-timeout 10 --max-time 30 https://api.telegram.org/ -o /dev/null
}

generate_config() {
    local secret=$1
    cat <<EOF
# Managed initial configuration; updates preserve these bytes.
[general]
config_strict = true
data_path = "$DATA"
use_middle_proxy = false
log_level = "normal"
beobachten_file = "$DATA/state/beobachten.txt"
quota_state_path = "$DATA/state/telemt.limit.json"
unknown_dc_file_log_enabled = false
unknown_dc_log_path = "$DATA/state/unknown-dc.txt"
proxy_secret_path = "$DATA/state/proxy-secret"
proxy_config_v4_cache_path = "$DATA/state/proxy-config-v4.txt"
proxy_config_v6_cache_path = "$DATA/state/proxy-config-v6.txt"
[general.modes]
classic = false
secure = true
tls = false
[censorship]
mask = false
tls_emulation = false
tls_front_dir = "$DATA/state/tls-front"
[logging]
destination = "stderr"
[network]
ipv4 = true
ipv6 = false
prefer = 4
cache_public_ip_path = "$DATA/state/public_ip.txt"
[server]
port = 18080
proxy_protocol = false
[server.api]
enabled = false
[server.conntrack_control]
inline_conntrack_control = true
mode = "tracked"
[[server.listeners]]
ip = "127.0.0.1"
port = 18080
transport = "web"
proxy_protocol = false
web_client_ip_source = "x_forwarded_for"
web_trusted_proxy_cidrs = ["127.0.0.1/32"]
[access.users]
web-user = "$secret"
[web]
enabled = true
carrier = "https"
[[web.vhosts]]
host = "$DOMAIN"
public_addr = "$PUBLIC_IP:443"
[web.vhosts.decoy]
mode = "static_directory"
directory = "$DATA/public"
index = "index.html"
[[web.vhosts.profiles]]
user = "web-user"
secret_mode = "dd"
max_sessions = 8
max_streams = 512
max_streams_per_session = 64
[[upstreams]]
EOF
    if [[ -n $SOCKS && $SOCKS != direct ]]; then
        printf 'type = "socks5"\naddress = "%s"\n' "$SOCKS"
    else
        say 'type = "direct"'
    fi
}

generate_unit() {
    cat <<'EOF'
# Managed by telemt-web-manager v1
[Unit]
Description=Telemt WEB proxy
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=120
StartLimitBurst=3
[Service]
Type=simple
User=telemt
Group=telemt
WorkingDirectory=/var/lib/telemt
ExecStart=/usr/local/bin/telemt /etc/telemt/telemt.toml
Restart=on-failure
RestartSec=5
TimeoutStopSec=180
UMask=0027
CapabilityBoundingSet=CAP_NET_ADMIN
AmbientCapabilities=CAP_NET_ADMIN
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictRealtime=true
RestrictNamespaces=true
LockPersonality=true
MemoryDenyWriteExecute=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK
ReadWritePaths=/var/lib/telemt/state
LimitNOFILE=65536
TasksMax=4096
MemoryMax=1G
[Install]
WantedBy=multi-user.target
EOF
}

listener_ready() {
    local pid listeners
    pid=$(systemctl show telemt.service -p MainPID --value)
    [[ $pid =~ ^[1-9][0-9]*$ ]] || return 1
    listeners=$(ss -H -ltnp 'sport = :18080') || return 1
    [[ $(printf '%s\n' "$listeners" | wc -l) == 1 && $listeners == *"127.0.0.1:18080 "* && $listeners == *"pid=$pid,"* ]] || return 1
    [[ $(ss -H -ltnp | grep -c "pid=$pid,") == 1 && $(systemctl show telemt.service -p MainPID --value) == "$pid" ]]
}

wait_ready() {
    local limit=${1:-90} start status
    start=$(now)
    while (( $(now) - start < limit )); do
        status=$(systemctl show telemt.service -p ActiveState --value) || return 1
        case $status in failed|inactive|deactivating) return 1;; esac
        if service_active && listener_ready; then return 0; fi
        pause
    done
    return 1
}

http_ok() {
    local code
    code=$(curl --noproxy '*' --silent --show-error --connect-timeout 5 --max-time 20 \
        --output /dev/null --write-out '%{http_code}' "$@") || return 1
    [[ $code == 200 ]]
}

path_health() {
    nginx_test && service_active && listener_ready && process_identity || return 1
    http_ok -H "Host: $DOMAIN" http://127.0.0.1:18080/ || return 1
    # Traverse stream on :443 too: internal :7444 requires a PROXY preamble.
    http_ok --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/" || return 1
    http_ok "https://$DOMAIN/" || return 1
    socks_probe
}

recent_logs() {
    local since=$1 version os backend
    version=$(binary_version "$BIN") || return 1
    # shellcheck source=/dev/null
    source /etc/os-release
    os="$ID:$VERSION_ID"
    backend=$(iptables --version 2>/dev/null || true)
    journalctl -u telemt.service --since "@$since" --no-pager -o cat |
        helper classify "$version" "$os" "$backend"
}

nginx_plan() {
    build_nginx_plan "$TMP/nginx-plan.json" || die 'automatic nginx integration not possible'
}

build_nginx_plan() {
    if [[ $PLAN_MODE == acme ]]; then
        helper acme-plan "$NGINX_ROOT" "$DOMAIN" "$1" "$ACME_ROOT"
    else
        helper nginx-plan "$NGINX_ROOT" "$DOMAIN" "$1" "$ACME_ROOT"
    fi
}

apply_nginx() {
    local path index=0 expected actual
    build_nginx_plan "$TMP/nginx-plan-current.json"
    cmp -s "$TMP/nginx-plan.json" "$TMP/nginx-plan-current.json" || die 'Nginx include set changed during preflight'
    while IFS=$'\t' read -r path expected; do
        actual=$(sha256sum "$path"); actual=${actual%% *}
        [[ $actual == "$expected" ]] || die 'Nginx changed during preflight; retry after manual review'
    done < <(jq -r '.snapshot | to_entries[] | [.key,.value] | @tsv' "$TMP/nginx-plan.json")
    while IFS= read -r path; do
        track_file "$path"
        jq -rj --argjson i "$index" '.edits[$i].content' "$TMP/nginx-plan.json" >"$TMP/nginx-stage"
        chmod 0644 "$TMP/nginx-stage"
        if [[ -e $path ]]; then
            chmod --reference="$path" "$TMP/nginx-stage"
            chown --reference="$path" "$TMP/nginx-stage"
        fi
        NGINX_CHANGED=1
        atomic_copy "$TMP/nginx-stage" "$path"
        index=$((index+1))
    done < <(jq -r '.edits[].path' "$TMP/nginx-plan.json")
    nginx_test || die 'Nginx validation failed; restoring backup'
    nginx_reload || die 'Nginx reload failed; restoring backup'
}

ensure_certificate() {
    local cert="$CERT_ROOT/live/$DOMAIN/fullchain.pem" key="$CERT_ROOT/live/$DOMAIN/privkey.pem" sockets
    if [[ ! -e $cert || ! -e $key ]]; then
        [[ ! -e $CERT_ROOT/live/$DOMAIN && ! -L $CERT_ROOT/live/$DOMAIN ]] || die 'Incomplete existing certificate; manual repair required'
        if [[ -t 0 && -z ${EMAIL:-} ]]; then read -r -p 'ACME registration email: ' EMAIL; fi
        if [[ -t 0 && ${AGREE_TOS:-0} != 1 ]]; then
            local consent
            read -r -p "Accept the current Let's Encrypt subscriber agreement? [y/N] " consent
            if [[ $consent == y || $consent == Y ]]; then AGREE_TOS=1; fi
        fi
        [[ -n ${EMAIL:-} ]] || die 'New certificate needs --email and --agree-tos'
        [[ ${AGREE_TOS:-0} == 1 ]] || die 'Use --agree-tos to accept ACME subscriber terms'
        sockets=$(ss -H -ltn 'sport = :80') || die 'Port 80 inspection failed'
        if [[ -z $sockets ]]; then
            say 'Requesting standalone HTTP-01 certificate on free port 80. Nginx stays running.'
            certbot certonly --standalone --non-interactive --agree-tos --email "$EMAIL" -d "$DOMAIN" \
                --cert-name "$DOMAIN" >"$TMP/certbot.log" 2>&1 || die 'Certbot failed; see Certbot own logs'
        else
            nginx_runtime_identity && nginx_port_owned 80 || die 'Port 80 owner is not the recognized Nginx service'
            issue_webroot_certificate
            # Issuance committed a persistent renewal vhost. Replan WEB changes.
            nginx_plan
        fi
    fi
    validate_certificate
    if ! systemctl is-enabled --quiet certbot.timer && ! systemctl is-enabled --quiet snap.certbot.renew.timer; then
        say 'WARNING: renewal timer not detected; verify existing cron/renewal scheduling manually.'
    fi
}

validate_certificate() {
    local cert="$CERT_ROOT/live/$DOMAIN/fullchain.pem" key="$CERT_ROOT/live/$DOMAIN/privkey.pem"
    helper certificate-paths "$CERT_ROOT" "$DOMAIN" || die 'Unsafe certificate ownership/paths'
    openssl x509 -in "$cert" -noout -checkend 604800 >/dev/null || die 'Certificate expires within 7 days'
    openssl x509 -in "$cert" -noout -checkhost "$DOMAIN" | grep -q 'does match certificate' || die 'Certificate hostname mismatch'
    [[ -r $key ]] || die 'Certificate key unreadable'
    [[ $(openssl x509 -in "$cert" -pubkey -noout | openssl pkey -pubin -outform DER | sha256sum) == \
       "$(openssl pkey -in "$key" -pubout -outform DER 2>/dev/null | sha256sum)" ]] || die 'Certificate/private key mismatch'
}

nginx_port_owned() {
    local port=$1 sockets master pid parent executable
    master=$(systemctl show nginx.service -p MainPID --value)
    [[ $master =~ ^[1-9][0-9]*$ ]] || return 1
    executable=$(readlink -e "/proc/$master/exe") || return 1
    sockets=$(ss -H -ltnp "sport = :$port") || return 1
    [[ -n $sockets && -z $(printf '%s\n' "$sockets" | grep -v '"nginx"' || true) ]] || return 1
    while read -r pid; do
        [[ $pid == "$master" ]] && continue
        parent=$(awk '/^PPid:/ {print $2}' "/proc/$pid/status") || return 1
        [[ $parent == "$master" && $(readlink -e "/proc/$pid/exe") == "$executable" ]] || return 1
    done < <(printf '%s\n' "$sockets" | grep -oE 'pid=[0-9]+' | cut -d= -f2)
    [[ $sockets == *pid=* ]]
}

acme_probe() {
    local token file content code=0
    token=$(openssl rand -hex 16)
    file="$ACME_ROOT/.well-known/acme-challenge/twm-$token"
    helper safe-path "$file" || return 1
    printf '%s' "$token" >"$file"; chmod 0644 "$file"
    content=$(curl --noproxy '*' --proto '=http' -fsS --connect-timeout 5 --max-time 15 \
        --resolve "$DOMAIN:80:127.0.0.1" "http://$DOMAIN/.well-known/acme-challenge/twm-$token") || code=1
    [[ $content == "$token" ]] || code=1
    rm -f -- "$file"
    return "$code"
}

issue_webroot_certificate() (
    # Separate transaction: successful issuance keeps the renewal vhost even if
    # a later Telemt installation fails. Failure restores only ACME mutations.
    CERT_ONLY=1 INSTALLING=1 PLAN_MODE=acme
    CHANGED=() ORIGINAL=()
    TMP=$(mktemp -d "$TMP/acme.XXXXXXXX")
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM HUP
    nginx_plan
    helper safe-path "$ACME_ROOT" || die 'Unsafe ACME webroot'
    if [[ -e $ACME_ROOT ]]; then
        [[ -f $ACME_ROOT/.telemt-web-manager && $(cat "$ACME_ROOT/.telemt-web-manager") == "$DOMAIN" ]] || die 'Unmanaged ACME webroot'
        helper safe-path "$ACME_ROOT/.telemt-web-manager" || die 'Unsafe ACME marker'
    fi
    backup_begin
    backup_nginx_context
    ARMED=1
    helper safe-path "$ACME_ROOT/.well-known/acme-challenge" || die 'Unsafe ACME challenge path'
    install -d -m 0755 "$ACME_ROOT" "$ACME_ROOT/.well-known" "$ACME_ROOT/.well-known/acme-challenge"
    if [[ ! -e $ACME_ROOT/.telemt-web-manager ]]; then
        track_file "$ACME_ROOT/.telemt-web-manager"
        printf '%s\n' "$DOMAIN" >"$ACME_ROOT/.telemt-web-manager"
        chmod 0644 "$ACME_ROOT/.telemt-web-manager"
    fi
    apply_nginx
    acme_probe || die 'ACME webroot is not served correctly by local Nginx'
    say 'Requesting webroot HTTP-01 certificate. Nginx stays running.'
    certbot certonly --webroot --webroot-path "$ACME_ROOT" --non-interactive --agree-tos \
        --email "$EMAIL" -d "$DOMAIN" --cert-name "$DOMAIN" >"$TMP/certbot.log" 2>&1 || die 'Certbot failed; ACME changes will roll back'
    validate_certificate
    helper renewal-contract "$CERT_ROOT" "$DOMAIN" "$ACME_ROOT" || die 'Certbot renewal webroot was not recorded as expected'
    ARMED=0
)

prompt_install() {
    [[ -t 0 ]] || die 'Non-interactive install requires --domain and --public-ip (see --help)'
    read -r -p 'WEB domain: ' DOMAIN
    read -r -p 'Public IPv4 (must match DNS A): ' PUBLIC_IP
    local choice host port
    read -r -p 'Use SOCKS5 upstream? [y/N] ' choice
    if [[ $choice == y || $choice == Y ]]; then
        read -r -p 'SOCKS host [127.0.0.1]: ' host
        read -r -p 'SOCKS port: ' port
        SOCKS="${host:-127.0.0.1}:$port"
    fi
}

install_manager() {
    if [[ -f $STATE/manifest.json ]]; then
        local requested_domain=$DOMAIN
        load_installation
        [[ -z $requested_domain || $requested_domain == "$DOMAIN" ]] || die 'Different domain requested; manual review required'
        say 'Already installed; checking without rewriting configuration.'
        path_health
        return
    fi
    [[ -n $DOMAIN && -n $PUBLIC_IP ]] || prompt_install
    local path secret since
    for path in "$BIN" "$CONFIG" "$UNIT" "$DATA" "$CONFIG_DIR" "$STATE" "$RENEW_HOOK"; do
        helper safe-path "$path" || die 'Unsafe install path'
        [[ ! -e $path && ! -L $path ]] || die 'Existing Telemt files found; automatic adoption not possible; manual review required'
    done
    [[ -z $(systemctl show telemt.service -p FragmentPath --value) ]] || die 'Existing Telemt unit found'
    [[ -z $(ss -H -ltn 'sport = :18080 or sport = :7444') ]] || die 'Private ports already occupied'
    dns_preflight
    socks_probe || die 'Telegram HTTPS through SOCKS failed'
    nginx_test || die 'Existing Nginx configuration invalid'
    systemctl is-active --quiet nginx || die 'Nginx must be active'
    nginx_runtime_identity || die 'Nginx process/config/443 ownership is ambiguous'
    nginx_plan
    fetch_release || die 'Latest stable release unavailable'
    # Fresh config has been researched against this version; never assume future schemas.
    [[ $RELEASE == 3.5.9 ]] || die 'New upstream release requires manager schema review before fresh install'
    download_candidate
    ensure_certificate
    backup_begin
    backup_nginx_context
    INSTALLING=1; ARMED=1
    if getent passwd telemt >/dev/null || getent group telemt >/dev/null; then
        die 'Existing telemt account/group needs manual review'
    fi
    useradd --system --user-group --home-dir "$DATA" --no-create-home --shell /usr/sbin/nologin telemt
    install -d -m 0750 -o root -g telemt "$CONFIG_DIR" "$DATA" "$DATA/public"
    install -d -m 0750 -o telemt -g telemt "$DATA/state"
    install -d -m 0700 "$STATE"
    track_file "$DATA/public/index.html"
    say '<!doctype html><html lang="en"><meta charset="utf-8"><title>Welcome</title><h1>Welcome</h1></html>' >"$DATA/public/index.html"
    chown root:telemt "$DATA/public/index.html"
    chmod 0440 "$DATA/public/index.html"
    secret=$(openssl rand -hex 16)
    track_file "$CONFIG"
    generate_config "$secret" >"$CONFIG"
    track_file "$STATE/web-link.txt"
    printf 'tg://webproxy?server=%s&secret=dd%s\n' "$DOMAIN" "$secret" >"$STATE/web-link.txt"
    chmod 0600 "$STATE/web-link.txt"
    unset secret
    chown root:telemt "$CONFIG"; chmod 0640 "$CONFIG"
    candidate_healthcheck "$CANDIDATE" "$CONFIG" || die 'Candidate rejected generated config'
    helper config-info "$CONFIG" >"$TMP/config-info"
    track_file "$BIN"; atomic_copy "$CANDIDATE" "$BIN"
    track_file "$UNIT"; generate_unit >"$UNIT"; chmod 0644 "$UNIT"
    systemctl daemon-reload
    since=$(now)
    systemctl enable --now telemt.service
    wait_ready 90 || die 'Telemt did not become ready'
    apply_nginx
    if ! path_health || ! recent_logs "$since"; then die 'Post-install health failed'; fi
    install -d -m 0755 "$(dirname "$RENEW_HOOK")"
    track_file "$RENEW_HOOK"
    printf '#!/bin/sh\nset -eu\n/usr/sbin/nginx -t\n/usr/bin/systemctl reload nginx\n' >"$RENEW_HOOK"
    chmod 0750 "$RENEW_HOOK"
    track_file "$STATE/manifest.json"
    jq -n --arg domain "$DOMAIN" --arg unit "$(sha256sum "$UNIT" | cut -d' ' -f1)" \
        --arg nginx "$(sha256sum "$NGINX_ROOT/conf.d/telemt-web-manager.conf" | cut -d' ' -f1)" \
        --arg acme "$([[ -f $NGINX_ROOT/conf.d/telemt-web-manager-acme.conf ]] && printf '%s' "$ACME_ROOT" || true)" \
        '{schema:1,domain:$domain,unit_sha256:$unit,nginx_sha256:$nginx,acme_webroot:$acme}' >"$STATE/manifest.json"
    ARMED=0
    say "Private WEB link: $STATE/web-link.txt (0600)"
    say 'Installed. WEB link is generated by Telemt in its journal; treat it as a secret.'
    say 'Run: journalctl -u telemt.service (privately; do not paste unredacted logs).'
}

load_installation() {
    [[ -f $STATE/manifest.json && ! -L $STATE/manifest.json ]] || die 'Unmanaged installation; automatic update/migration not possible; manual review required'
    managed_permissions || die 'Unsafe managed ownership/permissions or symlink; manual review required'
    jq -e '.schema == 1' "$STATE/manifest.json" >/dev/null || die 'Unknown manifest schema'
    [[ $(systemctl show telemt.service -p FragmentPath --value) == "$UNIT" ]] || die 'Unexpected service unit'
    [[ -z $(systemctl show telemt.service -p DropInPaths --value) ]] || die 'Service drop-ins need manual review'
    nginx_runtime_identity || die 'Nginx process/config/443 ownership is ambiguous'
    local actual expected
    actual=$(sha256sum "$UNIT"); expected=$(jq -er .unit_sha256 "$STATE/manifest.json")
    [[ ${actual%% *} == "$expected" ]] || die 'Service changed; manual review required'
    actual=$(sha256sum "$NGINX_ROOT/conf.d/telemt-web-manager.conf"); expected=$(jq -er .nginx_sha256 "$STATE/manifest.json")
    [[ ${actual%% *} == "$expected" ]] || die 'Nginx vhost changed; manual review required'
    helper config-info "$CONFIG" >"$TMP/config-info" || die 'automatic update/migration not possible; manual review required'
    helper runtime-contract "$CONFIG" "$DATA" || die 'Runtime/write paths require manual review; existing TOML was not changed'
    mapfile -t INFO <"$TMP/config-info"
    DOMAIN=${INFO[0]}; SOCKS=${INFO[1]}
    [[ $DOMAIN == "$(jq -er .domain "$STATE/manifest.json")" ]] || die 'Domain changed; manual review required'
    nginx_plan
    [[ $(jq '.edits | length' "$TMP/nginx-plan.json") == 0 ]] || die 'Nginx integration incomplete; manual review required'
    if [[ -n $(jq -r '.acme_webroot // ""' "$STATE/manifest.json") ]]; then
        [[ $(jq -r .acme_webroot "$STATE/manifest.json") == "$ACME_ROOT" && -f $NGINX_ROOT/conf.d/telemt-web-manager-acme.conf ]] || die 'ACME renewal vhost missing or changed'
        helper safe-path "$ACME_ROOT/.telemt-web-manager"
        [[ $(cat "$ACME_ROOT/.telemt-web-manager") == "$DOMAIN" ]] || die 'ACME webroot ownership marker changed'
        helper renewal-contract "$CERT_ROOT" "$DOMAIN" "$ACME_ROOT" || die 'ACME renewal configuration needs manual review'
    fi
}

update_transaction() {
    local current=$1 since config_hash
    if [[ $current == "$RELEASE" ]]; then say 'already up to date'; return 0; fi
    config_hash=$(sha256sum "$CONFIG")
    candidate_healthcheck "$CANDIDATE" "$CONFIG" || die 'automatic update/migration not possible; manual review required'
    [[ $(sha256sum "$CONFIG") == "$config_hash" ]] || die 'Configuration changed during candidate validation'
    backup_begin
    cp -a "$CONFIG" "$BACKUP/config.toml"
    cp -a "$UNIT" "$BACKUP/telemt.service"
    backup_nginx_context
    track_file "$BIN"
    [[ $(sha256sum "$CONFIG") == "$config_hash" ]] || die 'Configuration changed before activation'
    ARMED=1
    atomic_copy "$CANDIDATE" "$BIN"
    since=$(now)
    if ! restart_service || ! wait_ready 90 || ! path_health || ! recent_logs "$since"; then
        die 'Update health failed; restoring previous binary'
    fi
    [[ $(sha256sum "$CONFIG") == "$config_hash" ]] || die 'Configuration changed concurrently; manual review required'
    ARMED=0
    say "Updated to $RELEASE. Configuration preserved byte-for-byte."
}

update_manager() {
    load_installation
    local current
    current=$(binary_version "$BIN") || die 'Unknown installed binary version'
    fetch_release || die 'Latest stable release unavailable'
    if [[ $current == "$RELEASE" ]]; then say 'already up to date'; path_health; return; fi
    [[ $RELEASE == 3.5.9 ]] || die 'Unaudited upstream runtime/write-path contract; manual review required'
    [[ $(printf '%s\n%s\n' "$current" "$RELEASE" | sort -V | head -n1) == "$current" ]] || die 'Installed version is newer; automatic downgrade refused'
    path_health || die 'Existing installation unhealthy; update refused'
    download_candidate
    update_transaction "$current"
}

check_manager() {
    load_installation
    local failed=0 pid cert
    say "Manager: $SCRIPT_VERSION; installed Telemt: $(binary_version "$BIN")"
    if fetch_release; then say "Latest stable: $RELEASE"; else say 'Latest release unavailable'; failed=1; fi
    systemctl show telemt.service -p ActiveState -p SubState -p NRestarts -p User -p Group -p MainPID -p AmbientCapabilities -p CapabilityBoundingSet
    pid=$(systemctl show telemt.service -p MainPID --value)
    if [[ $pid =~ ^[1-9][0-9]*$ && -r /proc/$pid/status ]]; then
        sed -n -e '/^Uid:/p' -e '/^Gid:/p' -e '/^CapEff:/p' "/proc/$pid/status"
    else failed=1; fi
    listener_ready && say 'Listener: 127.0.0.1:18080, owned by Telemt' || failed=1
    path_health && say 'Nginx/local decoy/local SNI+TLS/public HTTPS/SOCKS: OK' || failed=1
    cert="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
    openssl x509 -in "$cert" -noout -enddate || failed=1
    openssl x509 -in "$cert" -noout -checkend 604800 >/dev/null || failed=1
    recent_logs "$(( $(now) - 300 ))" || failed=1
    say "Check result: $([[ $failed == 0 ]] && printf OK || printf FAILED)"
    return "$failed"
}

repair_manager() {
    load_installation
    candidate_healthcheck "$BIN" "$CONFIG" || die 'Config validation failed; no repair attempted'
    nginx_test || die 'Nginx validation failed; no repair attempted'
    backup_begin
    cp -a "$CONFIG" "$BACKUP/config.toml"
    cp -a "$UNIT" "$BACKUP/telemt.service"
    backup_nginx_context
    say 'Managed files verified. Restarting Telemt and reloading validated Nginx.'
    if ! restart_service || ! wait_ready 90 || ! nginx_reload || ! path_health; then
        die 'Service recovery failed; manual review required'
    fi
}

usage() {
    cat <<EOF
Telemt WEB Manager $SCRIPT_VERSION
Usage: $0 --install|--update|--check|--repair|--help
Install options: --domain proxy.example.com --public-ip 203.0.113.10
                 [--socks 127.0.0.1:1080] [--email ADDRESS --agree-tos]
Without arguments: interactive menu (requires TTY).
Existing SNI router with proxy_protocol on and a conf.d HTTP include required.
Check is read-only. Repair only restarts/reloads verified managed services.
EOF
}

main() {
    local action='' choice
    while (( $# )); do
        case $1 in
            --help) usage; return;;
            --install|--update|--check|--repair) [[ -z $action ]] || die 'Choose one action'; action=$1; shift;;
            --domain|--public-ip|--socks|--email)
                (( $# >= 2 )) || die 'Missing option value'
                case $1 in --domain) DOMAIN=$2;; --public-ip) PUBLIC_IP=$2;; --socks) SOCKS=$2;; --email) EMAIL=$2;; esac
                shift 2;;
            --agree-tos) AGREE_TOS=1; shift;;
            *) die 'Unknown option; see --help';;
        esac
    done
    if [[ -z $action ]]; then
        [[ -t 0 ]] || die 'No interactive terminal; specify an action'
        printf '1. Install\n2. Update\n3. Check\n4. Repair\n5. Exit\n'
        read -r -p '> ' choice
        case $choice in 1) action=--install;; 2) action=--update;; 3) action=--check;; 4) action=--repair;; 5) return;; *) die 'Invalid selection';; esac
    fi
    preflight
    TMP=$(mktemp -d /tmp/telemt-web-manager.XXXXXXXX)
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM HUP
    if [[ $action == --check ]]; then
        take_lock shared
    else take_lock; fi
    case $action in --install) install_manager;; --update) update_manager;; --check) check_manager;; --repair) repair_manager;; esac
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then main "$@"; fi
