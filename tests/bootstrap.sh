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
    else command python3 "$@"; fi
}
bootstrap_download() {
    local url=$1 target=$2
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
            printf '{"object":{"type":"commit","sha":"%040d"}}' 1 >"$target";;
        "https://raw.githubusercontent.com/$MANAGER_REPO/0000000000000000000000000000000000000001/telemt-web-manager.sh")
            [[ $fixture_mode != shell-failure ]] || return 1
            if [[ $fixture_mode == shell-empty ]]; then : >"$target";
            elif [[ $fixture_mode == bash-invalid ]]; then printf 'if then\n' >"$target";
            else printf '#!/usr/bin/env bash\n# Telemt WEB Manager. fixture\nprintf "fixture-%s\\n"\n' "$fixture_version" >"$target"; fi
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
python3 - "$ROOT/install.sh" <<'PY'
import os, pathlib, subprocess, sys
# CI has real root privileges. Some cloud containers have an unmapped nobody UID.
try:
 result = subprocess.run(['bash',sys.argv[1],'--no-start'], capture_output=True, preexec_fn=lambda: os.setuid(65534))
except subprocess.SubprocessError:
 if os.environ.get('GITHUB_ACTIONS') == 'true': raise
 print('SKIP - cloud UID mapping prevents non-root subprocess; CI must execute root refusal')
else:
 assert result.returncode and b'Run the manager installer as root' in result.stderr
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
run_bootstrap
grep -q 'Installed manager v0.0.9' "$SANDBOX/bootstrap.log"
printf 'ok - published stable preferred when available\n'
fixture_mode=annotated
run_bootstrap --version v0.1.0
grep -q 'Installed manager v0.1.0' "$SANDBOX/bootstrap.log"
printf 'ok - explicit published version and annotated tag resolve to immutable commit\n'
old=$(pair_hash)
for fixture_mode in shell-failure helper-failure shell-empty helper-empty bash-invalid python-invalid foreign; do
    rejected
    [[ $(pair_hash) == "$old" && $("$LAUNCHER") == fixture-v0.1.0 ]]
    printf 'ok - bootstrap %s refused before installation; previous pair intact\n' "$fixture_mode"
done
fixture_mode=valid
rejected --version '../../foreign'
printf 'ok - arbitrary ref/path input rejected\n'
fixture_version=v0.1.1
run_bootstrap
[[ $("$LAUNCHER") == fixture-v0.1.1 && $(pair_hash) != "$old" ]]
printf 'ok - manager update atomically replaces complete validated pair\n'
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

fixture_fault=0
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
python3 - "$ROOT/install.sh" "$LAUNCHER" <<'PY'
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
