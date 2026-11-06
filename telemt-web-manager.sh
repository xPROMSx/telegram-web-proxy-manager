#!/usr/bin/env bash
# Telegram Web Proxy Manager. GPL-3.0. Requires Bash 5 and Python 3.11+.
set +x
set -Eeuo pipefail
umask 077
export LC_ALL=C
readonly SCRIPT_VERSION=1.2.0
# Parsed statically by the bootstrap; never execute a downloaded manager to inspect it.
readonly UPDATE_JOURNAL_SCHEMAS=1
readonly UPDATE_RECEIPT_SCHEMAS=1
readonly UPDATE_GATE_SCHEMAS=1
export UPDATE_JOURNAL_SCHEMAS UPDATE_RECEIPT_SCHEMAS UPDATE_GATE_SCHEMAS
readonly SUPPORTED_TELEMT_VERSION=3.5.16
readonly SUPPORTED_TELEMT_COMMIT=84e5b827a6619fb2e09ad3d09f253cdffe04bc2f
readonly TELEMT_SHA256_X86_64=e6f46b2f3becf29bfd555cec8a059e429f7c082c1af402499b3a7940cf8ebd34
readonly TELEMT_SHA256_AARCH64=1e1bc87f05923b9673cbbaf34a3e50f7fdcf7d496cd24efcdb34c278ed18a659
BASE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
HELPER="$BASE_DIR/lib/safety.py"
BIN=/usr/local/bin/telemt
CONFIG=/etc/telemt/telemt.toml
UNIT=/etc/systemd/system/telemt.service
# Legacy internal paths/markers remain compatibility ABI; no state migration.
STATE=/var/lib/telemt-web-manager
DATA=/var/lib/telemt
ACME_ROOT=/var/lib/telemt-web-manager-acme
CERT_ROOT=/etc/letsencrypt
CONFIG_DIR=/etc/telemt
RENEW_HOOK=/etc/letsencrypt/renewal-hooks/deploy/telemt-web-manager
NGINX_ROOT=/etc/nginx
BACKUP_ROOT=/root/telemt-backups
LOCK=/run/lock/telemt-web-manager.lock
TMP='' BACKUP='' DOMAIN='' PUBLIC_IP='' SOCKS='' CANDIDATE=''
ARMED=0 INSTALLING=0 NGINX_CHANGED=0 UNINSTALLING=0
CONFIRM_UNINSTALL=0 DELETE_CERTIFICATE=0 CERT_CLEANUP_RUNNING=0 UNINSTALL_ENABLED='' UNINSTALL_ACTIVE=''
CERT_ONLY=0 NGINX_ONLY=0 PLAN_MODE=web
FRESH_JOURNAL='' FRESH_SERVICE_ATTEMPTED=0 FRESH_GATE_CREATED=0
INTERACTIVE_INSTALL=0 MENU_ACTION=0
SITE_ROOT=/var/www/telemt-web-manager SITE_DIGEST='' FRESH_SITE=0
# Invocation-only presentation. Never inherit or persist a language preference.
UI_LANG=en UI_INTERACTIVE=0
# Reviewed Ubuntu tools only; no user input is used as an apt package name.
readonly -A TOOL_PACKAGES=(
    [curl]=curl [tar]=tar [openssl]=openssl [jq]=jq [dig]=dnsutils
    [python3]=python3 [certbot]=certbot [flock]=util-linux [ss]=iproute2
    [iptables]=iptables [ip6tables]=iptables [iptables-save]=iptables [ip6tables-save]=iptables
    [nft]=nftables [conntrack]=conntrack [getent]=libc-bin
    [useradd]=passwd [userdel]=passwd [groupadd]=passwd [groupdel]=passwd [find]=findutils
    [awk]=mawk [grep]=grep [sed]=sed [cmp]=diffutils
    [cat]=coreutils [chmod]=coreutils [chown]=coreutils [cp]=coreutils [cut]=coreutils
    [date]=coreutils [dirname]=coreutils [id]=coreutils [install]=coreutils [mktemp]=coreutils
    [mv]=coreutils [readlink]=coreutils [rm]=coreutils [rmdir]=coreutils [sha256sum]=coreutils
    [sleep]=coreutils [stat]=coreutils [timeout]=coreutils [tr]=coreutils [uname]=coreutils [wc]=coreutils
    [unshare]=util-linux [setpriv]=util-linux [chroot]=coreutils [ip]=iproute2 [mount]=util-linux [ldd]=libc-bin
)
declare -a CHANGED=() ORIGINAL=()

say() { printf '%s\n' "$*"; }
die() { say "ERROR: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null || ui_die "Missing dependency: $1 (see README)" "Отсутствует зависимость: $1 (см. README)"; }
helper() { TWM_UI_LANGUAGE=en python3 "$HELPER" "$@"; }

# Explicit UI call sites only; say/die and machine/helper protocols stay intact.
ui_text() {
    if [[ $UI_LANG == ru ]]; then printf '%s' "$2"; else printf '%s' "$1"; fi
}
ui_message() {
    local color=$1 text=$2
    if (( UI_INTERACTIVE )) && [[ -t 1 && -n ${TERM:-} && $TERM != dumb && $TERM != unknown && ! -v NO_COLOR ]]; then
        printf '\033[1;%sm%s\033[0m\n' "$color" "$text"
    else say "$text"; fi
}
msg_ok() { ui_message 32 "$1"; }
msg_warn() { ui_message 33 "$1"; }
msg_err() { ui_message 31 "$1"; }
msg_inf() { ui_message 36 "$1"; }
ui_info() { if (( UI_INTERACTIVE )); then msg_inf "$(ui_text "$1" "$2")"; else say "$1"; fi; }
ui_ok() { if (( UI_INTERACTIVE )); then msg_ok "$(ui_text "$1" "$2")"; else say "$1"; fi; }
ui_warn() { if (( UI_INTERACTIVE )); then msg_warn "$(ui_text "$1" "$2")"; else say "$1"; fi; }
ui_err() { if (( UI_INTERACTIVE )); then msg_err "$(ui_text "$1" "$2")"; else say "$1"; fi; }
ui_die() {
    if (( UI_INTERACTIVE )); then msg_err "$(ui_text "ERROR: $1" "ОШИБКА: $2")" >&2; exit 1; fi
    die "$1"
}
ui_header() {
    printf '%s\n' '============================================================'
    msg_inf "            TELEGRAM WEB PROXY MANAGER v${SCRIPT_VERSION}"
    printf '%s\n' '============================================================'
    msg_inf "  $1"
    printf '%s\n' '------------------------------------------------------------'
}
ui_select_language() {
    local answer
    while true; do
        ui_header 'SELECT LANGUAGE / ВЫБЕРИТЕ ЯЗЫК'
        printf '  1. English\n  2. Русский\n  0. Exit / Выход\n'
        printf '%s\n' '------------------------------------------------------------'
        read -r -p '  Select / Выбор: ' answer || return 1
        case $answer in
            1) UI_LANG=en; return 0;;
            2) UI_LANG=ru; return 0;;
            0) return 1;;
            *) msg_warn 'Invalid selection / Неверный выбор.';;
        esac
    done
}
ui_main_menu() {
    ui_header "$(ui_text 'MAIN MENU' 'ГЛАВНОЕ МЕНЮ')"
    ui_text $'  1. Install Telegram proxy\n  2. Update Telemt\n  3. Check status\n  4. Check and restart services\n  5. Show connection link\n  6. Uninstall Telegram proxy\n  0. Exit\n' \
        $'  1. Установить Telegram-прокси\n  2. Обновить Telemt\n  3. Проверить состояние\n  4. Проверить и перезапустить службы\n  5. Показать ссылку подключения\n  6. Удалить Telegram-прокси\n  0. Выход\n'
    printf '%s\n' '------------------------------------------------------------'
}
ui_helper() {
    # Only human-facing commands receive the ephemeral language. Structured
    # helper stdout, recovery units and every explicit CLI invocation stay English.
    if (( UI_INTERACTIVE )) && [[ -t 0 && -t 1 ]]; then
        TWM_UI_LANGUAGE=$UI_LANG python3 "$HELPER" "$@"
    else helper "$@"; fi
}
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
    helper safe-path "$BACKUP_ROOT" || ui_die 'Unsafe backup path' 'Небезопасный путь резервной копии; требуется ручная проверка'
    install -d -m 0700 "$BACKUP_ROOT"
    BACKUP=$(mktemp -d "$BACKUP_ROOT/$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")
    ui_info "Backup: $BACKUP" "Резервная копия: $BACKUP"
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
    helper safe-path "$destination" || ui_die "Unsafe destination path" 'Небезопасный путь назначения; изменение остановлено'
    if [[ -e $destination ]]; then
        [[ -f $destination ]] || ui_die "Destination is not a regular file" 'Объект назначения не является обычным файлом; изменение остановлено'
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
    local -a fresh_roots=("$CONFIG_DIR" "$DATA" "$STATE")
    if (( FRESH_SITE )); then fresh_roots+=("$SITE_ROOT"); fi
    # In an EXIT trap, bare return can reuse the pre-trap signal status.
    if (( UNINSTALLING )); then uninstall_rollback; return "$?"; fi
    ui_warn 'Rolling back managed changes.' 'Восстанавливаем состояние до изменений.' >&2
    if (( INSTALLING && ! CERT_ONLY )); then
        if (( FRESH_SERVICE_ATTEMPTED )); then
            if ! systemctl disable --now telemt.service; then
                ui_err "CRITICAL: Telemt stop failed; fresh state retained. Review $FRESH_JOURNAL" "КРИТИЧЕСКАЯ ОШИБКА: Telemt не остановлен; состояние установки сохранено. Требуется ручная проверка: $FRESH_JOURNAL" >&2
                return 1
            fi
        fi
        if [[ -n $FRESH_JOURNAL ]] && ! helper fresh-verify "$FRESH_JOURNAL" "${fresh_roots[@]}"; then
            ui_err "CRITICAL: fresh ownership/process/mount validation failed; state retained. Review $FRESH_JOURNAL" "КРИТИЧЕСКАЯ ОШИБКА: не подтверждена принадлежность объектов установки, процессов или точек монтирования. Состояние сохранено; проверьте вручную: $FRESH_JOURNAL" >&2
            return 1
        fi
    fi
    for ((index=${#CHANGED[@]}-1; index>=0; index--)); do
        if [[ -n ${ORIGINAL[index]} ]]; then
            atomic_copy "${ORIGINAL[index]}" "${CHANGED[index]}" || failed=1
        else
            rm -f -- "${CHANGED[index]}" || failed=1
        fi
    done
    if (( INSTALLING && FRESH_GATE_CREATED )) && [[ -d ${UNIT}.d ]]; then
        helper safe-path "${UNIT}.d" && rmdir -- "${UNIT}.d" || failed=1
    fi
    if (( CERT_ONLY || NGINX_ONLY )); then
        :
    elif (( INSTALLING )); then
        systemctl daemon-reload || failed=1
    else
        restart_service && wait_ready 90 || failed=1
    fi
    if (( NGINX_CHANGED )); then nginx_test && nginx_reload || failed=1; fi
    if (( NGINX_ONLY && ! failed )); then path_health || failed=1; fi
    if (( INSTALLING && ! CERT_ONLY )) && [[ -n $FRESH_JOURNAL ]]; then
        if (( ! failed )) && helper fresh-cleanup-dirs "$FRESH_JOURNAL" "${fresh_roots[@]}"; then
            helper fresh-cleanup-account "$FRESH_JOURNAL" "${fresh_roots[@]}" || failed=1
        else failed=1; fi
    fi
    if (( failed )); then ui_err "CRITICAL: rollback incomplete; review $BACKUP/files.tsv and ${FRESH_JOURNAL:-the backup} for manual recovery" "КРИТИЧЕСКАЯ ОШИБКА: восстановление не завершено. Для ручного восстановления проверьте $BACKUP/files.tsv и ${FRESH_JOURNAL:-$BACKUP}" >&2; fi
    return "$failed"
}

cleanup() {
    local code=$?
    trap - EXIT INT TERM HUP
    if (( ARMED )); then rollback || code=1; fi
    if (( CERT_CLEANUP_RUNNING )); then
        ui_warn "Telemt uninstall succeeded. Certificate cleanup interrupted or requires manual review. Backup: $BACKUP" "Telemt удалён. Очистка сертификата прервана или требует ручной проверки. Резервная копия: $BACKUP" >&2
    fi
    if (( UI_INTERACTIVE && code != 0 )); then
        ui_err 'Operation did not complete. Review the messages above; manual intervention may be required.' \
            'Операция не завершена. Проверьте сообщения выше; может потребоваться ручное вмешательство администратора.' >&2
    fi
    if [[ -n $TMP && -d $TMP ]]; then rm -rf -- "$TMP"; fi
    exit "$code"
}

take_lock() {
    local identity mode=${1:-exclusive}
    identity=$(helper lock-path "$LOCK") || ui_die 'Unsafe lock path' 'Небезопасный путь блокировки; операция остановлена'
    exec 9<>"$LOCK"
    [[ $(stat -Lc '%d:%i' /proc/self/fd/9) == "$identity" && ! -L $LOCK ]] || ui_die 'Lock path changed' 'Путь блокировки изменился; операция остановлена'
    if [[ $mode == shared ]]; then
        flock -sn 9 || ui_die 'Manager mutation in progress' 'Другой процесс менеджера изменяет установку; повторите после его завершения'
    else
        flock -n 9 || ui_die 'Another manager invocation holds the lock' 'Менеджер уже запущен; дождитесь завершения другого процесса'
    fi
}

platform_preflight() {
    local init dep
    (( EUID == 0 )) || ui_die 'Run as root; this manager never invokes sudo' 'Запустите менеджер от root; он не вызывает sudo автоматически'
    [[ ${BASH_VERSINFO[0]} -ge 5 ]] || ui_die 'Bash 5+ required' 'Требуется Bash версии 5 или новее'
    [[ -d /run/systemd/system ]] || ui_die 'Active systemd environment required' 'Требуется работающая среда systemd'
    IFS= read -r init </proc/1/comm
    [[ $init == systemd ]] || ui_die 'systemd must already be the active init system' 'systemd должен быть действующей системой инициализации'
    # shellcheck source=/dev/null
    source /etc/os-release
    [[ $ID == ubuntu && ( $VERSION_ID == 24.04 || $VERSION_ID == 26.04 ) ]] || ui_die 'Supported OS: Ubuntu 24.04 / 26.04' 'Поддерживаемые ОС: Ubuntu 24.04 / 26.04'
    case $(uname -m) in x86_64|aarch64|arm64) ;; *) ui_die 'Unsupported architecture' 'Архитектура процессора не поддерживается';; esac
    for dep in systemctl systemd-path journalctl; do
        command -v "$dep" >/dev/null || ui_die "Existing systemd tooling required: $dep (not installed automatically)" "Требуется установленная команда systemd: $dep (автоматически не устанавливается)"
    done
}

preflight() {
    platform_preflight
    check_dependencies "${1:---install}"
}

dependency_commands() {
    case $1 in
        show-web-link) printf '%s\n' python3 flock stat;;
        --install|--update|--check|--repair|--uninstall)
            # Preserve the existing shared prerequisites, including archive tooling.
            printf '%s\n' curl tar openssl jq dig python3 certbot flock ss sha256sum timeout \
                iptables ip6tables nft conntrack getent useradd userdel groupdel \
                awk grep sed cmp cat chmod chown cp cut date dirname id install mktemp mv readlink rm rmdir sleep stat tr uname wc
            if [[ $1 != --uninstall ]]; then
                printf '%s\n' unshare setpriv chroot ip mount ldd iptables-save ip6tables-save
            fi
            if [[ $1 == --uninstall ]]; then printf '%s\n' groupadd find iptables-save ip6tables-save; fi;;
        *) ui_die 'Unknown dependency action' 'Неизвестная операция проверки зависимостей';;
    esac
}

manual_dependency_command() {
    ui_info 'Install manually:' 'Установите вручную:' >&2
    printf 'apt-get update && apt-get install -y --no-install-recommends' >&2
    printf ' %s' "$@" >&2
    printf '\n' >&2
}

check_dependencies() {
    local action=${1:---install} dep package answer service_path commands installed=0
    local -a required=() missing=() packages=()
    local -A selected=()
    if [[ $action != show-web-link ]]; then
        command -v nginx >/dev/null || ui_die 'Existing Nginx installation and supported topology required; Nginx is not installed automatically' 'Требуется установленный Nginx с поддерживаемой схемой маршрутизации; менеджер не устанавливает Nginx автоматически'
    fi
    if [[ $action != show-web-link && $action != --uninstall ]]; then
        command -v systemd-run >/dev/null || ui_die 'Existing systemd-run tooling required for isolated candidate validation' 'Для изолированной проверки кандидата требуется установленная команда systemd-run'
    fi
    commands=$(dependency_commands "$action") || ui_die 'Cannot determine required dependencies' 'Не удалось определить необходимые зависимости; операция остановлена'
    mapfile -t required <<<"$commands"
    for dep in "${required[@]}"; do
        if ! command -v "$dep" >/dev/null; then
            missing+=("$dep")
            package=${TOOL_PACKAGES[$dep]}
            if [[ -z ${selected[$package]:-} ]]; then
                packages+=("$package"); selected[$package]=1
            fi
        fi
    done
    if (( ${#missing[@]} )); then
        # Show-link normally needs no platform/service check. Before any apt offer,
        # however, it must prove the same immutable Ubuntu/systemd contract.
        if [[ $action == show-web-link ]]; then platform_preflight; fi
        ui_info 'Missing required dependencies:' 'Отсутствуют необходимые зависимости:' >&2
        for dep in "${missing[@]}"; do ui_info "  $dep -> package: ${TOOL_PACKAGES[$dep]}" "  $dep -> пакет: ${TOOL_PACKAGES[$dep]}" >&2; done
        ui_info "Packages to install: ${packages[*]}" "Пакеты для установки: ${packages[*]}" >&2
        if (( ! MENU_ACTION )) || [[ ! -t 0 || ! -t 1 ]]; then
            manual_dependency_command "${packages[@]}"
            ui_die 'Required dependencies missing; no packages installed' 'Необходимые зависимости отсутствуют; пакеты не устанавливались'
        fi
        read -r -p "$(ui_text 'Install missing packages now? [y/N] ' 'Установить недостающие пакеты сейчас? [y/N] ')" answer || answer=''
        if [[ $answer != y && $answer != Y ]]; then
            ui_info 'Dependency installation declined.' 'Установка зависимостей отменена.' >&2
            manual_dependency_command "${packages[@]}"
            ui_die 'Run Telegram Web Proxy Manager again after installing the dependencies' 'Установите зависимости и запустите Telegram Web Proxy Manager снова'
        fi
        command -v apt-get >/dev/null || {
            manual_dependency_command "${packages[@]}"
            ui_die 'apt-get unavailable; package installation requires manual review' 'apt-get недоступен; зависимости нужно проверить и установить вручную'
        }
        ui_info 'Updating Ubuntu package metadata...' 'Обновляем сведения о пакетах Ubuntu...'
        DEBIAN_FRONTEND=noninteractive apt-get update || ui_die 'apt-get update failed; selected action was not started' 'Ошибка apt-get update; выбранная операция не запускалась'
        ui_info "Installing packages: ${packages[*]}" "Устанавливаем пакеты: ${packages[*]}"
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${packages[@]}" || ui_die 'apt-get install failed; selected action was not started' 'Ошибка apt-get install; выбранная операция не запускалась'
        hash -r
        for dep in "${required[@]}"; do
            command -v "$dep" >/dev/null || ui_die "Required command still missing after package installation: $dep; selected action was not started" "После установки пакетов команда $dep по-прежнему недоступна; выбранная операция не запускалась"
        done
        installed=1
    fi
    python3 -c 'import tomllib' || ui_die 'Python 3.11+ required' 'Требуется Python версии 3.11 или новее'
    if [[ $action != show-web-link ]]; then
        service_path=$(systemd-path search-binaries-default) || ui_die 'Cannot determine systemd runtime PATH' 'Не удалось определить PATH служб systemd'
        PATH="$service_path" command -v conntrack >/dev/null || ui_die "conntrack is installed but is not available on systemd's default executable PATH; check: systemd-path search-binaries-default" 'conntrack установлен, но недоступен в стандартном PATH служб systemd. Проверьте: systemd-path search-binaries-default'
    fi
    if (( installed )); then ui_ok 'Dependencies installed successfully. Continuing...' 'Зависимости установлены. Продолжаем...'; fi
}

download_candidate() {
    local arch asset url digest actual
    arch=$(uname -m)
    case $arch in
        x86_64) digest=$TELEMT_SHA256_X86_64;;
        aarch64|arm64) arch=aarch64; digest=$TELEMT_SHA256_AARCH64;;
        *) ui_die 'Unsupported architecture' 'Архитектура процессора не поддерживается';;
    esac
    asset="telemt-$arch-linux-gnu.tar.gz"
    url="https://github.com/telemt/telemt/releases/download/$SUPPORTED_TELEMT_VERSION/$asset"
    curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fLsS --connect-timeout 10 --max-time 180 --max-filesize 134217728 --retry 2 "$url" -o "$TMP/asset.tar.gz"
    actual=$(sha256sum "$TMP/asset.tar.gz"); actual=${actual%% *}
    [[ $actual == "$digest" ]] || ui_die 'Pinned SHA256 mismatch; candidate will not execute' 'SHA256 не совпадает с закреплённым значением; кандидат не будет запущен'
    ui_ok "Verified Telemt $SUPPORTED_TELEMT_VERSION $asset SHA256: $actual; release commit: $SUPPORTED_TELEMT_COMMIT" "Проверен Telemt $SUPPORTED_TELEMT_VERSION, $asset, SHA256: $actual; commit релиза: $SUPPORTED_TELEMT_COMMIT"
    timeout 60 python3 "$HELPER" extract-binary "$TMP/asset.tar.gz" "$TMP/telemt" || ui_die 'Unknown/unsafe/oversized archive layout' 'Структура архива неизвестна, небезопасна или превышает допустимый размер; установка остановлена'
    chmod 0755 "$TMP/telemt"
    CANDIDATE="$TMP/telemt"
    [[ $(binary_version "$CANDIDATE") == "$SUPPORTED_TELEMT_VERSION" ]] || ui_die 'Candidate differs from supported Telemt version' 'Версия кандидата отличается от закреплённой версии Telemt'
}


binary_version() {
    local version
    version=$(timeout 10 "$1" --version 2>/dev/null) || return 1
    [[ $version =~ ^[Tt]elemt[[:blank:]]([0-9A-Za-z.+-]+)$ ]] || return 1
    version=${BASH_REMATCH[1]}
    helper semver "$version" || return 1
    printf '%s\n' "$version"
}

candidate_healthcheck() {
    # 3.5.16 permits absent decoy assets during healthcheck. Preserve the
    # manager's pre-issuance readiness contract independently of that CLI.
    local working=${3:-$DATA} mode site=$SITE_ROOT
    mode=$(helper decoy-mode "$2" 2>/dev/null) || return 1
    if [[ $mode == static_directory ]]; then
        [[ -d $working/public && -f $working/public/index.html ]] || return 1
        helper safe-path "$working/public/index.html" >/dev/null 2>&1 || return 1
    else
        if [[ $working == "$TMP/compat-data" ]]; then site="$TMP/site"; fi
        [[ -n $SITE_DIGEST && $(helper site-identity "$site" 2>/dev/null) == "$SITE_DIGEST" ]] || return 1
    fi
    # Its diagnostics can quote TOML secrets. Keep neither stdout nor stderr.
    (cd "$working" && timeout 60 "$1" healthcheck "$2") >/dev/null 2>&1
}

candidate_compatibility() {
    local binary=$1 config=$2 data_root=${3:-$DATA} before copy probe
    binary_version "$binary" >/dev/null || return 1
    helper config-info "$config" >/dev/null || return 1
    helper runtime-contract "$config" "$data_root" || return 1
    before=$(sha256sum "$config"); before=${before%% *}
    copy=$(mktemp "$TMP/compat-config.XXXXXXXX") || return 1
    probe=$(mktemp "$TMP/compat-probe.XXXXXXXX") || return 1
    cp -- "$config" "$copy" || return 1
    candidate_healthcheck "$binary" "$copy" "$data_root" || return 1
    [[ $(sha256sum "$copy" | cut -d' ' -f1) == "$before" ]] || return 1
    # Prove strict parsing of the supplied file, not merely a zero CLI exit.
    printf '__telemt_web_manager_unknown_contract = true\n' >"$probe"
    cat "$copy" >>"$probe"
    if candidate_healthcheck "$binary" "$probe" "$data_root"; then return 1; fi
    [[ $(sha256sum "$config" | cut -d' ' -f1) == "$before" ]] || return 1
    rm -f -- "$copy" "$probe"
}

dns_preflight() {
    helper domain "$DOMAIN"
    helper ipv4 "$PUBLIC_IP"
    dig +time=3 +tries=1 +short A "$DOMAIN" >"$TMP/dns-a"
    dig +time=3 +tries=1 +short AAAA "$DOMAIN" >"$TMP/dns-aaaa"
    helper dns "$TMP/dns-a" "$TMP/dns-aaaa" "$PUBLIC_IP" || ui_die 'DNS A/AAAA validation failed before installation' 'Проверка DNS A/AAAA не пройдена; установка не запускалась'
}

socks_probe() {
    [[ -z $SOCKS || $SOCKS == direct ]] && return 0
    helper socks-address "$SOCKS" || return 1
    # SOCKS handshake plus verified Telegram TLS tests actual Telegram egress.
    curl --noproxy '' --proxy "socks5h://$SOCKS" --proto '=https' -fsS \
        --connect-timeout 10 --max-time 30 https://api.telegram.org/ -o /dev/null
}

generate_config() {
    local secret=$1 data_root=${2:-$DATA}
    helper safe-path "$data_root" || return 1
    cat <<EOF || return 1
# Managed initial configuration; updates preserve these bytes.
[general]
config_strict = true
disable_colors = true
data_path = "$data_root"
use_middle_proxy = false
log_level = "normal"
beobachten_file = "$data_root/state/beobachten.txt"
quota_state_path = "$data_root/state/telemt.limit.json"
unknown_dc_file_log_enabled = false
unknown_dc_log_path = "$data_root/state/unknown-dc.txt"
proxy_secret_path = "$data_root/state/proxy-secret"
proxy_config_v4_cache_path = "$data_root/state/proxy-config-v4.txt"
proxy_config_v6_cache_path = "$data_root/state/proxy-config-v6.txt"
[general.modes]
classic = false
secure = true
tls = false
[censorship]
mask = false
tls_emulation = false
tls_front_dir = "$data_root/state/tls-front"
[logging]
destination = "stderr"
[network]
ipv4 = true
ipv6 = false
prefer = 4
cache_public_ip_path = "$data_root/state/public_ip.txt"
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
mode = "http_upstream"
upstream = "http://127.0.0.1:18081"
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

prepare_compatibility_data() {
    local root=$1
    # Only a new private child of this transaction's temporary directory.
    [[ $root == "$TMP/compat-data" && ! -e $root && ! -L $root ]] || return 1
    helper safe-path "$root" || return 1
    install -d -m 0700 "$root" "$root/state" "$root/public" || return 1
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

wait_https_ready() {
    # Reserve a second for Bash clock granularity within the 30-second budget.
    local deadline=$((SECONDS+29)) remaining limit
    while (( SECONDS < deadline )); do
        remaining=$((deadline-SECONDS)); limit=$((remaining < 5 ? remaining : 5))
        if http_ok --connect-timeout "$limit" --max-time "$limit" \
            --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/" 2>/dev/null; then
            remaining=$((deadline-SECONDS))
            (( remaining > 0 )) || break
            limit=$((remaining < 5 ? remaining : 5))
            if http_ok --connect-timeout "$limit" --max-time "$limit" "https://$DOMAIN/" 2>/dev/null; then
                (( SECONDS < deadline )) && return 0
                break
            fi
        fi
        (( SECONDS < deadline )) || break
        sleep 1
    done
    return 1
}

path_health() {
    local mode
    nginx_test && service_active && listener_ready && process_identity || return 1
    mode=$(helper decoy-mode "$CONFIG") || return 1
    if [[ $mode == http_upstream ]]; then
        nginx_port_owned 18081 && http_ok http://127.0.0.1:18081/ || return 1
    fi
    http_ok -H "Host: $DOMAIN" http://127.0.0.1:18080/ || return 1
    # Traverse stream on :443 too: internal :7444 requires a PROXY preamble.
    if [[ ${1:-} == fresh ]]; then
        wait_https_ready || ui_die $'Telegram HTTPS route did not become ready after Nginx reload.\nCheck SNI routing, TLS certificate and public HTTPS reachability.' $'HTTPS-маршрут Telegram не стал доступен после перезагрузки Nginx.\nПроверьте SNI-маршрутизацию, TLS-сертификат и доступность публичного HTTPS.'
    else
        http_ok --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/" || return 1
        http_ok "https://$DOMAIN/" || return 1
    fi
    socks_probe
}

recent_logs() {
    local since=$1
    journalctl -u telemt.service --since "@$since" --no-pager -o json |
        helper classify-journal
}

nginx_plan() {
    build_nginx_plan "$TMP/nginx-plan.json" || ui_die 'automatic nginx integration not possible' 'Автоматическое подключение к Nginx остановлено; требуется ручная проверка'
}

build_nginx_plan() {
    local status=0 red='' reset=''
    if [[ $PLAN_MODE == uninstall ]]; then
        helper nginx-uninstall-plan "$NGINX_ROOT" "$DOMAIN" "$1" "$ACME_ROOT" || status=$?
    elif [[ $PLAN_MODE == acme ]]; then
        helper acme-plan "$NGINX_ROOT" "$DOMAIN" "$1" "$ACME_ROOT" || status=$?
    elif [[ $PLAN_MODE == keepalive ]]; then
        helper nginx-keepalive-plan "$NGINX_ROOT" "$DOMAIN" "$1" "$ACME_ROOT" "$STATE/manifest.json" || status=$?
    elif [[ -n $SITE_DIGEST ]]; then
        helper nginx-site-plan "$NGINX_ROOT" "$DOMAIN" "$1" "$ACME_ROOT" "$SITE_DIGEST" || status=$?
    else
        helper nginx-plan "$NGINX_ROOT" "$DOMAIN" "$1" "$ACME_ROOT" || status=$?
    fi
    if (( status == 20 )); then
        # Only the helper's exact foreign server_name conflict uses this code.
        if (( UI_INTERACTIVE )); then
            ui_die $'This domain is already used in Nginx (possibly by 3x-ui / REALITY).\nUse a separate, unused domain or subdomain for Telegram WEB.\nNo Nginx configuration was changed.' \
                $'Этот домен уже используется в Nginx (возможно, 3x-ui / REALITY).\nДля Telegram WEB выберите отдельный свободный домен или поддомен.\nКонфигурация Nginx не изменена.'
        fi
        if [[ -t 2 && -n ${TERM:-} && $TERM != dumb && $TERM != unknown && ! -v NO_COLOR ]]; then
            red=$'\033[1;31m' reset=$'\033[0m'
        fi
        printf '%sERROR: This domain is already used in Nginx (possibly by 3x-ui / REALITY).\nUse a separate, unused domain or subdomain for Telegram WEB.\nNo Nginx configuration was changed.%s\n' "$red" "$reset" >&2
        exit 1
    fi
    return "$status"
}

apply_nginx() {
    local path index=0 expected actual
    build_nginx_plan "$TMP/nginx-plan-current.json"
    cmp -s "$TMP/nginx-plan.json" "$TMP/nginx-plan-current.json" || ui_die 'Nginx include set changed during preflight' 'Набор include-файлов Nginx изменился во время проверки; операция остановлена'
    while IFS=$'\t' read -r path expected; do
        actual=$(sha256sum "$path"); actual=${actual%% *}
        [[ $actual == "$expected" ]] || ui_die 'Nginx changed during preflight; retry after manual review' 'Конфигурация Nginx изменилась во время проверки; проверьте её вручную перед повторной попыткой'
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
        if [[ $(jq --argjson i "$index" '.edits[$i].content == null' "$TMP/nginx-plan.json") == true ]]; then
            helper planned-unlink "$TMP/nginx-plan.json" "$path"
        else atomic_copy "$TMP/nginx-stage" "$path"; fi
        index=$((index+1))
    done < <(jq -r '.edits[].path' "$TMP/nginx-plan.json")
    nginx_test || ui_die 'Nginx validation failed; restoring backup' 'Проверка Nginx не пройдена; восстанавливаем резервную копию'
    nginx_reload || ui_die 'Nginx reload failed; restoring backup' 'Перезагрузка Nginx не удалась; восстанавливаем резервную копию'
}

ensure_certificate() {
    local cert="$CERT_ROOT/live/$DOMAIN/fullchain.pem" key="$CERT_ROOT/live/$DOMAIN/privkey.pem" sockets issued=0
    if [[ ! -e $cert || ! -e $key ]]; then
        [[ ! -e $CERT_ROOT/live/$DOMAIN && ! -L $CERT_ROOT/live/$DOMAIN &&
           ! -e $CERT_ROOT/renewal/$DOMAIN.conf && ! -L $CERT_ROOT/renewal/$DOMAIN.conf &&
           ! -e $CERT_ROOT/archive/$DOMAIN && ! -L $CERT_ROOT/archive/$DOMAIN ]] ||
            ui_die 'Existing Certbot lineage assets; preserve them and review recovery manually' 'Найдены существующие файлы сертификата Certbot; сохраните их и проверьте восстановление вручную'
        if [[ -t 0 && -z ${EMAIL:-} ]]; then read -r -p "$(ui_text 'ACME registration email: ' 'Email для регистрации ACME: ')" EMAIL; fi
        if [[ -t 0 && ${AGREE_TOS:-0} != 1 ]]; then
            local consent
            read -r -p "$(ui_text "Accept the current Let's Encrypt subscriber agreement? [y/N] " "Принять действующие условия Let's Encrypt? [y/N] ")" consent
            if [[ $consent == y || $consent == Y ]]; then AGREE_TOS=1; fi
        fi
        [[ -n ${EMAIL:-} ]] || ui_die 'New certificate needs --email and --agree-tos' 'Для нового сертификата нужны --email и --agree-tos'
        [[ ${AGREE_TOS:-0} == 1 ]] || ui_die 'Use --agree-tos to accept ACME subscriber terms' 'Для согласия с условиями ACME укажите --agree-tos'
        sockets=$(ss -H -ltn 'sport = :80') || ui_die 'Port 80 inspection failed' 'Не удалось проверить порт 80'
        if [[ -z $sockets ]]; then
            [[ $(helper port80-config "$NGINX_ROOT") == 0 ]] || ui_die 'Nginx config declares port 80 but runtime does not; manual review required' 'В конфигурации Nginx указан порт 80, но слушатель отсутствует; требуется ручная проверка'
            ui_info 'Requesting standalone HTTP-01 certificate on free port 80. Nginx stays running.' 'Запрашиваем сертификат HTTP-01 в режиме standalone на свободном порту 80. Nginx продолжает работать.'
            certbot certonly --standalone --non-interactive --agree-tos --email "$EMAIL" -d "$DOMAIN" \
                --cert-name "$DOMAIN" >"$TMP/certbot.log" 2>&1 || ui_die 'Certbot failed; see Certbot own logs' 'Ошибка Certbot; проверьте его журнал'
        else
            if ! nginx_runtime_identity || ! nginx_port_owned 80; then
                ui_die 'Port 80 owner is not the recognized Nginx service' 'Порт 80 занят процессом, принадлежность которого проверенному Nginx не подтверждена'
            fi
            [[ $(helper port80-config "$NGINX_ROOT") == 1 ]] || ui_die 'Nginx runtime/config port 80 mismatch; manual review required' 'Слушатель порта 80 не соответствует конфигурации Nginx; требуется ручная проверка'
            issue_webroot_certificate
            # Issuance committed a persistent renewal vhost. Replan WEB changes.
            nginx_plan
        fi
        issued=1
    fi
    validate_certificate
    certificate_renewal_contract "$issued"
    write_certificate_state
    renewal_scheduler_status
}

generate_renewal_hook() {
    printf '#!/bin/sh\nset -eu\n/usr/sbin/nginx -t\n/usr/bin/systemctl reload nginx\n'
}

renewal_deploy_hook_contract() {
    [[ $RENEW_HOOK == "$CERT_ROOT/renewal-hooks/deploy/telemt-web-manager" ]] ||
        ui_die 'Unexpected managed Certbot deploy-hook path; manual review required' 'Неожиданный путь deploy-hook Certbot; требуется ручная проверка'
    helper safe-path "$RENEW_HOOK" || ui_die 'Unsafe managed Certbot deploy hook; manual review required' 'Небезопасный deploy-hook Certbot; требуется ручная проверка'
    [[ -f $RENEW_HOOK && ! -L $RENEW_HOOK && $(stat -c %u "$RENEW_HOOK") == 0 ]] ||
        ui_die 'Managed Certbot deploy hook missing or wrong owner; manual review required' 'Deploy-hook Certbot отсутствует или имеет другого владельца; требуется ручная проверка'
    local mode
    mode=$(stat -c %a "$RENEW_HOOK")
    (( (8#$mode & 0100) != 0 && (8#$mode & 07022) == 0 )) ||
        ui_die 'Unsafe managed Certbot deploy-hook permissions; manual review required' 'Небезопасные права deploy-hook Certbot; требуется ручная проверка'
    cmp -s "$RENEW_HOOK" <(generate_renewal_hook) ||
        ui_die 'Managed Certbot deploy hook changed; manual review required' 'Deploy-hook Certbot изменён; требуется ручная проверка'
}

renewal_scheduler_status() {
    if systemctl is-enabled --quiet certbot.timer; then
        ui_info 'Renewal scheduler detected: certbot.timer' 'Обнаружено автоматическое продление сертификатов: certbot.timer'
    elif systemctl is-enabled --quiet snap.certbot.renew.timer; then
        ui_info 'Renewal scheduler detected: snap.certbot.renew.timer' 'Обнаружено автоматическое продление сертификатов: snap.certbot.renew.timer'
    else
        ui_warn 'WARNING: no known Certbot timer detected; verify cron/custom renewal scheduling manually.' 'ВНИМАНИЕ: известный таймер Certbot не найден. Проверьте вручную продление через cron или собственный планировщик.'
    fi
}

certificate_health_contract() {
    validate_certificate
    certificate_renewal_contract
    renewal_deploy_hook_contract
}

certificate_renewal_contract() {
    local freshly_issued=${1:-0} kind expected='' sockets
    kind=$(helper renewal-kind "$CERT_ROOT" "$DOMAIN" "$ACME_ROOT") ||
        ui_die 'Certificate renewal settings are unsupported; preserve Certbot assets and review docs/OPERATIONS.md' 'Настройки продления сертификата не поддерживаются. Сохраните файлы Certbot и обратитесь к docs/OPERATIONS.md'
    if [[ -e $STATE/certificate.json || -L $STATE/certificate.json ]]; then
        helper certificate-record-check "$STATE" "$DOMAIN" "$CERT_ROOT" "$ACME_ROOT" "$NGINX_ROOT" || ui_die 'Certificate ownership record mismatch' 'Запись о принадлежности сертификата не совпадает; требуется ручная проверка'
        expected=$(jq -er .acme_webroot "$STATE/certificate.json")
    fi
    if [[ -f $STATE/manifest.json ]]; then
        [[ $(jq -er .domain "$STATE/manifest.json") == "$DOMAIN" ]] || ui_die 'Certificate domain differs from managed manifest' 'Домен сертификата отличается от manifest менеджера; операция остановлена'
        expected=$(jq -r '.acme_webroot // ""' "$STATE/manifest.json")
    fi
    if [[ $kind == webroot ]]; then
        [[ ! -f $STATE/manifest.json || $expected == "$ACME_ROOT" ]] || ui_die 'Manifest renewal webroot changed' 'Каталог webroot продления отличается от manifest; операция остановлена'
        helper acme-state "$NGINX_ROOT" "$DOMAIN" "$ACME_ROOT" ||
            ui_die 'Managed webroot renewal is incomplete; certificate retained. Restore the audited ACME vhost/webroot/marker or repair renewal manually; see docs/OPERATIONS.md' 'Настройка продления через webroot неполна; сертификат сохранён. Восстановите проверенные ACME vhost/webroot/маркер или исправьте продление вручную; см. docs/OPERATIONS.md'
        [[ $freshly_issued == 1 || -f $STATE/manifest.json || -f $STATE/certificate.json ]] ||
            ui_die 'Existing certificate has no manager ownership evidence; automatic adoption refused' 'Не подтверждена принадлежность существующего сертификата менеджеру; автоматическое использование остановлено'
        nginx_port_owned 80 || ui_die 'Managed webroot renewal needs the recognized Nginx listening on port 80' 'Для продления через webroot проверенный Nginx должен слушать порт 80'
    else
        [[ -z $expected ]] || ui_die 'Managed webroot certificate changed to standalone; manual review required' 'Продление сертификата переключено с webroot на standalone; требуется ручная проверка'
        [[ $freshly_issued == 1 || -f $STATE/manifest.json || -f $STATE/certificate.json ]] ||
            ui_die 'Existing certificate has no manager ownership evidence; automatic adoption refused. Preserve Certbot assets; see docs/OPERATIONS.md' 'Принадлежность сертификата менеджеру не подтверждена; автоматическое использование остановлено. Сохраните файлы Certbot; см. docs/OPERATIONS.md'
        # ss includes IPv4 and IPv6, including wildcard and loopback listeners.
        # Any listener is outside the audited free-port standalone contract.
        sockets=$(ss -H -ltn 'sport = :80') || ui_die 'Standalone renewal port 80 inspection failed' 'Не удалось проверить порт 80 для продления в режиме standalone'
        [[ -z $sockets ]] ||
            ui_die 'Standalone Certbot renewal requires free TCP port 80; port 80 is currently occupied. Review renewal strategy manually.' 'Для продления Certbot в режиме standalone нужен свободный TCP-порт 80. Сейчас он занят; проверьте схему продления вручную.'
    fi
}

validate_certificate() {
    local cert="$CERT_ROOT/live/$DOMAIN/fullchain.pem" key="$CERT_ROOT/live/$DOMAIN/privkey.pem"
    helper certificate-paths "$CERT_ROOT" "$DOMAIN" || ui_die 'Unsafe certificate ownership/paths' 'Небезопасные пути или неподтверждённая принадлежность сертификата; операция остановлена'
    if [[ ${1:-health} != identity ]]; then
        openssl x509 -in "$cert" -noout -checkend 604800 >/dev/null || ui_die 'Certificate expires within 7 days' 'Срок сертификата истекает менее чем через 7 дней; требуется продление'
    fi
    openssl x509 -in "$cert" -noout -checkhost "$DOMAIN" | grep -q 'does match certificate' || ui_die 'Certificate hostname mismatch' 'Сертификат не соответствует домену; операция остановлена'
    [[ -r $key ]] || ui_die 'Certificate key unreadable' 'Закрытый ключ сертификата недоступен для чтения'
    [[ $(openssl x509 -in "$cert" -pubkey -noout | openssl pkey -pubin -outform DER | sha256sum) == \
       "$(openssl pkey -in "$key" -pubout -outform DER 2>/dev/null | sha256sum)" ]] || ui_die 'Certificate/private key mismatch' 'Сертификат не соответствует закрытому ключу'
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

issue_webroot_certificate() {
    local parent_tmp=$TMP
    local TMP
    TMP=$(mktemp -d "$parent_tmp/acme.XXXXXXXX")
    (
    # Separate transaction: successful issuance keeps the renewal vhost even if
    # a later Telemt installation fails. Failure restores only ACME mutations.
    CERT_ONLY=1 INSTALLING=1 PLAN_MODE=acme
    # Separate certificate subshell deliberately isolates its tracked edits.
    # shellcheck disable=SC2030
    CHANGED=() ORIGINAL=()
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM HUP
    nginx_plan
    helper safe-path "$ACME_ROOT" || ui_die 'Unsafe ACME webroot' 'Небезопасный каталог ACME webroot; операция остановлена'
    if [[ -e $ACME_ROOT ]]; then
        [[ -f $ACME_ROOT/.telemt-web-manager && $(cat "$ACME_ROOT/.telemt-web-manager") == "$DOMAIN" ]] || ui_die 'Unmanaged ACME webroot' 'Принадлежность ACME webroot менеджеру не подтверждена; операция остановлена'
        helper safe-path "$ACME_ROOT/.telemt-web-manager" || ui_die 'Unsafe ACME marker' 'Небезопасный маркер ACME; операция остановлена'
    fi
    backup_begin
    backup_nginx_context
    ARMED=1
    helper safe-path "$ACME_ROOT/.well-known/acme-challenge" || ui_die 'Unsafe ACME challenge path' 'Небезопасный путь ACME challenge; операция остановлена'
    install -d -m 0755 "$ACME_ROOT" "$ACME_ROOT/.well-known" "$ACME_ROOT/.well-known/acme-challenge"
    if [[ ! -e $ACME_ROOT/.telemt-web-manager ]]; then
        track_file "$ACME_ROOT/.telemt-web-manager"
        printf '%s\n' "$DOMAIN" >"$ACME_ROOT/.telemt-web-manager"
        chmod 0644 "$ACME_ROOT/.telemt-web-manager"
    fi
    apply_nginx
    acme_probe || ui_die 'ACME webroot is not served correctly by local Nginx' 'Локальный Nginx некорректно обслуживает ACME webroot; запрос сертификата остановлен'
    ui_info 'Requesting webroot HTTP-01 certificate. Nginx stays running.' 'Запрашиваем сертификат HTTP-01 через webroot. Nginx продолжает работать.'
    certbot certonly --webroot --webroot-path "$ACME_ROOT" --non-interactive --agree-tos \
        --email "$EMAIL" -d "$DOMAIN" --cert-name "$DOMAIN" >"$TMP/certbot.log" 2>&1 || ui_die 'Certbot failed; ACME changes will roll back' 'Ошибка Certbot; изменения ACME будут отменены'
    validate_certificate
    helper renewal-contract "$CERT_ROOT" "$DOMAIN" "$ACME_ROOT" || ui_die 'Certbot renewal webroot was not recorded as expected' 'Certbot не сохранил ожидаемый каталог webroot для продления; операция остановлена'
    ARMED=0
    )
}

detect_public_ipv4() {
    local url address
    for url in https://api.ipify.org https://ipv4.icanhazip.com; do
        if address=$(curl -4 --noproxy '*' --connect-timeout 2 --max-time 4 --max-filesize 64 -fsS "$url" 2>/dev/null |
            python3 -c '
import ipaddress, sys
value = sys.stdin.buffer.read(65).decode("ascii").removesuffix("\n")
address = ipaddress.IPv4Address(value)
if not address.is_global or address.is_multicast:
    sys.exit(1)
print(address)
' 2>/dev/null); then
            printf '%s\n' "$address"
            return 0
        fi
    done
    return 1
}

prompt_install() {
    [[ -t 0 ]] || ui_die 'Non-interactive install requires --domain and --public-ip (see --help)' 'Для установки без диалога нужны --domain и --public-ip (см. --help)'
    read -r -p "$(ui_text 'WEB domain: ' 'Домен WEB-прокси: ')" DOMAIN
    local detected_ip
    if detected_ip=$(detect_public_ipv4); then
        ui_info "Detected public IPv4: $detected_ip" "Определён публичный IPv4: $detected_ip"
        read -r -p "$(ui_text "Public IPv4 [$detected_ip]: " "Публичный IPv4 [$detected_ip]: ")" PUBLIC_IP
        PUBLIC_IP=${PUBLIC_IP:-$detected_ip}
    else
        ui_warn 'Could not detect public IPv4 automatically.' 'Не удалось автоматически определить публичный IPv4.'
        read -r -p "$(ui_text 'Public IPv4 (must match DNS A): ' 'Публичный IPv4 (должен совпадать с DNS A): ')" PUBLIC_IP
    fi
    local choice host port
    read -r -p "$(ui_text 'Use SOCKS5 upstream? [y/N] ' 'Подключаться через SOCKS5? [y/N] ')" choice
    if [[ $choice == y || $choice == Y ]]; then
        read -r -p "$(ui_text 'SOCKS host [127.0.0.1]: ' 'Хост SOCKS [127.0.0.1]: ')" host
        read -r -p "$(ui_text 'SOCKS port: ' 'Порт SOCKS: ')" port
        SOCKS="${host:-127.0.0.1}:$port"
    fi
}

present_web_link() {
    [[ -t 0 && -t 1 && -t 2 ]] || { ui_err 'WEB link display requires interactive input and output.' 'Показ WEB-ссылки возможен только в терминале без перенаправления stdout/stderr.' >&2; return 1; }
    ui_helper web-link-display "$STATE" "$CONFIG" || {
        ui_warn 'No valid manager-owned WEB link is available.' 'Проверенная WEB-ссылка этой установки недоступна; требуется ручная проверка.' >&2; return 1;
    }
}

managed_dropins() {
    local paths
    paths=$(systemctl show telemt.service -p DropInPaths --value) || return 1
    if [[ -n $paths ]]; then
        [[ $paths == "${UNIT}.d/50-telemt-web-manager-update.conf" ]] || return 1
        helper update-gate-contract
    else
        [[ ! -e ${UNIT}.d/50-telemt-web-manager-update.conf && ! -L ${UNIT}.d/50-telemt-web-manager-update.conf ]]
    fi
}

initialize_update_state() { helper update-install-baseline; }
installed_release_identity() { helper update-local-receipt; }
installed_compatibility() { helper update-readonly-compatibility; }
universal_update() { ui_helper update-universal; }
recover_update() { ui_helper update-recover; }
pending_update() { helper update-pending; }

show_current_web_link() {
    (( EUID == 0 )) || ui_die 'Run as root; this manager never invokes sudo' 'Запустите менеджер от root; он не вызывает sudo автоматически'
    [[ -t 0 && -t 1 && -t 2 ]] || ui_die 'WEB link display requires interactive input and output.' 'Для показа WEB-ссылки нужны интерактивные ввод и вывод.'
    check_dependencies show-web-link
    take_lock shared
    helper update-pending || ui_die 'Pending or critical Update; WEB link is not displayed' 'Обновление не завершено или требует вмешательства; WEB-ссылка не показана'
    present_web_link
}

optimize_nginx_keepalive() {
    local answer expected actual
    PLAN_MODE=keepalive
    nginx_plan
    if [[ $(jq '.edits | length' "$TMP/nginx-plan.json") == 0 ]]; then PLAN_MODE=web; return; fi
    ui_info 'The verified Nginx vhost can reuse connections to Telemt. Only this vhost and its manifest hash will change; Telemt will keep running.' \
        'Проверенный vhost Nginx можно оптимизировать для повторного использования соединений с Telemt. Изменятся только этот vhost и его хеш в manifest; Telemt продолжит работать.'
    if ! read -r -p "$(ui_text 'Enable Nginx upstream keepalive? [y/N]: ' 'Включить Nginx upstream keepalive? [д/Н]: ')" answer; then answer=''; fi
    case $answer in
        y|Y|yes|Yes|YES|д|Д|да|Да|ДА) ;;
        *) ui_info 'Nginx optimization cancelled; no changes made.' 'Оптимизация Nginx отменена; изменений не внесено.'; PLAN_MODE=web; return;;
    esac
    expected=$(jq -rj '.edits[0].content' "$TMP/nginx-plan.json" | sha256sum | cut -d' ' -f1)
    jq --arg nginx "$expected" '.nginx_sha256 = $nginx' "$STATE/manifest.json" >"$TMP/manifest-keepalive.json"
    chmod 0600 "$TMP/manifest-keepalive.json"
    backup_begin
    backup_nginx_context
    track_file "$STATE/manifest.json"
    NGINX_ONLY=1 ARMED=1
    apply_nginx
    actual=$(sha256sum "$NGINX_ROOT/conf.d/telemt-web-manager.conf")
    [[ ${actual%% *} == "$expected" ]] || ui_die 'Nginx changed during optimization; restoring backup' \
        'Конфигурация Nginx изменилась во время оптимизации; восстанавливаем резервную копию'
    atomic_copy "$TMP/manifest-keepalive.json" "$STATE/manifest.json"
    path_health || ui_die 'WEB health check failed; restoring the previous Nginx vhost and manifest' \
        'Проверка WEB не пройдена; восстанавливаем прежний vhost Nginx и manifest'
    ARMED=0 NGINX_ONLY=0 PLAN_MODE=web
    ui_ok 'Nginx upstream keepalive enabled. Telemt was not restarted.' 'Nginx upstream keepalive включён. Telemt не перезапускался.'
}

install_manager() {
    if [[ -f $STATE/manifest.json ]]; then
        local requested_domain=$DOMAIN
        load_installation
        [[ -z $requested_domain || $requested_domain == "$DOMAIN" ]] || ui_die 'Different domain requested; manual review required' 'Запрошен другой домен; автоматическое изменение остановлено, требуется ручная проверка'
        ui_info 'Already installed; checking without rewriting configuration.' 'Установка уже существует; проверяем её без перезаписи конфигурации.'
        path_health
        if (( INTERACTIVE_INSTALL && UI_INTERACTIVE )) && [[ -t 0 && -t 1 ]]; then optimize_nginx_keepalive; fi
        return
    fi
    [[ -n $DOMAIN && -n $PUBLIC_IP ]] || prompt_install
    local path secret since
    for path in "$BIN" "$CONFIG" "$UNIT" "$DATA" "$CONFIG_DIR" "$SITE_ROOT"; do
        helper safe-path "$path" || ui_die 'Unsafe install path' 'Небезопасный путь установки; операция остановлена'
        [[ ! -e $path && ! -L $path ]] || ui_die 'Existing Telemt files found; automatic adoption not possible; manual review required' 'Найдены существующие файлы Telemt. Автоматическое подключение остановлено; требуется ручная проверка'
    done
    if [[ -e $STATE || -L $STATE ]]; then
        helper certificate-only-state "$STATE" || ui_die 'Existing manager state is not certificate-only; adoption refused' 'Существующее состояние менеджера содержит не только сертификат; автоматическое подключение остановлено'
        helper certificate-record-check "$STATE" "$DOMAIN" "$CERT_ROOT" "$ACME_ROOT" "$NGINX_ROOT" || ui_die 'Preserved certificate ownership mismatch' 'Не совпадает принадлежность сохранённого сертификата; требуется ручная проверка'
    fi
    if [[ -e $RENEW_HOOK || -L $RENEW_HOOK ]]; then
        [[ -f $STATE/certificate.json ]] || ui_die 'Existing deploy hook has no certificate ownership evidence' 'Для существующего deploy-hook не подтверждена принадлежность сертификата; требуется ручная проверка'
        renewal_deploy_hook_contract
    fi
    if getent passwd telemt >/dev/null || getent group telemt >/dev/null; then
        ui_die 'Existing telemt account/group needs manual review' 'Существующая учётная запись или группа telemt требует ручной проверки'
    fi
    [[ -z $(systemctl show telemt.service -p FragmentPath --value) ]] || ui_die 'Existing Telemt unit found' 'Найден существующий unit Telemt; автоматическое подключение остановлено'
    [[ -d $(dirname "$SITE_ROOT") ]] || ui_die 'Site parent directory missing' 'Родительский каталог сайта отсутствует; требуется ручная проверка'
    [[ -z $(ss -H -ltn 'sport = :18080 or sport = :7444 or sport = :18081') ]] || ui_die 'Private ports already occupied' 'Внутренние порты уже заняты; установка остановлена'
    dns_preflight
    socks_probe || ui_die 'Telegram HTTPS through SOCKS failed' 'Проверка HTTPS Telegram через SOCKS не пройдена'
    nginx_test || ui_die 'Existing Nginx configuration invalid' 'Текущая конфигурация Nginx не прошла проверку'
    systemctl is-active --quiet nginx || ui_die 'Nginx must be active' 'Для установки Nginx должен работать'
    nginx_runtime_identity || ui_die 'Nginx process/config/443 ownership is ambiguous' 'Не удалось однозначно подтвердить процессы, конфигурацию и владельца порта 443 Nginx; требуется ручная проверка'
    SITE_DIGEST=$(helper site-generate "$TMP/site") || ui_die 'Approved site resources failed validation; no configuration changed' 'Ресурсы сайта не прошли проверку; конфигурация не изменена'
    nginx_plan
    download_candidate
    secret=$(openssl rand -hex 16)
    prepare_compatibility_data "$TMP/compat-data" || ui_die 'Unable to stage managed decoy; no certificate issuance attempted' 'Не удалось подготовить сайт-прикрытие для проверки; сертификат не запрашивался'
    generate_config "$secret" "$TMP/compat-data" >"$TMP/fresh.toml" || ui_die 'Unable to stage managed config; no certificate issuance attempted' 'Не удалось подготовить конфигурацию для проверки; сертификат не запрашивался'
    candidate_compatibility "$CANDIDATE" "$TMP/fresh.toml" "$TMP/compat-data" ||
        ui_die 'Candidate incompatible with strict managed WEB configuration; no certificate issuance attempted' 'Кандидат несовместим со строгой WEB-конфигурацией менеджера; сертификат не запрашивался'
    ensure_certificate
    backup_begin
    backup_nginx_context
    INSTALLING=1; ARMED=1
    if getent passwd telemt >/dev/null || getent group telemt >/dev/null; then
        ui_die 'Existing telemt account/group needs manual review' 'Существующая учётная запись или группа telemt требует ручной проверки'
    fi
    FRESH_JOURNAL="$BACKUP/fresh-ownership.json"
    FRESH_SITE=1
    helper fresh-init "$FRESH_JOURNAL" "$CONFIG_DIR" "$DATA" "$STATE" "$SITE_ROOT"
    helper fresh-account-create "$FRESH_JOURNAL" "$DATA"
    for path in "$CONFIG_DIR" "$DATA" "$DATA/public" "$DATA/state"; do
        helper fresh-mkdir "$FRESH_JOURNAL" "$path" 0750
        if [[ $path == "$DATA/state" ]]; then chown telemt:telemt "$path";
        else chown root:telemt "$path"; fi
    done
    if [[ ! -e $STATE ]]; then helper fresh-mkdir "$FRESH_JOURNAL" "$STATE" 0700; fi
    helper fresh-mkdir "$FRESH_JOURNAL" "$SITE_ROOT" 0755
    for path in "$TMP/site/"*; do
        track_file "$SITE_ROOT/${path##*/}"
        atomic_copy "$path" "$SITE_ROOT/${path##*/}"
    done
    [[ $(helper site-identity "$SITE_ROOT") == "$SITE_DIGEST" ]] || ui_die 'Published site integrity failed' 'Целостность опубликованного сайта не подтверждена; выполняется восстановление'
    track_file "$CONFIG"
    generate_config "$secret" "$DATA" >"$CONFIG" || ui_die 'Unable to create final managed config' 'Не удалось создать итоговую конфигурацию'
    track_file "$STATE/web-link.txt"
    printf 'tg://webproxy?server=%s&secret=dd%s\n' "$DOMAIN" "$secret" >"$STATE/web-link.txt"
    chmod 0600 "$STATE/web-link.txt"
    unset secret
    chown root:telemt "$CONFIG"; chmod 0640 "$CONFIG"
    candidate_compatibility "$CANDIDATE" "$CONFIG" || ui_die 'Candidate rejected generated config' 'Кандидат не принял созданную конфигурацию; установка остановлена'
    helper config-info "$CONFIG" >"$TMP/config-info"
    track_file "$BIN"; atomic_copy "$CANDIDATE" "$BIN"
    track_file "$UNIT"; generate_unit >"$UNIT"; chmod 0644 "$UNIT"
    for path in "$STATE/telemt-release.json" "$STATE/telemt-generation.json" "$STATE/update-journal.json" \
                "$DATA/.telemt-web-manager-generation.json" "${UNIT}.d/50-telemt-web-manager-update.conf" \
                "$(dirname "$UNIT")/telemt-web-manager-recovery.service"; do track_file "$path"; done
    if [[ ! -e ${UNIT}.d ]]; then FRESH_GATE_CREATED=1; fi
    initialize_update_state
    systemctl daemon-reload
    since=$(now)
    FRESH_SERVICE_ATTEMPTED=1
    systemctl enable --now telemt.service
    wait_ready 90 || ui_die 'Telemt did not become ready' 'Telemt не стал готов к работе за отведённое время'
    apply_nginx
    if ! path_health fresh || ! recent_logs "$since"; then ui_die 'Post-install health failed' 'Проверка работоспособности после установки не пройдена; выполняется восстановление'; fi
    install -d -m 0755 "$(dirname "$RENEW_HOOK")"
    if [[ ! -e $RENEW_HOOK ]]; then
        track_file "$RENEW_HOOK"
        generate_renewal_hook >"$RENEW_HOOK"
        chmod 0750 "$RENEW_HOOK"
    fi
    renewal_deploy_hook_contract
    track_file "$STATE/manifest.json"
    jq -n --arg domain "$DOMAIN" --arg public_ip "$PUBLIC_IP" --arg unit "$(sha256sum "$UNIT" | cut -d' ' -f1)" \
        --arg nginx "$(sha256sum "$NGINX_ROOT/conf.d/telemt-web-manager.conf" | cut -d' ' -f1)" \
        --arg acme "$(if [[ -f $NGINX_ROOT/conf.d/telemt-web-manager-acme.conf ]]; then printf '%s' "$ACME_ROOT"; fi)" \
        '{schema:1,domain:$domain,public_ip:$public_ip,unit_sha256:$unit,nginx_sha256:$nginx,acme_webroot:$acme}' >"$STATE/manifest.json"
    ARMED=0
    ui_info "Private WEB link: $STATE/web-link.txt (0600)" "Секретная WEB-ссылка сохранена: $STATE/web-link.txt (0600)"
    ui_ok 'Installed. The manager saved the private WEB link; treat it as a bearer secret.' 'Установка завершена. WEB-ссылка содержит секрет доступа; храните её в безопасном месте и не передавайте посторонним.'
    if (( INTERACTIVE_INSTALL )) && [[ -t 0 && -t 1 ]]; then
        present_web_link || ui_warn 'Install committed. Review the private WEB link state; no link was regenerated.' 'Установка завершена. Проверьте сохранённую WEB-ссылку вручную; ссылка не создавалась заново.' >&2
    fi
}

load_installation() {
    [[ -f $STATE/manifest.json && ! -L $STATE/manifest.json ]] || ui_die 'Unmanaged installation; automatic update/migration not possible; manual review required' 'Принадлежность установки менеджеру не подтверждена; автоматическое обновление остановлено, требуется ручная проверка'
    managed_permissions || ui_die 'Unsafe managed ownership/permissions or symlink; manual review required' 'Обнаружены небезопасные права, владелец или символическая ссылка; требуется ручная проверка'
    installed_release_identity >/dev/null || ui_die 'Invalid/missing installed release identity; manual review required' 'Идентификаторы установленного релиза отсутствуют или неверны; требуется ручная проверка'
    jq -e '.schema == 1' "$STATE/manifest.json" >/dev/null || ui_die 'Unknown manifest schema' 'Неизвестная схема manifest; операция остановлена'
    [[ $(systemctl show telemt.service -p FragmentPath --value) == "$UNIT" ]] || ui_die 'Unexpected service unit' 'Неожиданный unit службы; операция остановлена'
    managed_dropins || ui_die 'Service drop-ins need manual review' 'Дополнительные настройки службы требуют ручной проверки'
    nginx_runtime_identity || ui_die 'Nginx process/config/443 ownership is ambiguous' 'Не удалось однозначно подтвердить процессы, конфигурацию и владельца порта 443 Nginx; требуется ручная проверка'
    local actual expected
    actual=$(sha256sum "$UNIT"); expected=$(jq -er .unit_sha256 "$STATE/manifest.json")
    [[ ${actual%% *} == "$expected" ]] || ui_die 'Service changed; manual review required' 'Unit службы изменён; требуется ручная проверка'
    actual=$(sha256sum "$NGINX_ROOT/conf.d/telemt-web-manager.conf"); expected=$(jq -er .nginx_sha256 "$STATE/manifest.json")
    [[ ${actual%% *} == "$expected" ]] || ui_die 'Nginx vhost changed; manual review required' 'Vhost Nginx изменён; требуется ручная проверка'
    helper config-info "$CONFIG" >"$TMP/config-info" || ui_die 'automatic update/migration not possible; manual review required' 'Автоматическое обновление или перенос состояния остановлены; требуется ручная проверка'
    helper runtime-contract "$CONFIG" "$DATA" || ui_die 'Runtime/write paths require manual review; existing TOML was not changed' 'Рабочие пути или пути записи требуют ручной проверки; существующий TOML не изменён'
    SITE_DIGEST=$(helper site-bound "$CONFIG" "$DATA" "$NGINX_ROOT" "$SITE_ROOT") || ui_die 'Site ownership/hash differs; manual review required' 'Принадлежность или целостность сайта не подтверждена; требуется ручная проверка'
    installed_compatibility || ui_die 'Installed compatibility/isolation validation failed; no changes made' 'Проверка совместимости или изоляции установленной версии не пройдена; изменений не внесено'
    mapfile -t INFO <"$TMP/config-info"
    DOMAIN=${INFO[0]}; SOCKS=${INFO[1]}; PUBLIC_IP=${INFO[2]}
    [[ $(jq -r '.public_ip // ""' "$STATE/manifest.json") == "" ||
       $(jq -r .public_ip "$STATE/manifest.json") == "$PUBLIC_IP" ]] || ui_die 'WEB public address changed; manual review required' 'Публичный адрес WEB изменён; требуется ручная проверка'
    [[ $DOMAIN == "$(jq -er .domain "$STATE/manifest.json")" ]] || ui_die 'Domain changed; manual review required' 'Домен изменён; требуется ручная проверка'
    nginx_plan
    [[ $(jq '.edits | length' "$TMP/nginx-plan.json") == 0 ]] || ui_die 'Nginx integration incomplete; manual review required' 'Подключение к Nginx неполно; требуется ручная проверка'
    certificate_health_contract
}

update_manager() {
    load_installation
    path_health || ui_die 'Existing installation unhealthy; update refused' 'Установка не прошла проверку работоспособности; обновление остановлено'
    universal_update || ui_die 'Universal Update refused or rolled back; inspect private journal/backup evidence' 'Universal Update остановлен или отменён с восстановлением. Проверьте приватный журнал и резервную копию; может потребоваться ручное вмешательство'
}

check_manager() {
    load_installation
    renewal_scheduler_status
    local failed=0 pid cert current
    current=$(installed_release_identity) || return 1
    ui_info "Manager: $SCRIPT_VERSION; installed Telemt: $current; Install baseline: $SUPPORTED_TELEMT_VERSION; Update: newest stable compatible official release" "Менеджер: $SCRIPT_VERSION; установлен Telemt: $current; версия для новой установки: $SUPPORTED_TELEMT_VERSION; обновление: новейший стабильный совместимый официальный релиз"
    systemctl show telemt.service -p ActiveState -p SubState -p NRestarts -p User -p Group -p MainPID -p AmbientCapabilities -p CapabilityBoundingSet
    pid=$(systemctl show telemt.service -p MainPID --value)
    if [[ $pid =~ ^[1-9][0-9]*$ && -r /proc/$pid/status ]]; then
        sed -n -e '/^Uid:/p' -e '/^Gid:/p' -e '/^CapEff:/p' "/proc/$pid/status"
    else failed=1; fi
    listener_ready && ui_ok 'Listener: 127.0.0.1:18080, owned by Telemt' 'Слушатель: 127.0.0.1:18080, принадлежит Telemt' || failed=1
    path_health && ui_ok 'Nginx/local decoy/local SNI+TLS/public HTTPS/SOCKS: OK' 'Nginx / локальный сайт-прикрытие / локальный SNI+TLS / публичный HTTPS / SOCKS: исправны' || failed=1
    cert="$CERT_ROOT/live/$DOMAIN/fullchain.pem"
    openssl x509 -in "$cert" -noout -enddate || failed=1
    openssl x509 -in "$cert" -noout -checkend 604800 >/dev/null || failed=1
    recent_logs "$(( $(now) - 300 ))" || failed=1
    if (( failed )); then
        ui_err 'Check result: FAILED' 'Проверка не пройдена. Проверьте сообщения диагностики; может потребоваться ручная проверка.'
    else ui_ok 'Check result: OK' 'Результат проверки: OK'; fi
    return "$failed"
}

repair_manager() {
    load_installation
    helper runtime-contract "$CONFIG" "$DATA" || ui_die 'Config validation failed; no repair attempted' 'Конфигурация не прошла проверку; восстановление служб не запускалось'
    nginx_test || ui_die 'Nginx validation failed; no repair attempted' 'Nginx не прошёл проверку; восстановление служб не запускалось'
    backup_begin
    cp -a "$CONFIG" "$BACKUP/config.toml"
    cp -a "$UNIT" "$BACKUP/telemt.service"
    backup_nginx_context
    ui_info 'Managed files verified. Restarting Telemt and reloading validated Nginx.' 'Файлы установки проверены. Перезапускаем Telemt и перечитываем проверенную конфигурацию Nginx.'
    if ! restart_service || ! wait_ready 90 || ! nginx_reload || ! path_health; then
        ui_die 'Service recovery failed; manual review required' 'Работоспособность служб не восстановлена; требуется ручная проверка'
    fi
    if (( UI_INTERACTIVE )); then ui_ok 'Services restarted and checked successfully.' 'Службы перезапущены и успешно проверены.'; fi
}

# Uninstall uses identity contracts; it never requires Telemt readiness/HTTP.
write_certificate_state() {
    helper certificate-record-stage "$TMP/certificate.json" "$DOMAIN" "$CERT_ROOT" "$ACME_ROOT" "$NGINX_ROOT"
    helper safe-path "$STATE" || ui_die 'Unsafe certificate state directory' 'Небезопасный каталог состояния сертификата; операция остановлена'
    if [[ ! -e $STATE ]]; then install -d -m 0700 "$STATE"; fi
    [[ $(stat -c %a "$STATE") == 700 ]] || ui_die 'Unsafe certificate state permissions' 'Небезопасные права состояния сертификата; операция остановлена'
    if [[ -e $STATE/certificate.json || -L $STATE/certificate.json ]]; then
        helper certificate-record-check "$STATE" "$DOMAIN" "$CERT_ROOT" "$ACME_ROOT" "$NGINX_ROOT" || ui_die 'Certificate ownership record mismatch' 'Запись о принадлежности сертификата не совпадает; требуется ручная проверка'
    else
        atomic_copy "$TMP/certificate.json" "$STATE/certificate.json"
    fi
}

uninstall_load() {
    [[ -e $STATE/manifest.json || -L $STATE/manifest.json ]] || {
        ui_info 'No manager-owned Telemt installation found. Unmanaged Telemt is not removed automatically.' 'Установка Telemt, принадлежащая менеджеру, не найдена. Чужие установки автоматически не удаляются.'
        return 2
    }
    helper uninstall-plan "$TMP/uninstall-plan.json" "$BIN" "$CONFIG" "$UNIT" "$DATA" "$STATE" "$NGINX_ROOT" "$CERT_ROOT" "$ACME_ROOT" "$SITE_ROOT" ||
        ui_die 'Managed ownership/identity cannot be proven; no uninstall changes made' 'Принадлежность установки менеджеру не подтверждена; удаление не выполнялось'
    DOMAIN=$(jq -er '.certificate.domain' "$TMP/uninstall-plan.json")
    if [[ $(systemctl show telemt.service -p FragmentPath --value) != "$UNIT" ]] || ! managed_dropins; then
        ui_die 'Unexpected unit/drop-in; uninstall refused' 'Обнаружены неожиданный unit или дополнительные настройки; удаление остановлено'
    fi
    generate_unit >"$TMP/expected-unit"
    cmp -s "$UNIT" "$TMP/expected-unit" || ui_die 'Unit differs from exact manager contract' 'Unit службы отличается от ожидаемого контракта менеджера; операция остановлена'
    if ! nginx_test || ! systemctl is-active --quiet nginx || ! nginx_runtime_identity; then ui_die 'Nginx identity/configuration requires review' 'Принадлежность или конфигурация Nginx требует ручной проверки'; fi
    validate_certificate identity
    certificate_renewal_contract
    renewal_deploy_hook_contract
    PLAN_MODE=uninstall
    nginx_plan
    UNINSTALL_ENABLED=$(systemctl is-enabled telemt.service || true)
    UNINSTALL_ACTIVE=$(systemctl show telemt.service -p ActiveState --value)
    [[ $UNINSTALL_ENABLED == enabled || $UNINSTALL_ENABLED == disabled ]] || ui_die 'Ambiguous service enabled state' 'Не удалось однозначно определить автозапуск службы; операция остановлена'
    [[ $UNINSTALL_ACTIVE == active || $UNINSTALL_ACTIVE == inactive || $UNINSTALL_ACTIVE == failed ]] || ui_die 'Service transition in progress; retry after review' 'Служба меняет состояние; проверьте её и повторите попытку'
}

uninstall_firewall_absent() {
    nft list ruleset >"$TMP/nft-final" && iptables-save >"$TMP/iptables-final" && ip6tables-save >"$TMP/ip6tables-final" || return 1
    ! grep -Eq 'telemt_conntrack(_a|_b)?|TELEMT_NOTRACK|TELEMT_NT_[AB]' "$TMP/nft-final" "$TMP/iptables-final" "$TMP/ip6tables-final"
}

uninstall_quiet() {
    local active
    active=$(systemctl show telemt.service -p ActiveState --value) || return 1
    [[ $active == inactive || $active == failed ]] || return 1
    helper uninstall-quiet "$BACKUP" || return 1
    [[ -z $(ss -H -ltn 'sport = :18080') ]] || return 1
    uninstall_firewall_absent
}

uninstall_remove_files() { helper uninstall-remove "$BACKUP"; }
uninstall_remove_account() { helper uninstall-account-remove "$BACKUP"; }

# The issuance subshell has its own edit arrays; these are the parent transaction.
# shellcheck disable=SC2031
uninstall_rollback() {
    local failed=0 index
    ui_warn 'Rolling back managed uninstall.' 'Восстанавливаем установку после ошибки удаления.' >&2
    helper uninstall-restore "$BACKUP" || failed=1
    if (( ! failed )); then
        for ((index=${#CHANGED[@]}-1; index>=0; index--)); do
            if [[ -n ${ORIGINAL[index]} ]]; then atomic_copy "${ORIGINAL[index]}" "${CHANGED[index]}" || failed=1
            else helper safe-path "${CHANGED[index]}" && rm -f -- "${CHANGED[index]}" || failed=1; fi
        done
        systemctl daemon-reload || failed=1
        if [[ $UNINSTALL_ENABLED == enabled ]]; then systemctl enable telemt.service || failed=1
        else systemctl disable telemt.service || failed=1; fi
        if (( NGINX_CHANGED )); then nginx_test && nginx_reload || failed=1; fi
        if [[ $UNINSTALL_ACTIVE == active ]]; then systemctl start telemt.service || failed=1; fi
    fi
    if (( failed )); then ui_err "CRITICAL: uninstall rollback incomplete; retain $BACKUP for manual recovery" "КРИТИЧЕСКАЯ ОШИБКА: восстановление после удаления не завершено. Сохраните $BACKUP для ручного восстановления" >&2; fi
    return "$failed"
}

uninstall_final() {
    local path
    for path in "$BIN" "$CONFIG_DIR" "$UNIT" "$DATA" "$STATE/manifest.json" "$STATE/web-link.txt"; do
        [[ ! -e $path && ! -L $path ]] || return 1
    done
    for path in "$STATE/telemt-release.json" "$STATE/telemt-generation.json" "$STATE/update-journal.json" \
        "$UNIT.d/50-telemt-web-manager-update.conf" "${UNIT%/*}/telemt-web-manager-recovery.service"; do
        [[ ! -e $path && ! -L $path ]] || return 1
    done
    if getent passwd telemt >/dev/null || getent group telemt >/dev/null; then return 1; fi
    [[ -z $(systemctl show telemt.service -p FragmentPath --value) &&
       -z $(ss -H -ltn 'sport = :18080 or sport = :7444') ]] || return 1
    uninstall_firewall_absent && nginx_test && systemctl is-active --quiet nginx || return 1
    PLAN_MODE=web
    build_nginx_plan "$TMP/absent-plan.json" || return 1
    # Both formats must plan a fresh HTTPS vhost after complete removal.
    # The stream format determines whether there are two or three edits.
    jq -e --arg vhost "$NGINX_ROOT/conf.d/telemt-web-manager.conf" \
        'any(.edits[]; .path == $vhost and .old == null and .content != null)' \
        "$TMP/absent-plan.json" >/dev/null || return 1
    [[ -x $BASE_DIR/telemt-web-manager.sh && -f $HELPER ]] || return 1
    helper certificate-record-check "$STATE" "$DOMAIN" "$CERT_ROOT" "$ACME_ROOT" "$NGINX_ROOT"
}

# Certificate cleanup is deliberately outside the committed Telemt transaction.
delete_managed_certificate() {
    helper certificate-record-check "$STATE" "$DOMAIN" "$CERT_ROOT" "$ACME_ROOT" "$NGINX_ROOT" || return 1
    validate_certificate identity
    renewal_deploy_hook_contract
    # Verify the installed Certbot exposes this bounded deletion interface.
    certbot delete --help >"$TMP/certbot-delete-help" 2>&1 || return 1
    grep -q -- '--cert-name' "$TMP/certbot-delete-help" || return 1
    nginx_test || return 1
    helper certificate-cleanup-plan "$TMP/certificate-cleanup.json" "$STATE" "$DOMAIN" "$CERT_ROOT" "$ACME_ROOT" "$NGINX_ROOT" "$RENEW_HOOK" || return 1
    cp "$TMP/certificate-cleanup.json" "$BACKUP/certificate-cleanup.json" || return 1
    if [[ -f $NGINX_ROOT/conf.d/telemt-web-manager-acme.conf ]]; then
        cp -p "$NGINX_ROOT/conf.d/telemt-web-manager-acme.conf" "$BACKUP/acme-vhost" || return 1
    fi
    certbot delete --non-interactive --cert-name "$DOMAIN" >"$BACKUP/certificate-delete.log" 2>&1 || return 1
    [[ ! -e $CERT_ROOT/live/$DOMAIN && ! -L $CERT_ROOT/live/$DOMAIN &&
       ! -e $CERT_ROOT/archive/$DOMAIN && ! -L $CERT_ROOT/archive/$DOMAIN &&
       ! -e $CERT_ROOT/renewal/$DOMAIN.conf && ! -L $CERT_ROOT/renewal/$DOMAIN.conf ]] || return 1
    helper certificate-cleanup-remove "$TMP/certificate-cleanup.json" || return 1
    if ! nginx_test || ! nginx_reload; then
        if [[ -f $BACKUP/acme-vhost ]]; then
            atomic_copy "$BACKUP/acme-vhost" "$NGINX_ROOT/conf.d/telemt-web-manager-acme.conf"
            if nginx_test; then nginx_reload || true; fi
        fi
        return 1
    fi
}

uninstall_manager() {
    local status=0 answer dep
    for dep in groupadd find iptables-save ip6tables-save; do need "$dep"; done
    uninstall_load || status=$?
    if (( status == 2 )); then return 1; fi
    (( status == 0 )) || return "$status"
    ui_ok "Managed Telemt deployment: $DOMAIN; service telemt.service; config $CONFIG; data $DATA. Certificate: preserve by default. Manager remains installed." "Установка Telemt: $DOMAIN; служба telemt.service; конфигурация $CONFIG; данные $DATA. По умолчанию сертификат сохраняется. Менеджер остаётся установленным."
    if (( ! CONFIRM_UNINSTALL )); then
        [[ -t 0 ]] || ui_die 'Use --uninstall --confirm-uninstall; certificate is preserved by default' 'Для удаления без диалога укажите --uninstall --confirm-uninstall; по умолчанию сертификат сохраняется'
        read -r -p "$(ui_text 'Type UNINSTALL to remove the managed Telemt deployment: ' 'Для удаления этой установки Telemt введите UNINSTALL: ')" answer
        [[ $answer == UNINSTALL ]] || { ui_warn 'Uninstall cancelled.' 'Удаление отменено.'; return; }
        read -r -p "$(ui_text "Delete the Let's Encrypt certificate for $DOMAIN too? [y/N] " "Удалить также сертификат Let's Encrypt для $DOMAIN? [y/N] ")" answer
        if [[ $answer == y || $answer == Y ]]; then DELETE_CERTIFICATE=1; fi
    fi
    backup_begin
    backup_nginx_context
    printf '%s\n%s\n' "$UNINSTALL_ENABLED" "$UNINSTALL_ACTIVE" >"$BACKUP/service-state"
    cp "$TMP/certificate.json" "$BACKUP/certificate-ownership.json" 2>/dev/null ||
        helper certificate-record-stage "$BACKUP/certificate-ownership.json" "$DOMAIN" "$CERT_ROOT" "$ACME_ROOT" "$NGINX_ROOT"
    jq --arg enabled "$UNINSTALL_ENABLED" --arg active "$UNINSTALL_ACTIVE" \
        '.service = {enabled: $enabled, active: $active}' "$TMP/uninstall-plan.json" >"$TMP/uninstall-initial.json"
    helper uninstall-backup "$TMP/uninstall-initial.json" "$BACKUP"
    UNINSTALLING=1 ARMED=1
    if [[ ! -e $STATE/certificate.json ]]; then
        track_file "$STATE/certificate.json"
        write_certificate_state
    fi
    if ! cmp -s "$UNIT" "$TMP/expected-unit" ||
        [[ $(systemctl show telemt.service -p FragmentPath --value) != "$UNIT" ]] || ! managed_dropins; then ui_die 'Unit identity changed before stop' 'Unit службы изменился перед остановкой; удаление остановлено'; fi
    systemctl disable --now telemt.service || ui_die 'Telemt stop/disable failed' 'Не удалось остановить Telemt или отключить его автозапуск'
    if [[ -f ${UNIT%/*}/telemt-web-manager-recovery.service ]]; then
        systemctl stop telemt-web-manager-recovery.service || ui_die 'Managed recovery service stop failed' 'Не удалось остановить службу восстановления менеджера'
    fi
    uninstall_quiet || ui_die 'Owned process/listener/firewall state remains; uninstall rolled back' 'После остановки остались процессы, слушатели или правила firewall Telemt; удаление отменено с восстановлением'
    helper uninstall-refresh "$BACKUP" || ui_die 'Unable to snapshot stopped runtime; uninstall rolled back' 'Не удалось сохранить снимок остановленной установки; удаление отменено с восстановлением'
    apply_nginx
    uninstall_remove_files || ui_die 'Managed file removal failed' 'Не удалось удалить файлы установки; требуется проверка результата восстановления'
    systemctl daemon-reload
    uninstall_remove_account || ui_die 'Managed account cleanup failed' 'Не удалось удалить учётную запись установки; требуется проверка результата восстановления'
    uninstall_final || ui_die 'Final uninstall absence/renewal validation failed' 'Итоговая проверка удаления или продления сертификата не пройдена; выполняется восстановление'
    ARMED=0 UNINSTALLING=0
    ui_ok 'Telemt uninstall succeeded. Manager and backups retained; certificate preserved.' 'Telemt удалён. Менеджер, резервные копии и сертификат сохранены.'
    if (( DELETE_CERTIFICATE )); then
        CERT_CLEANUP_RUNNING=1
        if (trap - EXIT; delete_managed_certificate); then CERT_CLEANUP_RUNNING=0; ui_info 'Exact managed certificate and unused renewal assets removed.' 'Принадлежащий установке сертификат и неиспользуемые файлы продления удалены.'
        else CERT_CLEANUP_RUNNING=0; ui_warn "Telemt uninstall succeeded. Certificate cleanup failed or requires manual review. Ownership/backup evidence: $BACKUP" "Telemt удалён. Очистка сертификата не удалась или требует ручной проверки. Сведения о принадлежности и резервная копия: $BACKUP" >&2; return 1; fi
    fi
}

usage() {
    cat <<EOF
Telegram Web Proxy Manager $SCRIPT_VERSION
Usage: telegram-web-proxy-manager --install|--update|--check|--repair|--uninstall|--help
Install options: --domain proxy.example.com --public-ip 203.0.113.10
                 [--socks 127.0.0.1:1080] [--email ADDRESS --agree-tos]
Uninstall: --uninstall --confirm-uninstall [--delete-certificate]
Certificate preserved by default; only proven manager-owned Telemt is removed.
Without arguments: interactive menu (requires TTY).
Existing SNI router with proxy_protocol on and a conf.d HTTP include required.
Check is read-only. Repair only restarts/reloads verified managed services.
EOF
}

main() {
    local action='' choice arguments=$#
    MENU_ACTION=0 INTERACTIVE_INSTALL=0 UI_LANG=en UI_INTERACTIVE=0
    while (( $# )); do
        case $1 in
            --help) usage; return;;
            --install|--update|--check|--repair|--uninstall) [[ -z $action ]] || die 'Choose one action'; action=$1; shift;;
            --domain|--public-ip|--socks|--email)
                (( $# >= 2 )) || die 'Missing option value'
                case $1 in --domain) DOMAIN=$2;; --public-ip) PUBLIC_IP=$2;; --socks) SOCKS=$2;; --email) EMAIL=$2;; esac
                shift 2;;
            --confirm-uninstall) CONFIRM_UNINSTALL=1; shift;;
            --delete-certificate) DELETE_CERTIFICATE=1; shift;;
            --agree-tos) AGREE_TOS=1; shift;;
            *) die 'Unknown option; see --help';;
        esac
    done
    if [[ -z $action ]]; then
        (( arguments == 0 )) || die 'No action specified; see --help'
        [[ -t 0 && -t 1 ]] || die 'No interactive terminal; specify an action'
        trap 'exit 130' INT
        UI_INTERACTIVE=1
        ui_select_language || return 0
        ui_main_menu
        read -r -p "$(ui_text '  Select an option: ' '  Выберите пункт: ')" choice || return 0
        MENU_ACTION=1
        case $choice in 1) action=--install; INTERACTIVE_INSTALL=1;; 2) action=--update;; 3) action=--check;; 4) action=--repair;; 5) action=show-web-link;; 6) action=--uninstall;; 0) return;; *) ui_die 'Invalid selection' 'Неверный пункт меню; операция не запускалась';; esac
    fi
    if (( CONFIRM_UNINSTALL || DELETE_CERTIFICATE )); then
        [[ $action == --uninstall ]] || die 'Uninstall flags require --uninstall'
        (( ! DELETE_CERTIFICATE || CONFIRM_UNINSTALL )) || die '--delete-certificate requires --confirm-uninstall'
    fi
    if [[ $action == show-web-link ]]; then show_current_web_link; return; fi
    preflight "$action"
    TMP=$(mktemp -d /tmp/telemt-web-manager.XXXXXXXX)
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM HUP
    if [[ $action == --check ]]; then
        take_lock shared
        pending_update || ui_die 'Pending/critical Update; Check remains read-only' 'Обновление не завершено или требует вмешательства; проверка состояния не изменяет установку. Требуется ручная проверка'
    else
        take_lock
        recover_update || ui_die 'Pending Update recovery requires manual review' 'Восстановление незавершённого обновления требует ручной проверки; выбранная операция остановлена'
    fi
    case $action in --install) install_manager;; --update) update_manager;; --check) check_manager;; --repair) repair_manager;; --uninstall) uninstall_manager;; esac
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then main "$@"; fi
