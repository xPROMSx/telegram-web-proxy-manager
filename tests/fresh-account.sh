#!/usr/bin/env bash
# Real account lifecycle on the disposable Actions runner; no service or host config.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
(( EUID == 0 )) || { printf 'root-only account fixture; execute intact in Actions\n' >&2; exit 1; }
if getent passwd telemt >/dev/null || getent group telemt >/dev/null; then
    printf 'refusing preexisting telemt account/group\n' >&2; exit 1
fi
fixture=$(mktemp -d)
# On failure preserve the ledger and owned paths for runner log diagnostics.
trap 'printf "account fixture evidence: %s\n" "$fixture"' EXIT
ledger="$fixture/fresh-ownership.json"
config="$fixture/config" data="$fixture/data" state="$fixture/state"
python3 lib/safety.py fresh-init "$ledger" "$config" "$data" "$state"
python3 lib/safety.py fresh-account-create "$ledger" "$data"
for directory in "$config" "$data" "$data/public" "$data/state" "$state"; do
    mode=0750; if [[ $directory == "$state" ]]; then mode=0700; fi
    python3 lib/safety.py fresh-mkdir "$ledger" "$directory" "$mode"
    [[ $(stat -c %a "$directory") == "${mode#0}" ]]
done
chown telemt:telemt "$data/state"
mkdir "$data/state/runtime"
printf cache >"$data/state/runtime/cache"
printf keep >"$fixture/unrelated"
ln -s "$fixture/unrelated" "$data/state/symlink"
python3 lib/safety.py fresh-cleanup-dirs "$ledger" "$config" "$data" "$state"
python3 lib/safety.py fresh-cleanup-account "$ledger" "$config" "$data" "$state"
[[ ! -e $config && ! -e $data && ! -e $state && $(cat "$fixture/unrelated") == keep ]]
if getent passwd telemt >/dev/null || getent group telemt >/dev/null; then exit 1; fi
printf 'ok - REAL root fresh account UID/GID, writable runtime state, no-follow cleanup and user/private-group removal\n'
rm -rf -- "$fixture"
trap - EXIT
