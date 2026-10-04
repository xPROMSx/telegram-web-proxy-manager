#!/usr/bin/env python3
"""Real official 3.5.13 metadata/download/extraction and both GNU architectures.
Artifacts are private outside the checkout. No candidate executes in this step.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('provenance_safety',ROOT/'lib/safety.py')
s=importlib.util.module_from_spec(spec); sys.modules[spec.name]=s; spec.loader.exec_module(s)
EXPECT={'x86_64':'92021ad31520302bfbfe4a13b49adc9d129ec48a08699f81515e9c55668be9fa',
        'aarch64':'9aec3a87e730c6dc0d1baaffcdde3dde9bada1e892c6b96195c0740919f3de52'}
root=Path(sys.argv[1]); root.mkdir(mode=0o700,parents=True,exist_ok=True)
policy=s.UpdateReleases(); inventory=policy.latest()
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
assert frozen['commit_sha']==s.BASELINE_COMMIT and frozen['asset']['sha256']==s.BASELINE_HASHES['x86_64'][0]
policy.recheck(frozen,require_latest=False)
binary=policy.download(frozen,directory)
assert s.update_hash(binary)['sha256']==s.BASELINE_HASHES['x86_64'][1]
s.update_copy_stream(binary,root/'baseline',0o755)
print('REAL reviewed 3.5.12 baseline: signed tag, pinned archive SHA256 and exact embedded ELF identity verified',flush=True)
