#!/usr/bin/env python3
"""Verify historical 3.5.12/3.5.13 and current Fresh GNU artifacts.
Artifacts are private outside the checkout. No candidate executes in this step.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import urllib.parse

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('provenance_safety',ROOT/'lib/safety.py')
s=importlib.util.module_from_spec(spec); sys.modules[spec.name]=s; spec.loader.exec_module(s)
EXPECT={'x86_64':'92021ad31520302bfbfe4a13b49adc9d129ec48a08699f81515e9c55668be9fa',
        'aarch64':'9aec3a87e730c6dc0d1baaffcdde3dde9bada1e892c6b96195c0740919f3de52'}
class ActionsHTTP(s.UpdateHTTP):
    @staticmethod
    def open(request):
        token=os.environ.get('TELEMT_TEST_GITHUB_TOKEN')
        if token and urllib.parse.urlsplit(request.full_url).hostname=='api.github.com':
            # Initial API request only: urllib never copies unredirected headers
            # into a redirect. Downloads and candidate execution receive no token.
            request.add_unredirected_header('Authorization','Bearer '+token)
        return s.UpdateHTTP.open(request)


root=Path(sys.argv[1]); root.mkdir(mode=0o700,parents=True,exist_ok=True)
policy=s.UpdateReleases(ActionsHTTP()); inventory=policy.latest()
print('Official stable inventory (double full pagination): '+inventory['version'],flush=True)
raw=policy.http.api('/releases/402625235'); record=s.UpdateReleases.release(raw)|{'version':'3.5.13'}
for arch,digest in EXPECT.items():
    directory=root/arch; directory.mkdir(mode=0o700)
    frozen=policy.freeze(record,arch)
    assert frozen['commit_sha']=='d3de9865cf5d088809fdf728059bcb2b0841db67'
    assert frozen['asset']['sha256']==digest
    policy.recheck(frozen,require_latest=False)
    binary=policy.download(frozen,directory)
    receipt=s.UpdateReceipt.create(binary,'1'*32,'2'*32,frozen=frozen,arch=arch)
    s.update_write_json(directory/'frozen.json',frozen); s.update_write_json(directory/'receipt.json',receipt)
    print(f'Official 3.5.13 {arch}: verified signed annotated tag {frozen["tag_object_sha"]} -> {frozen["commit_sha"]}',flush=True)
    print(f'Official {arch} archive SHA256: {digest}; extracted binary: {receipt["binary"]["sha256"]} size={receipt["binary"]["size"]}; schema-1 receipt OK',flush=True)
print('REAL provenance/download: both architectures; candidate execution deferred to isolation',flush=True)
# Independently fetch the immutable fresh-Install baseline through the same
# verified official provenance path. Boot/fresh-generation fixtures use its
# exact ELF, never a synthetic file blessed by an overridden production hash.
baseline=s.UpdateReleases.release(policy.http.api('/releases/tags/3.5.12'))|{'version':'3.5.12'}
directory=root/'baseline-provenance'; directory.mkdir(mode=0o700)
frozen=policy.freeze(baseline,'x86_64')
legacy_commit,legacy_pins=s.REVIEWED_BASELINES['3.5.12']
assert frozen['commit_sha']==legacy_commit and frozen['asset']['sha256']==legacy_pins['x86_64'][0]
policy.recheck(frozen,require_latest=False)
binary=policy.download(frozen,directory)
assert s.update_hash(binary)['sha256']==legacy_pins['x86_64'][1]
s.update_copy_stream(binary,root/'baseline',0o755)
print('REAL reviewed 3.5.12 baseline: signed tag, pinned archive SHA256 and exact embedded ELF identity verified',flush=True)

# Current Fresh Install artifacts are separate from the historical 3.5.12 ->
# 3.5.13 update rehearsal, so raising the Fresh pin cannot turn it into downgrade.
fresh=s.UpdateReleases.release(policy.http.api('/releases/tags/'+s.BASELINE_VERSION))|{'version':s.BASELINE_VERSION}
for arch in ('x86_64','aarch64'):
    directory=root/('fresh-'+arch); directory.mkdir(mode=0o700)
    frozen=policy.freeze(fresh,arch)
    assert frozen['commit_sha']==s.BASELINE_COMMIT
    assert frozen['tag_object_sha']=='210883304cae6a9aed583631634081087baaa4da'
    assert frozen['asset']['sha256']==s.BASELINE_HASHES[arch][0]
    policy.recheck(frozen,require_latest=False)
    binary=policy.download(frozen,directory)
    assert s.update_hash(binary)['sha256']==s.BASELINE_HASHES[arch][1]
    receipt=s.UpdateReceipt.create(binary,'3'*32,'4'*32,arch=arch)
    assert receipt['installed_version']==s.BASELINE_VERSION and receipt['origin']=='reviewed-baseline'
    s.update_write_json(directory/'frozen.json',frozen)
    s.update_write_json(directory/'receipt.json',receipt)
    print('REAL Fresh '+s.BASELINE_VERSION+' '+arch+': signed tag, archive/checksum and ELF pins; reviewed receipt verified',flush=True)

# Reuse the existing root bootstrap barrier fixture with actual verified ELFs.
sys.path.insert(0,str(ROOT/'tests'))
from update_bootstrap import verify_reviewed_bootstrap
verify_reviewed_bootstrap(root)
