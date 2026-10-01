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

# Shared by release selection, downloaded-pair validation and the locked guard.
# This code is part of the installer, never loaded from an installed/downloaded file.
bootstrap_version_code() {
    cat <<'PY'
import json, re
from pathlib import Path

def load_metadata(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Duplicate manager metadata field')
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique)

VERSION_RE = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
                        r'(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?'
                        r'(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?')

def version_key(value):
    if not isinstance(value, str): raise ValueError('Invalid manager SemVer')
    match = VERSION_RE.fullmatch(value)
    if match is None: raise ValueError('Invalid manager SemVer')
    identifiers = match[4].split('.') if match[4] else []
    if any(x.isdigit() and len(x) > 1 and x.startswith('0') for x in identifiers):
        raise ValueError('Invalid numeric prerelease identifier')
    # Length + ASCII digits compares arbitrarily large numbers without overflow
    # or Python's integer-string conversion limit. Build metadata is excluded.
    core = tuple((len(match[i]), match[i]) for i in (1, 2, 3))
    pre = tuple((0, len(x), x) if x.isdigit() else (1, x) for x in identifiers)
    return core, not identifiers, pre

def manager_version(path):
    content = Path(path).read_bytes().decode('utf-8')
    # The fixed prologue puts the declaration outside shell strings/heredocs.
    # Only the exact generated syntax is supported, without shell interpretation.
    source_lines = content.split('\n')
    if (source_lines[2:6] != ['set +x', 'set -Eeuo pipefail', 'umask 077', 'export LC_ALL=C']
            or len(source_lines) < 7 or not source_lines[6].startswith('readonly SCRIPT_VERSION=')):
        raise ValueError('Unrecognized manager version prologue')
    # Reject other bare references too (nested/quoted/conditional assignments).
    lines = [line for line in source_lines if not line.lstrip().startswith('#')
             and re.search(r'(?<![\w${])SCRIPT_VERSION\b', line)]
    if len(lines) != 1 or not lines[0].startswith('readonly SCRIPT_VERSION='):
        raise ValueError('Missing or ambiguous installed SCRIPT_VERSION')
    value = lines[0][len('readonly SCRIPT_VERSION='):]
    version_key(value)
    return value
PY
}

resolve_manager_release() {
    local page count sha kind depth
    local -a metadata=()
    if [[ -n $VERSION ]]; then
        # Keep the public explicit-tag surface: one prerelease OR build suffix.
        [[ $VERSION =~ ^v[0-9]+\.[0-9]+\.[0-9]+([+-][0-9A-Za-z.-]+)?$ ]] || bootstrap_die 'Expected a published version tag, e.g. v0.1.0'
        { bootstrap_version_code; cat <<'PYCODE'
import sys
if not sys.argv[1].startswith('v'): sys.exit(1)
version_key(sys.argv[1][1:])
PYCODE
        } | python3 - "$VERSION" || bootstrap_die 'Expected a published SemVer tag, e.g. v0.1.0'
        bootstrap_download "https://api.github.com/repos/$MANAGER_REPO/releases/tags/$VERSION" "$BOOTSTRAP_TMP/releases.json" || bootstrap_die 'Manager release metadata unavailable'
        metadata+=("$BOOTSTRAP_TMP/releases.json")
    else
        for ((page=1; page<=20; page++)); do
            bootstrap_download "https://api.github.com/repos/$MANAGER_REPO/releases?per_page=100&page=$page" "$BOOTSTRAP_TMP/releases-$page.json" || bootstrap_die 'Manager release metadata unavailable'
            metadata+=("$BOOTSTRAP_TMP/releases-$page.json")
            count=$({ bootstrap_version_code; cat <<'PY'
import sys
value = load_metadata(sys.argv[1])
if not isinstance(value, list) or len(value) > 100: sys.exit(1)
print(len(value))
PY
            } | python3 - "${metadata[-1]}"
            ) || bootstrap_die 'Invalid manager release list'
            (( count == 100 )) || break
        done
        (( count < 100 )) || bootstrap_die 'Release history too large; select --version explicitly'
    fi
    MANAGER_TAG=$({ bootstrap_version_code; cat <<'PY'
import datetime, sys
releases = []
for filename in sys.argv[2:]:
    value = load_metadata(filename)
    if sys.argv[1]:
        if not isinstance(value, dict): sys.exit(1)
        releases.append(value)
    else:
        if not isinstance(value, list): sys.exit(1)
        releases.extend(value)
valid, seen = [], set()
for release in releases:
    if not isinstance(release, dict): sys.exit(1)
    if release.get('draft') is True: continue
    if release.get('draft') is not False or not isinstance(release.get('prerelease'), bool): sys.exit(1)
    tag = release.get('tag_name')
    if not isinstance(tag, str) or not tag.startswith('v'): sys.exit(1)
    key = version_key(tag[1:])
    if tag in seen: sys.exit(1)
    seen.add(tag)
    if release.get('html_url') != 'https://github.com/xPROMSx/telemt-web-manager/releases/tag/' + tag: sys.exit(1)
    published = release.get('published_at')
    if not isinstance(published, str): sys.exit(1)
    if datetime.datetime.fromisoformat(published.replace('Z', '+00:00')).tzinfo is None: sys.exit(1)
    # A GitHub prerelease flag on a plain core version remains supported (v0.1.0
    # is published that way). A SemVer prerelease cannot be treated as stable.
    valid.append((key, tag, release['prerelease'] or not key[1]))
if sys.argv[1]:
    valid = [r for r in valid if r[1] == sys.argv[1]]
else:
    stable = [r for r in valid if not r[2]]
    if stable: valid = stable
if not valid: sys.exit(1)
latest = max(r[0] for r in valid)
selected = [r for r in valid if r[0] == latest]
# Distinct tags at equal highest precedence require administrator selection.
if len(selected) != 1: sys.exit(1)
print(selected[0][1])
PY
    } | python3 - "$VERSION" "${metadata[@]}"
    ) || bootstrap_die 'Ambiguous or invalid published manager release; select --version explicitly after review'
    bootstrap_download "https://api.github.com/repos/$MANAGER_REPO/git/ref/tags/$MANAGER_TAG" "$BOOTSTRAP_TMP/ref.json" || bootstrap_die 'Published manager tag unavailable'
    for ((depth=0; depth<5; depth++)); do
        local object
        object=$({ bootstrap_version_code; cat <<'PY'
import sys
value = load_metadata(sys.argv[1])
obj = value.get('object', {})
if sys.argv[3] == '0':
    if value.get('ref') != 'refs/tags/' + sys.argv[2]: sys.exit(1)
elif value.get('sha') != sys.argv[4]: sys.exit(1)
sha, kind = obj.get('sha', ''), obj.get('type', '')
if not re.fullmatch('[0-9a-f]{40}', sha) or kind not in ('commit', 'tag'): sys.exit(1)
print(sha, kind)
PY
        } | python3 - "$BOOTSTRAP_TMP/ref.json" "$MANAGER_TAG" "$depth" "${sha:-}"
        ) || bootstrap_die 'Invalid manager tag object'
        read -r sha kind <<<"$object"
        if [[ $kind == commit ]]; then MANAGER_COMMIT=$sha; return; fi
        bootstrap_download "https://api.github.com/repos/$MANAGER_REPO/git/tags/$sha" "$BOOTSTRAP_TMP/ref.json" || bootstrap_die 'Annotated manager tag unavailable'
    done
    bootstrap_die 'Manager tag does not resolve to one commit'
}

validate_manager_pair() {
    [[ -s $BOOTSTRAP_TMP/telemt-web-manager.sh && -s $BOOTSTRAP_TMP/safety.py ]] || bootstrap_die 'Empty manager download'
    bash -n "$BOOTSTRAP_TMP/telemt-web-manager.sh" || bootstrap_die 'Invalid manager Bash syntax'
    { bootstrap_version_code; cat <<'PY'
import sys
script, helper, tag = sys.argv[1:]
if not Path(script).read_bytes().startswith(b'#!/usr/bin/env bash\n# Telemt WEB Manager.'):
    raise ValueError('Downloaded program is not recognized as this manager')
if not Path(helper).read_bytes().startswith(b'#!/usr/bin/env python3\n"""Strict, read-only parsers and staged Nginx plans.'):
    raise ValueError('Downloaded helper is not recognized')
if manager_version(script) != tag[1:]:
    raise ValueError('Downloaded SCRIPT_VERSION does not match published tag')
compile(Path(helper).read_bytes(), 'safety.py', 'exec')
PY
    } | python3 - "$BOOTSTRAP_TMP/telemt-web-manager.sh" "$BOOTSTRAP_TMP/safety.py" "$MANAGER_TAG"
}

commit_manager_pair() {
    # Linux renameat2 exchanges complete directories atomically. Never copy into
    # the live pair. The common manager lock excludes active manager operations.
    { bootstrap_version_code; cat <<'PY'
import ctypes, fcntl, os, shutil, signal, stat, sys, tempfile
from pathlib import Path
source, dest, launcher, lock = map(Path, sys.argv[1:5])
tag, explicit = sys.argv[5:]

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
        if had_pair:
            installed = manager_version(dest / 'telemt-web-manager.sh')
            if not explicit and version_key(tag[1:]) < version_key(installed):
                raise ValueError(f'Installed manager {installed}; automatically selected {tag}; '
                                 'automatic downgrade refused. Use --version for an intentional published version.')
        # All validation and downgrade checks precede installation staging/commit files.
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
    if stage is not None and stage.exists():
        if swapped and not committed:
            print(f'ERROR: Rollback exchange failed; previous manager pair retained at {stage}; manual recovery required', file=sys.stderr)
        else: shutil.rmtree(stage)
    if staged_launcher is not None and staged_launcher.exists(): staged_launcher.unlink()
PY
    } | python3 - "$BOOTSTRAP_TMP" "$INSTALL_DIR" "$LAUNCHER" "$BOOTSTRAP_LOCK" "$MANAGER_TAG" "$VERSION"
}

launch_manager_menu() {
    if (( ! NO_START )) && [[ -t 0 && -t 1 ]]; then "$LAUNCHER"; fi
}

bootstrap_main() {
    (( EUID == 0 )) || bootstrap_die 'Run the manager installer as root'
    while (( $# )); do
        case $1 in
            --version)
                [[ -z $VERSION ]] || bootstrap_die 'Duplicate --version'
                (( $# >= 2 )) || bootstrap_die 'Missing --version tag'
                VERSION=$2
                [[ -n $VERSION ]] || bootstrap_die 'Missing --version tag'
                shift 2;;
            --no-start) NO_START=1; shift;;
            *) bootstrap_die 'Usage: install.sh [--version vX.Y.Z] [--no-start]';;
        esac
    done
    local tool
    for tool in bash curl python3 mktemp rm; do command -v "$tool" >/dev/null || bootstrap_die "Missing dependency: $tool"; done
    python3 -c 'import sys; sys.exit(sys.version_info < (3,11))' || bootstrap_die 'Python 3.11+ required'
    BOOTSTRAP_TMP=$(mktemp -d)
    trap 'rm -rf -- "$BOOTSTRAP_TMP"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM HUP
    resolve_manager_release
    local base="https://raw.githubusercontent.com/$MANAGER_REPO/$MANAGER_COMMIT"
    bootstrap_download "$base/telemt-web-manager.sh" "$BOOTSTRAP_TMP/telemt-web-manager.sh" || bootstrap_die 'Manager shell download failed/empty'
    bootstrap_download "$base/lib/safety.py" "$BOOTSTRAP_TMP/safety.py" || bootstrap_die 'Manager helper download failed/empty'
    validate_manager_pair || bootstrap_die 'Invalid manager Python/Bash syntax'
    commit_manager_pair || bootstrap_die 'Manager installation transaction failed; review the error above'
    printf 'Installed manager %s (%s). Run: telemt-web-manager\n' "$MANAGER_TAG" "$MANAGER_COMMIT"
    rm -rf -- "$BOOTSTRAP_TMP"; BOOTSTRAP_TMP=''
    launch_manager_menu
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then bootstrap_main "$@"; fi
