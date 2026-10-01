#!/usr/bin/env bash
# Install only the manager program pair from an official published release.
set +x
set -Eeuo pipefail
umask 077
export LC_ALL=C
INSTALL_DIR=/opt/telemt-web-manager
LAUNCHER=/usr/local/bin/telemt-web-manager
BOOTSTRAP_LOCK=/run/lock/telemt-web-manager.lock
BOOTSTRAP_TMP='' MANAGER_TAG='' MANAGER_COMMIT='' VERSION='' NO_START=0
readonly MANAGER_REPO=xPROMSx/telemt-web-manager

bootstrap_die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
bootstrap_download() {
    curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fLsS \
        --connect-timeout 10 --max-time 60 --max-filesize 8388608 --retry 2 "$1" -o "$2" || return 1
    [[ -s $2 ]]
}

resolve_manager_release() {
    local page count sha kind depth
    local -a metadata=()
    if [[ -n $VERSION ]]; then
        [[ $VERSION =~ ^v[0-9]+\.[0-9]+\.[0-9]+([+-][0-9A-Za-z.-]+)?$ ]] || bootstrap_die 'Expected a published version tag, e.g. v0.1.0'
        bootstrap_download "https://api.github.com/repos/$MANAGER_REPO/releases/tags/$VERSION" "$BOOTSTRAP_TMP/releases.json" || bootstrap_die 'Manager release metadata unavailable'
        metadata+=("$BOOTSTRAP_TMP/releases.json")
    else
        for ((page=1; page<=20; page++)); do
            bootstrap_download "https://api.github.com/repos/$MANAGER_REPO/releases?per_page=100&page=$page" "$BOOTSTRAP_TMP/releases-$page.json" || bootstrap_die 'Manager release metadata unavailable'
            metadata+=("$BOOTSTRAP_TMP/releases-$page.json")
            count=$(python3 - "${metadata[-1]}" <<'PY'
import json, sys
value = json.load(open(sys.argv[1]))
if not isinstance(value, list): sys.exit(1)
print(len(value))
PY
            ) || bootstrap_die 'Invalid manager release list'
            (( count == 100 )) || break
        done
        (( count < 100 )) || bootstrap_die 'Release history too large; select --version explicitly'
    fi
    MANAGER_TAG=$(python3 - "$VERSION" "${metadata[@]}" <<'PY'
import datetime, json, re, sys
releases = []
for filename in sys.argv[2:]:
    value = json.load(open(filename))
    releases.extend(value if isinstance(value, list) else [value])
valid = []
for release in releases:
    if release.get('draft') is True: continue
    if release.get('draft') is not False or not isinstance(release.get('prerelease'), bool): sys.exit(1)
    tag = release.get('tag_name', '')
    if not re.fullmatch(r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?', tag): sys.exit(1)
    if release.get('html_url') != 'https://github.com/xPROMSx/telemt-web-manager/releases/tag/' + tag: sys.exit(1)
    published = datetime.datetime.fromisoformat(release['published_at'].replace('Z', '+00:00'))
    if published.tzinfo is None: sys.exit(1)
    valid.append((published, tag, release['prerelease']))
if sys.argv[1]:
    valid = [r for r in valid if r[1] == sys.argv[1]]
else:
    stable = [r for r in valid if not r[2]]
    if stable: valid = stable
if not valid: sys.exit(1)
latest = max(r[0] for r in valid)
selected = [r for r in valid if r[0] == latest]
if len(selected) != 1: sys.exit(1)
print(selected[0][1])
PY
    ) || bootstrap_die 'Ambiguous or invalid published manager release'
    bootstrap_download "https://api.github.com/repos/$MANAGER_REPO/git/ref/tags/$MANAGER_TAG" "$BOOTSTRAP_TMP/ref.json" || bootstrap_die 'Published manager tag unavailable'
    for ((depth=0; depth<5; depth++)); do
        read -r sha kind < <(python3 - "$BOOTSTRAP_TMP/ref.json" "$MANAGER_TAG" "$depth" <<'PY'
import json, re, sys
value = json.load(open(sys.argv[1]))
obj = value.get('object', {})
if sys.argv[3] == '0' and value.get('ref') != 'refs/tags/' + sys.argv[2]: sys.exit(1)
sha, kind = obj.get('sha', ''), obj.get('type', '')
if not re.fullmatch('[0-9a-f]{40}', sha) or kind not in ('commit', 'tag'): sys.exit(1)
print(sha, kind)
PY
        ) || bootstrap_die 'Invalid manager tag object'
        if [[ $kind == commit ]]; then MANAGER_COMMIT=$sha; return; fi
        bootstrap_download "https://api.github.com/repos/$MANAGER_REPO/git/tags/$sha" "$BOOTSTRAP_TMP/ref.json" || bootstrap_die 'Annotated manager tag unavailable'
    done
    bootstrap_die 'Manager tag does not resolve to one commit'
}

validate_manager_pair() {
    [[ -s $BOOTSTRAP_TMP/telemt-web-manager.sh && -s $BOOTSTRAP_TMP/safety.py ]] || bootstrap_die 'Empty manager download'
    bash -n "$BOOTSTRAP_TMP/telemt-web-manager.sh" || bootstrap_die 'Invalid manager Bash syntax'
    python3 - "$BOOTSTRAP_TMP/safety.py" <<'PY'
from pathlib import Path
import sys
compile(Path(sys.argv[1]).read_bytes(), 'safety.py', 'exec')
PY
}

commit_manager_pair() {
    # Linux renameat2 exchanges complete directories atomically. Never copy into
    # the live pair. The common manager lock excludes active manager operations.
    python3 - "$BOOTSTRAP_TMP" "$INSTALL_DIR" "$LAUNCHER" "$BOOTSTRAP_LOCK" <<'PY'
import ctypes, fcntl, os, shutil, signal, stat, sys, tempfile
from pathlib import Path
source, dest, launcher, lock = map(Path, sys.argv[1:])

def safe(path, regular=False):
    for item in (path, *path.parents):
        try: info = item.lstat()
        except FileNotFoundError: continue
        sticky = stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
        if info.st_uid != 0 or stat.S_ISLNK(info.st_mode) or (info.st_mode & 0o022 and not sticky):
            raise ValueError('Unsafe bootstrap path; manual review required')
        if item == path and regular:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('Expected a regular manager file')
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError('Expected a manager directory')

def existing_pair():
    safe(dest)
    if not dest.exists(): return False
    if {p.name for p in dest.iterdir()} != {'telemt-web-manager.sh', 'lib'}:
        raise ValueError('Unrelated installation directory; manual review required')
    safe(dest / 'lib')
    if {p.name for p in (dest / 'lib').iterdir()} != {'safety.py'}:
        raise ValueError('Unrelated manager helper directory; manual review required')
    for p in (dest / 'telemt-web-manager.sh', dest / 'lib/safety.py'): safe(p, regular=True)
    if not (dest / 'telemt-web-manager.sh').read_bytes().startswith(b'#!/usr/bin/env bash\n# Telemt WEB Manager.'):
        raise ValueError('Existing program is not recognized as this manager')
    if not (dest / 'lib/safety.py').read_bytes().startswith(b'#!/usr/bin/env python3\n\"\"\"Strict, read-only parsers and staged Nginx plans.'):
        raise ValueError('Existing helper requires manual review')
    return True

wrapper = ('#!/bin/sh\nexec ' + str(dest / 'telemt-web-manager.sh') + ' "$@"\n').encode()
stage = staged_launcher = None
swapped = created = launcher_created = committed = False
libc = ctypes.CDLL(None, use_errno=True)
exchange = getattr(libc, 'renameat2', None)
if exchange is None: raise SystemExit('ERROR: Atomic directory exchange unavailable')
exchange.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
exchange.restype = ctypes.c_int

def swap(a, b):
    if exchange(-100, os.fsencode(a), -100, os.fsencode(b), 2):
        raise OSError(ctypes.get_errno(), 'Atomic manager directory exchange failed')

def interrupted(signum, frame):
    if not committed: raise InterruptedError('Bootstrap interrupted')
for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP): signal.signal(sig, interrupted)
try:
    safe(dest.parent); safe(launcher.parent); safe(lock.parent)
    with os.fdopen(os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600), 'r+') as held:
        info = os.fstat(held.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('Unsafe manager lock')
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        had_pair = existing_pair()
        safe(launcher, regular=True)
        if launcher.exists() and launcher.read_bytes() != wrapper:
            raise ValueError('Unrelated launcher; manual review required')
        had_launcher = launcher.exists()
        if had_launcher and (stat.S_IMODE(launcher.stat().st_mode) != 0o755 or launcher.stat().st_gid != 0):
            raise ValueError('Existing launcher mode requires manual review')
        # All validation precedes creation of installation staging/commit files.
        stage = Path(tempfile.mkdtemp(prefix='.telemt-web-manager.', dir=dest.parent))
        (stage / 'lib').mkdir(0o755)
        for src, relative, mode in ((source / 'telemt-web-manager.sh', 'telemt-web-manager.sh', 0o755), (source / 'safety.py', 'lib/safety.py', 0o644)):
            target = stage / relative
            shutil.copyfile(src, target)
            os.chown(target, 0, 0); target.chmod(mode)
        os.chown(stage, 0, 0); os.chown(stage / 'lib', 0, 0)
        stage.chmod(0o755); (stage / 'lib').chmod(0o755)
        fd, filename = tempfile.mkstemp(prefix='.telemt-web-manager.', dir=launcher.parent)
        staged_launcher = Path(filename)
        with os.fdopen(fd, 'wb') as output: output.write(wrapper)
        os.chown(staged_launcher, 0, 0); staged_launcher.chmod(0o755)
        # Block catchable signals only across the tiny commit/rollback window.
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})
        try:
            if had_pair: swap(stage, dest); swapped = True
            else: os.rename(stage, dest); created = True
            if not had_launcher:
                os.replace(staged_launcher, launcher); launcher_created = True
            committed = True
        except BaseException:
            if swapped: swap(stage, dest); swapped = False
            elif created: os.rename(dest, stage); created = False
            if launcher_created: launcher.unlink(); launcher_created = False
            raise
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
except (OSError, ValueError) as error:
    print('ERROR: ' + str(error), file=sys.stderr); sys.exit(1)
finally:
    if stage is not None and stage.exists(): shutil.rmtree(stage)
    if staged_launcher is not None and staged_launcher.exists(): staged_launcher.unlink()
PY
}

launch_manager_menu() {
    if (( ! NO_START )) && [[ -t 0 && -t 1 ]]; then "$LAUNCHER"; fi
}

bootstrap_main() {
    (( EUID == 0 )) || bootstrap_die 'Run the manager installer as root'
    while (( $# )); do
        case $1 in
            --version) (( $# >= 2 )) || bootstrap_die 'Missing --version tag'; VERSION=$2; shift 2;;
            --no-start) NO_START=1; shift;;
            *) bootstrap_die 'Usage: install.sh [--version vX.Y.Z] [--no-start]';;
        esac
    done
    local tool
    for tool in bash curl python3 mktemp rm; do command -v "$tool" >/dev/null || bootstrap_die "Missing dependency: $tool"; done
    python3 -c 'import sys; sys.exit(sys.version_info < (3,11))' || bootstrap_die 'Python 3.11+ required'
    BOOTSTRAP_TMP=$(mktemp -d)
    trap 'rm -rf -- "$BOOTSTRAP_TMP"' EXIT
    resolve_manager_release
    local base="https://raw.githubusercontent.com/$MANAGER_REPO/$MANAGER_COMMIT"
    bootstrap_download "$base/telemt-web-manager.sh" "$BOOTSTRAP_TMP/telemt-web-manager.sh" || bootstrap_die 'Manager shell download failed/empty'
    bootstrap_download "$base/lib/safety.py" "$BOOTSTRAP_TMP/safety.py" || bootstrap_die 'Manager helper download failed/empty'
    validate_manager_pair || bootstrap_die 'Invalid manager Python/Bash syntax'
    commit_manager_pair || bootstrap_die 'Manager installation transaction failed; previous pair retained'
    printf 'Installed manager %s (%s). Run: telemt-web-manager\n' "$MANAGER_TAG" "$MANAGER_COMMIT"
    rm -rf -- "$BOOTSTRAP_TMP"; BOOTSTRAP_TMP=''
    launch_manager_menu
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then bootstrap_main "$@"; fi
