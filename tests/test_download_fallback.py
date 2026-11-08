"""Deterministic Fresh Install GitHub download failure/asset API contract."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_safety import ROOT

# Transport and digest are simulated here; tests/download.sh verifies the real
# pinned SHA256 against actual official archive bytes.
FIXTURE = r'''
set -Eeuo pipefail
source ./telemt-web-manager.sh
TMP="$TEST_ROOT/tmp"
mkdir -p "$TMP"
curl() {
    local arg url=''
    [[ $* == *--proto-redir* && $* == *--tlsv1.2* && $* != *--insecure* ]] || return 98
    for arg in "$@"; do [[ $arg == https://* ]] && url=$arg; done
    printf '%s\n' "$url" >> "$TEST_ROOT/requests"
    if [[ $url == "https://github.com/telemt/telemt/releases/download/3.5.16/telemt-x86_64-linux-gnu.tar.gz" ]]; then
        case $MOCK_MODE in
            direct) printf trusted > "$TMP/asset.tar.gz"; printf 200; return 0;;
            forbidden) printf 403; return 22;;
            *) printf 504; return 22;;
        esac
    fi
    if [[ $url == 'https://api.github.com/repos/telemt/telemt/releases/assets/695266457' ]]; then
        [[ $* == *'Accept: application/octet-stream'* ]] || return 97
        if [[ $MOCK_MODE == both-fail ]]; then printf 504; return 22; fi
        printf trusted > "$TMP/asset.tar.gz"
        return 0
    fi
    return 96
}
sha256sum() {
    [[ $1 == "$TMP/asset.tar.gz" ]] || return 95
    printf '%s  %s\n' "${MOCK_DIGEST:-$TELEMT_SHA256_X86_64}" "$1"
}
timeout() {
    [[ $1 == 60 && $2 == python3 && $4 == extract-binary ]] || return 94
    printf '#!/bin/sh\n' > "$6"
    printf executed > "$TEST_ROOT/extracted"
}
binary_version() { printf '%s\n' "$SUPPORTED_TELEMT_VERSION"; }
download_candidate
'''


class OfficialAssetFallbackTests(unittest.TestCase):
    def exercise(self, mode, digest=None):
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ, TEST_ROOT=temp, MOCK_MODE=mode)
            if digest:
                env['MOCK_DIGEST'] = digest
            p = subprocess.run(['bash', '-c', FIXTURE], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=15)
            trace = Path(temp, 'requests').read_text().splitlines() if Path(temp, 'requests').exists() else []
            extracted = Path(temp, 'extracted').exists()
        return p, trace, extracted

    def test_release_504_recovers_using_exact_official_asset_api(self):
        result, urls, executed = self.exercise('outage')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(urls), 2)
        self.assertTrue(urls[0].startswith('https://github.com/telemt/telemt/releases/download/3.5.16/'))
        self.assertEqual(urls[1], 'https://api.github.com/repos/telemt/telemt/releases/assets/695266457')
        self.assertTrue(executed)

    def test_release_403_does_not_fallback_to_api(self):
        result, urls, executed = self.exercise('forbidden')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(urls), 1)
        self.assertIn('Cannot download Telemt', result.stdout + result.stderr)
        self.assertFalse(executed)

    def test_both_routes_504_report_clear_error_without_execution(self):
        result, urls, executed = self.exercise('both-fail')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(urls), 2)
        self.assertIn('Cannot download Telemt from GitHub Releases', result.stdout + result.stderr)
        self.assertFalse(executed)

    def test_api_fallback_bad_sha_never_executes_binary(self):
        result, urls, executed = self.exercise('outage', 'f' * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(urls), 2)
        self.assertIn('Pinned SHA256 mismatch', result.stdout + result.stderr)
        self.assertFalse(executed)


if __name__ == '__main__':
    unittest.main()
