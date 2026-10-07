#!/usr/bin/env bash
# Root-owned temporary paths only; release/network and interactive menu are fixtures.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
ROOT=$PWD
# shellcheck source=install.sh
source ./install.sh
(( EUID == 0 )) || bootstrap_die 'Run bootstrap fixtures as root (sudo bash tests/bootstrap.sh)'
SANDBOX=$(mktemp -d)
trap 'rm -rf -- "$SANDBOX"' EXIT
INSTALL_DIR="$SANDBOX/opt/telemt-web-manager" LAUNCHER="$SANDBOX/bin/telemt-web-manager"
BOOTSTRAP_LOCK="$SANDBOX/lock/telemt-web-manager.lock"
mkdir -p "$SANDBOX/opt" "$SANDBOX/bin" "$SANDBOX/lock" "$SANDBOX/untouched"
for path in telemt.toml nginx.conf certbot.conf xray.json; do printf 'untouched\n' >"$SANDBOX/untouched/$path"; done
untouched=$(sha256sum "$SANDBOX"/untouched/*)
fixture_version=v0.1.0 fixture_mode=valid fixture_fault=0
# Each bootstrap runs in a subshell; fault injection observes its temporary path there.
# shellcheck disable=SC2030,SC2031
python3() {
    if [[ $fixture_fault == 1 && ${2:-} == "$BOOTSTRAP_TMP" && ${3:-} == "$INSTALL_DIR" ]]; then
        { printf 'import os\ndef fail_replace(*args): raise OSError("fixture launcher commit failure")\nos.replace = fail_replace\n'; cat; } | command python3 "$@"
    elif [[ $fixture_fault == 2 && ${2:-} == "$BOOTSTRAP_TMP" && ${3:-} == "$INSTALL_DIR" ]]; then
        # Fail only the reverse exchange after launcher failure. Preserve real
        # forward renameat2, and prove cleanup retains the sole old pair.
        command python3 "$@" < <(cat | sed '/^def interrupted/i\real_swap = swap\nswap_count = 0\ndef swap(a, b):\n    global swap_count\n    swap_count += 1\n    if swap_count == 2: raise OSError("fixture reverse exchange failure")\n    real_swap(a, b)\ndef fail_replace(*args): raise OSError("fixture launcher commit failure")\nos.replace = fail_replace\n')
    else command python3 "$@"; fi
}
bootstrap_repository_metadata() {
    if [[ $1 == "$PRIMARY_MANAGER_REPO" ]]; then printf 404; return; fi
    printf '{"id":1398514078,"full_name":"xPROMSx/telemt-web-manager","name":"telemt-web-manager","html_url":"https://github.com/xPROMSx/telemt-web-manager","owner":{"id":102687702,"login":"xPROMSx"},"private":false,"fork":false,"archived":false,"disabled":false}' >"$2"
    printf 200
}
bootstrap_download() {
    local url=$1 target=$2 downloaded_version=${MANAGER_TAG:-$fixture_version}
    printf '%s\n' "$url" >>"$SANDBOX/requests"
    case $url in
        "https://api.github.com/repos/$MANAGER_REPO/releases"*|"https://api.github.com/repos/$MANAGER_REPO/releases/tags/"*)
            python3 - "$target" "$fixture_version" "$fixture_mode" "$url" <<'PY'
import json, sys
path, tag, mode, url = sys.argv[1:]
def release(t, pre=True, draft=False, date='2026-01-01T00:00:00Z'):
 return dict(tag_name=t, draft=draft, prerelease=pre, published_at=date,
             html_url='https://github.com/xPROMSx/telemt-web-manager/releases/tag/'+t)
value = [release(tag), release('v9.9.9',draft=True,date='2026-12-01T00:00:00Z')]
if mode == 'stable': value += [release('v0.0.9',pre=False)]
if mode == 'foreign': value[0]['html_url'] = 'https://github.com/example/foreign/releases/tag/'+tag
if '/tags/' in url: value = release(url.rsplit('/',1)[1])
if 'page=2' in url: value = []
with open(path,'w') as f: json.dump(value,f)
PY
            ;;
        "https://api.github.com/repos/$MANAGER_REPO/git/ref/tags/"*)
            if [[ $fixture_mode == annotated ]]; then
                printf '{"ref":"refs/tags/%s","object":{"type":"tag","sha":"%040d"}}' "${url##*/}" 2 >"$target"
            else printf '{"ref":"refs/tags/%s","object":{"type":"commit","sha":"%040d"}}' "${url##*/}" 1 >"$target"; fi
            ;;
        "https://api.github.com/repos/$MANAGER_REPO/git/tags/"*)
            printf '{"sha":"%040d","object":{"type":"commit","sha":"%040d"}}' 2 1 >"$target";;
        "https://raw.githubusercontent.com/$MANAGER_REPO/0000000000000000000000000000000000000001/telemt-web-manager.sh")
            [[ $fixture_mode != shell-failure ]] || return 1
            if [[ $fixture_mode == shell-empty ]]; then : >"$target";
            elif [[ $fixture_mode == bash-invalid ]]; then printf 'if then\n' >"$target";
            else
                printf '#!/usr/bin/env bash\n# Telemt WEB Manager. fixture\nset +x\nset -Eeuo pipefail\numask 077\nexport LC_ALL=C\nreadonly SCRIPT_VERSION=%s\nprintf "fixture-%s\\n"\n' "${downloaded_version#v}" "$downloaded_version" >"$target"
                if [[ $fixture_mode == version-mismatch ]]; then sed -i 's/^readonly SCRIPT_VERSION=.*/readonly SCRIPT_VERSION=99.0.0/' "$target"; fi
                if [[ $fixture_mode == unrecognized ]]; then sed -i '2c# unrelated program' "$target"; fi
            fi
            ;;
        "https://raw.githubusercontent.com/$MANAGER_REPO/0000000000000000000000000000000000000001/lib/safety.py")
            [[ $fixture_mode != helper-failure ]] || return 1
            if [[ $fixture_mode == helper-empty ]]; then : >"$target";
            elif [[ $fixture_mode == python-invalid ]]; then printf 'if :\n' >"$target";
            else cp "$ROOT/lib/safety.py" "$target"; fi
            ;;
        *) return 1;;
    esac
}
run_bootstrap() {
    # shellcheck disable=SC2030,SC2031
    (VERSION='' NO_START=0 BOOTSTRAP_TMP=''; bootstrap_main --no-start "$@") >"$SANDBOX/bootstrap.log" 2>&1
}
rejected() {
    if run_bootstrap "$@"; then bootstrap_die "Unexpected bootstrap acceptance: $fixture_mode"; fi
}
pair_hash() { sha256sum "$INSTALL_DIR/telemt-web-manager.sh" "$INSTALL_DIR/lib/safety.py"; }
python3 - "$ROOT/install.sh" "$SANDBOX" <<'PY'
import json, os, signal, subprocess, sys, time
from pathlib import Path
script, root = sys.argv[1:]
root = Path(root)
marker = root / 'download-started'
# The foreground child installs handlers before atomically publishing readiness.
# There is no parent-written marker followed by a still-pending child spawn.
child = """
import json, os, signal, sys
from pathlib import Path
def interrupted(signum, frame):
    sys.exit(128 + signum)
for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(sig, interrupted)
marker = Path(sys.argv[1])
staged = marker.with_suffix('.ready')
staged.write_text(json.dumps(dict(temporary=sys.argv[2], pid=os.getpid(), pgid=os.getpgrp())))
os.replace(staged, marker)
while True:
    signal.pause()
"""
code = ('source "$1"; INSTALL_DIR="$2/opt/signal-fixture"; LAUNCHER="$2/bin/signal-fixture"; '
        'BOOTSTRAP_LOCK="$2/lock/signal-fixture"; '
        'bootstrap_download() { printf "%s" "$BOOTSTRAP_TMP" >"$2"; '
        'command python3 -c "$SIGNAL_CHILD" "$SIGNAL_MARKER" "$BOOTSTRAP_TMP"; }; '
        'bootstrap_repository_metadata() { bootstrap_download "$1" "$2"; }; '
        'SIGNAL_MARKER="$2/download-started"; SIGNAL_CHILD="$3"; '
        'bootstrap_main --no-start')
install = root / 'opt/signal-fixture'
launcher = root / 'bin/signal-fixture'
def snapshot():
    paths = [launcher, install, *install.rglob('*')] if install.exists() else [launcher, install]
    return {str(path): (path.stat().st_mode, path.stat().st_uid, path.stat().st_gid,
                       path.read_bytes() if path.is_file() else None)
            for path in paths if path.exists()}
for sig, expected in ((signal.SIGINT, 130), (signal.SIGTERM, 143), (signal.SIGHUP, 143)):
    longest = 0
    for iteration in range(30):
        # Cover both a fresh install and interrupted update of an existing pair.
        if iteration == 15:
            (install / 'lib').mkdir(parents=True)
            (install / 'telemt-web-manager.sh').write_text('existing manager\n')
            (install / 'lib/safety.py').write_text('existing helper\n')
            launcher.write_text('existing launcher\n')
        before = snapshot()
        marker.unlink(missing_ok=True)
        p = subprocess.Popen(['bash','-c',code,'fixture',script,str(root),child],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            deadline = time.monotonic() + 10
            while not marker.exists():
                if p.poll() is not None: raise AssertionError(p.communicate())
                assert time.monotonic() < deadline, 'blocking child not ready'
                time.sleep(0.001)  # Poll readiness, never delay an already-ready interruption.
            ready = json.loads(marker.read_text())
            temporary = Path(ready['temporary'])
            assert ready['pid'] != p.pid and ready['pgid'] == p.pid
            assert os.getpgid(ready['pid']) == p.pid, 'child must be alive in bootstrap process group'
            started = time.monotonic()
            os.killpg(p.pid, sig)
            stdout, stderr = p.communicate(timeout=10)
            elapsed = time.monotonic() - started
            longest = max(longest, elapsed)
            assert p.returncode == expected, (sig.name, p.returncode, stdout, stderr)
            assert not temporary.exists(), 'bootstrap temporary state survived interruption'
            assert snapshot() == before, 'installation or launcher mutated during download'
            try:
                os.killpg(p.pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError('bootstrap process group still contains an orphan child')
        finally:
            # Also clean descendants if the parent has exited but a failure left its child.
            try: os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            p.communicate(timeout=10)
    print(f'ok - synchronized {sig.name}: 30 interruptions, exit={expected}, '
          f'max exit={longest:.3f}s; temporary cleanup, unchanged fresh/existing pair and launcher, no orphan child')
    # Reset only these fixture paths before the next signal's fresh-install cases.
    if install.exists():
        import shutil
        shutil.rmtree(install)
        launcher.unlink()
print('ok - synchronized bootstrap signal stress: 90 cycles; SIGINT/SIGTERM/SIGHUP; no timeouts or persistent mutation')
PY
python3 - "$ROOT/install.sh" <<'PY'
import os, pathlib, subprocess, sys, tempfile
# CI has real root privileges. Some cloud containers have an unmapped nobody UID.
try:
 # The runner's checkout ancestors may be private to its UID. Root refusal must
 # execute the script, rather than accidentally assert a checkout read failure.
 with tempfile.TemporaryDirectory(prefix='telemt-root-check.') as readable:
  directory = pathlib.Path(readable); directory.chmod(0o755)
  script = directory / 'install.sh'
  script.write_bytes(pathlib.Path(sys.argv[1]).read_bytes()); script.chmod(0o644)
  result = subprocess.run(['bash',str(script),'--no-start'], cwd='/tmp', capture_output=True, preexec_fn=lambda: os.setuid(65534))
except subprocess.SubprocessError:
 if os.environ.get('GITHUB_ACTIONS') == 'true': raise
 print('SKIP - cloud UID mapping prevents non-root subprocess; CI must execute root refusal')
else:
 assert result.returncode and b'Run the manager installer as root' in result.stderr, result.stderr.decode()
 print('ok - bootstrap root requirement enforced before downloads')
PY
run_bootstrap
grep -q 'Installed manager v0.1.0' "$SANDBOX/bootstrap.log"
[[ $("$LAUNCHER") == fixture-v0.1.0 ]]
python3 - "$INSTALL_DIR" "$LAUNCHER" <<'PY'
from pathlib import Path
import sys
root, launcher = map(Path,sys.argv[1:])
for p, mode in ((root,0o755),(root/'lib',0o755),(root/'telemt-web-manager.sh',0o755),(root/'lib/safety.py',0o644),(launcher,0o755)):
 s=p.lstat(); assert s.st_uid==s.st_gid==0 and s.st_mode & 0o7777==mode and not p.is_symlink()
PY
printf 'ok - published prerelease-only manager selected; draft ignored; immutable same-commit pair; root ownership/modes and launcher\n'
old=$(pair_hash)
run_bootstrap
[[ $(pair_hash) == "$old" ]]
printf 'ok - safe bootstrap rerun preserves manager pair\n'
fixture_mode=stable
rejected
grep -q 'automatic downgrade refused' "$SANDBOX/bootstrap.log"
run_bootstrap --version v0.0.9
grep -q 'Installed manager v0.0.9' "$SANDBOX/bootstrap.log"
printf 'ok - automatic stable downgrade refused; explicit published downgrade allowed\n'
fixture_mode=annotated
run_bootstrap --version v0.1.0
grep -q 'Installed manager v0.1.0' "$SANDBOX/bootstrap.log"
printf 'ok - explicit published version and annotated tag resolve to immutable commit\n'
old=$(pair_hash)
for fixture_mode in shell-failure helper-failure shell-empty helper-empty bash-invalid python-invalid foreign version-mismatch unrecognized; do
    rejected
    [[ $(pair_hash) == "$old" && $("$LAUNCHER") == fixture-v0.1.0 ]]
    printf 'ok - bootstrap %s refused before installation; previous pair intact\n' "$fixture_mode"
done
fixture_mode=valid
rejected --version '../../foreign'
rejected --version v0.1.0 --version v0.1.1
rejected --version ''
rejected --version
rejected --unknown
printf 'ok - arbitrary ref/path, duplicate/missing version and unknown options rejected\n'
fixture_version=v0.1.1
run_bootstrap
[[ $("$LAUNCHER") == fixture-v0.1.1 && $(pair_hash) != "$old" ]]
printf 'ok - manager update atomically replaces complete validated pair\n'
old=$(pair_hash)
# The locked guard must leave directory identity, bytes, modes and launcher intact.
identity=$(stat -c '%d:%i' "$INSTALL_DIR")
fixture_version=v0.1.0
rejected
grep -q 'Installed manager 0.1.1; automatically selected v0.1.0; automatic downgrade refused' "$SANDBOX/bootstrap.log"
[[ $(pair_hash) == "$old" && $(stat -c '%d:%i' "$INSTALL_DIR") == "$identity" && $("$LAUNCHER") == fixture-v0.1.1 ]]
printf 'ok - automatic downgrade before persistent installation mutation; installed pair and launcher unchanged\n'
fixture_version=v0.1.1
cp "$INSTALL_DIR/telemt-web-manager.sh" "$SANDBOX/saved-script"
for declaration in missing malformed duplicate ambiguous substitution; do
    python3 - "$INSTALL_DIR/telemt-web-manager.sh" "$SANDBOX/saved-script" "$declaration" "$SANDBOX/executed" <<'PY'
from pathlib import Path
import sys
path, original, mode, marker = sys.argv[1:]
text = Path(original).read_text()
assignment = 'readonly SCRIPT_VERSION=0.1.1'
replacement = {'missing': '', 'malformed': 'readonly SCRIPT_VERSION=01.1.1',
               'duplicate': assignment + '\n' + assignment,
               'ambiguous': 'readonly SCRIPT_VERSION="0.1.1"',
               'substitution': 'readonly SCRIPT_VERSION=$(touch ' + marker + ')'}[mode]
Path(path).write_text(text.replace(assignment, replacement))
PY
    broken=$(pair_hash)
    rejected
    [[ $(pair_hash) == "$broken" && ! -e $SANDBOX/executed && $(stat -c '%d:%i' "$INSTALL_DIR") == "$identity" ]]
    # Even an explicit downgrade must not bypass malformed installed state.
    rejected --version v0.1.0
    [[ $(pair_hash) == "$broken" && ! -e $SANDBOX/executed ]]
    printf 'ok - installed SCRIPT_VERSION %s refused without execution/mutation\n' "$declaration"
done
cp "$SANDBOX/saved-script" "$INSTALL_DIR/telemt-web-manager.sh"
printf '\ntouch "%s"\n' "$SANDBOX/executed" >>"$INSTALL_DIR/telemt-web-manager.sh"
run_bootstrap
[[ ! -e $SANDBOX/executed ]]
printf 'ok - malicious installed script content is never executed during version detection\n'
# A higher-core prerelease still compares above a lower stable candidate.
sed -i 's/^readonly SCRIPT_VERSION=.*/readonly SCRIPT_VERSION=0.2.0-alpha.10/' "$INSTALL_DIR/telemt-web-manager.sh"
rejected
[[ ! -e $SANDBOX/executed ]]
fixture_version=v0.2.0-alpha.2
rejected
grep -q 'automatic downgrade refused' "$SANDBOX/bootstrap.log"
printf 'ok - installed prerelease alpha.10 vs lower alpha.2 automatic candidate refused by SemVer\n'
fixture_version=v0.1.1
cp "$SANDBOX/saved-script" "$INSTALL_DIR/telemt-web-manager.sh"
old=$(pair_hash)
# Inject failure exactly after pair exchange, before creating the launcher.
# No production test hook or environment switch exists in the installer.
rm "$LAUNCHER"
fixture_fault=1
fixture_version=v0.1.2
rejected
[[ $(pair_hash) == "$old" && ! -e $LAUNCHER ]]
# Fresh commit failure must also leave neither installed directory nor launcher.
mv "$INSTALL_DIR" "$SANDBOX/opt/saved-pair"
rejected
[[ ! -e $INSTALL_DIR && ! -e $LAUNCHER ]]
mv "$SANDBOX/opt/saved-pair" "$INSTALL_DIR"

# A failed rollback must retain the previous pair, never delete its stage.
fixture_fault=2
rejected
grep -q 'previous manager pair retained at .*manual recovery required' "$SANDBOX/bootstrap.log"
recovery=$(find "$SANDBOX/opt" -maxdepth 1 -type d -name '.telemt-web-manager.*')
[[ -n $recovery && ! -e $LAUNCHER ]]
[[ $(sha256sum "$recovery/telemt-web-manager.sh" "$recovery/lib/safety.py" | cut -d' ' -f1) == $(printf '%s\n' "$old" | cut -d' ' -f1) ]]
rm -rf -- "$INSTALL_DIR"
mv "$recovery" "$INSTALL_DIR"
fixture_fault=0
printf 'ok - failed reverse exchange retains previous pair for manual recovery\n'
printf 'ok - installer failed-update after directory exchange rolls back complete previous pair; fresh commit failure leaves no installation\n'
fixture_version=v0.1.1
run_bootstrap
# Refuse unrelated destinations, symlinks, unsafe paths and an active manager lock.
printf unrelated >"$INSTALL_DIR/extra"
rejected
rm "$INSTALL_DIR/extra"
printf unrelated >"$LAUNCHER"
rejected
rm "$LAUNCHER"
run_bootstrap
chmod 0644 "$LAUNCHER"
rejected
chmod 0755 "$LAUNCHER"
chmod 0775 "$INSTALL_DIR/lib/safety.py"
rejected
chmod 0644 "$INSTALL_DIR/lib/safety.py"
ln "$INSTALL_DIR/telemt-web-manager.sh" "$SANDBOX/hardlinked-script"
rejected
rm "$SANDBOX/hardlinked-script"
mv "$INSTALL_DIR/telemt-web-manager.sh" "$SANDBOX/symlink-script"
ln -s "$SANDBOX/symlink-script" "$INSTALL_DIR/telemt-web-manager.sh"
rejected
rm "$INSTALL_DIR/telemt-web-manager.sh"
mv "$SANDBOX/symlink-script" "$INSTALL_DIR/telemt-web-manager.sh"
mv "$INSTALL_DIR/lib/safety.py" "$SANDBOX/saved-helper"
ln -s "$SANDBOX/saved-helper" "$INSTALL_DIR/lib/safety.py"
rejected
rm "$INSTALL_DIR/lib/safety.py"
mv "$SANDBOX/saved-helper" "$INSTALL_DIR/lib/safety.py"
mv "$INSTALL_DIR" "$SANDBOX/opt/owned"
ln -s "$SANDBOX/opt/owned" "$INSTALL_DIR"
rejected
rm "$INSTALL_DIR"; mv "$SANDBOX/opt/owned" "$INSTALL_DIR"
ln -s "$SANDBOX/absent" "$SANDBOX/opt/dangling"
(original=$INSTALL_DIR; INSTALL_DIR="$SANDBOX/opt/dangling"; rejected; [[ -L $INSTALL_DIR ]]; INSTALL_DIR=$original)
rm "$SANDBOX/opt/dangling"
exec {fixture_lock}>"$BOOTSTRAP_LOCK"
flock -x "$fixture_lock"
rejected
flock -u "$fixture_lock"
exec {fixture_lock}>&-
printf 'ok - unrelated paths, unsafe modes, symlink/dangling paths and active manager lock refused\n'
[[ $(sha256sum "$SANDBOX"/untouched/*) == "$untouched" ]]
[[ -z $(find "$SANDBOX/opt" "$SANDBOX/bin" -name '.telemt-web-manager.*' -print) ]]
printf 'ok - bootstrap preserves Telemt/Nginx/Certbot/Xray fixtures and cleans transaction stages\n'
# Exercise a real pseudo-terminal; never start the actual manager/menu in CI.
python3 - "$ROOT/install.sh" "${LAUNCHER%/*}/telegram-web-proxy-manager" <<'PY'
import os, pty, select, subprocess, sys
script, launcher = sys.argv[1:]
code = 'source "$1"; LAUNCHER=$2; NO_START=$3; launch_manager_menu'
result = subprocess.run(['bash','-c',code,'fixture',script,launcher,'0'],capture_output=True)
assert result.returncode == 0 and not result.stdout
for suppress in ('0','1'):
 master, slave = pty.openpty()
 p = subprocess.Popen(['bash','-c',code,'fixture',script,launcher,suppress],stdin=slave,stdout=slave,stderr=slave)
 os.close(slave); assert p.wait(timeout=10)==0
 output = b''
 while select.select([master],[],[],0.1)[0]:
  try: block = os.read(master,4096)
  except OSError: break
  if not block: break
  output += block
 os.close(master)
 assert (b'fixture-v0.1.1' in output) == (suppress=='0')
print('ok - interactive launch only with TTY; noninteractive and --no-start do not launch')
PY
