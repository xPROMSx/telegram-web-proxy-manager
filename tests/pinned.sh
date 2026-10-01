#!/usr/bin/env bash
# Mechanical production/docs/download/staging/runtime version relationship.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
# shellcheck source=telemt-web-manager.sh
source ./telemt-web-manager.sh
[[ $SUPPORTED_TELEMT_VERSION == 3.5.10 ]]
python3 - "$SUPPORTED_TELEMT_VERSION" <<'PY'
from pathlib import Path
import sys
version = sys.argv[1]
for name in ('README.md', 'README.ru.md', 'docs/OPERATIONS.md', 'docs/UPSTREAM.md'):
    assert 'Supported Telemt: **' + version + '**' in Path(name).read_text(), name
print('ok - production supported Telemt == documented supported Telemt == ' + version)
PY
if [[ ${1:-} == --versions ]]; then
    [[ -n ${TELEMT_TEST_EVIDENCE_DIR:-} ]]
    for layer in upstream staging runtime; do
        [[ $(cat "$TELEMT_TEST_EVIDENCE_DIR/$layer.version") == "$SUPPORTED_TELEMT_VERSION" ]]
    done
    printf 'ok - production pin == real downloaded binary == staging healthcheck == real runtime smoke == docs: %s\n' "$SUPPORTED_TELEMT_VERSION"
    exit 0
fi
[[ $# == 0 ]]
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT
curl --proto '=https' --tlsv1.2 -fsS --connect-timeout 10 --max-time 60 --retry 2 \
    "https://api.github.com/repos/telemt/telemt/releases/tags/$SUPPORTED_TELEMT_VERSION" -o "$TMP/release.json"
curl --proto '=https' --tlsv1.2 -fsS --connect-timeout 10 --max-time 60 --retry 2 \
    "https://api.github.com/repos/telemt/telemt/git/ref/tags/$SUPPORTED_TELEMT_VERSION" -o "$TMP/ref.json"
cp "$TMP/ref.json" "$TMP/resolved.json"
for ((depth=0; depth<8; depth++)); do
    [[ $(jq -r '.object.type' "$TMP/resolved.json") == tag ]] || break
    tag_sha=$(jq -r '.object.sha' "$TMP/resolved.json")
    [[ $tag_sha =~ ^[0-9a-f]{40}$ ]]
    curl --proto '=https' --tlsv1.2 -fsS --connect-timeout 10 --max-time 60 --retry 2 \
        "https://api.github.com/repos/telemt/telemt/git/tags/$tag_sha" -o "$TMP/resolved.json"
done
python3 - "$TMP" "$SUPPORTED_TELEMT_VERSION" "$SUPPORTED_TELEMT_COMMIT" "$TELEMT_SHA256_X86_64" "$TELEMT_SHA256_AARCH64" <<'PY'
import json
from pathlib import Path
import sys
root, version, commit, x86, arm = sys.argv[1:]
r = json.loads((Path(root) / 'release.json').read_text())
ref = json.loads((Path(root) / 'ref.json').read_text())
resolved = json.loads((Path(root) / 'resolved.json').read_text())
assert r['tag_name'] == version and not r['draft'] and not r['prerelease']
assert r['target_commitish'] == commit
assert ref['ref'] == 'refs/tags/' + version
assert resolved['object']['type'] == 'commit' and resolved['object']['sha'] == commit
for arch, digest in (('x86_64', x86), ('aarch64', arm)):
    name = 'telemt-' + arch + '-linux-gnu.tar.gz'
    assets = [a for a in r['assets'] if a['name'] == name]
    assert len(assets) == 1
    assert assets[0]['digest'] == 'sha256:' + digest
    assert assets[0]['browser_download_url'] == 'https://github.com/telemt/telemt/releases/download/' + version + '/' + name
    print('ok - official pinned ' + name + ' SHA256 ' + digest)
print('ok - official pinned release/tag commit ' + commit)
PY
