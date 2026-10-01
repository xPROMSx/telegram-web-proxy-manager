#!/usr/bin/env bash
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
ROOT=$PWD
# shellcheck source=telemt-web-manager.sh
source ./telemt-web-manager.sh
sandbox=$(mktemp -d)
holder=''
finish() { if [[ -n $holder ]]; then kill "$holder" 2>/dev/null || true; fi; rm -rf -- "$sandbox"; }
trap finish EXIT
export ROOT
export LOCK="$sandbox/lock" READY="$sandbox/ready" RELEASE_FIFO="$sandbox/release"
mkfifo "$READY" "$RELEASE_FIFO"
for mode in shared exclusive; do
    rm -f "$LOCK"
    # SC2016: child shell must expand these exported paths.
    # shellcheck disable=SC2016
    timeout 15 bash -c 'lock_path=$LOCK; source "$ROOT/telemt-web-manager.sh"; LOCK=$lock_path; take_lock "$1"; printf ready >"$READY"; read -r _ <"$RELEASE_FIFO"' _ "$mode" &
    holder=$!
    read -r _ <"$READY" || true # writer closes without a newline
    [[ -f $LOCK ]]
    # SC2016: child shell must expand its paths.
    # shellcheck disable=SC2016
    if bash -c 'lock_path=$LOCK; source "$ROOT/telemt-web-manager.sh"; LOCK=$lock_path; take_lock' >"$sandbox/exclusive.log" 2>&1; then exit 1; fi
    if [[ $mode == shared ]]; then
        (take_lock shared)
    else
        if (take_lock shared) >"$sandbox/shared.log" 2>&1; then exit 1; fi
    fi
    printf 'release\n' >"$RELEASE_FIFO"
    wait "$holder"; holder=''
    (take_lock)
done
rm "$LOCK"
touch "$sandbox/target"; ln -s "$sandbox/target" "$LOCK"
if (take_lock shared) >"$sandbox/symlink.log" 2>&1; then exit 1; fi
rm "$LOCK"; mkfifo "$LOCK"
if (take_lock shared) >"$sandbox/fifo.log" 2>&1; then exit 1; fi
rm "$LOCK"; touch "$LOCK"; chmod 0666 "$LOCK"
if (take_lock shared) >"$sandbox/mode.log" 2>&1; then exit 1; fi
chmod 0600 "$LOCK"; ln "$LOCK" "$sandbox/hardlink"
if (take_lock shared) >"$sandbox/hardlink.log" 2>&1; then exit 1; fi
printf 'ok - missing lock creation, shared checks, exclusive mutations and unsafe lock paths\n'
