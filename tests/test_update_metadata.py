"""Strict universal release policy. Synthetic API, no executable candidates."""
import copy
import hashlib
import importlib.util
import io
import json
import re
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('update_safety', ROOT / 'lib/safety.py')
s = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = s
spec.loader.exec_module(s)


def release(version='3.5.13', number=1):
    return dict(id=number, tag_name=version, published_at='2026-10-03T17:52:11Z', draft=False,
                prerelease=False, target_commitish='main',
                url=f'https://api.github.com/repos/telemt/telemt/releases/{number}',
                html_url='https://github.com/telemt/telemt/releases/tag/' + version)


class API:
    def __init__(self, records): self.records = records; self.calls = []
    def api(self, suffix):
        self.calls.append(suffix)
        if not suffix: return dict(s.UPSTREAM_REPOSITORY)
        if suffix.startswith('/releases?'):
            page = int(suffix.rsplit('=', 1)[1])
            return copy.deepcopy(self.records[(page-1)*100:page*100])
        raise AssertionError('unexpected endpoint')


class UpdateMetadataTests(unittest.TestCase):
    def test_manager_and_reviewed_baseline_constants_match_shell(self):
        source=(ROOT/'telemt-web-manager.sh').read_text()
        expected={'SCRIPT_VERSION':s.UPDATE_MANAGER_VERSION,'SUPPORTED_TELEMT_VERSION':s.BASELINE_VERSION,
            'SUPPORTED_TELEMT_COMMIT':s.BASELINE_COMMIT,'TELEMT_SHA256_X86_64':s.BASELINE_HASHES['x86_64'][0],
            'TELEMT_SHA256_AARCH64':s.BASELINE_HASHES['aarch64'][0]}
        for name,value in expected.items():
            self.assertEqual(re.findall(r'^readonly '+name+r'=([^\s]+)$',source,re.M),[value])

    def test_frozen_revalidation_endpoints_and_bounded_discovery_count(self):
        selected=release(number=1000); records=[release(f'0.0.{i}',i+1) for i in range(100)]+[selected]
        name='telemt-x86_64-linux-gnu.tar.gz'
        def asset(identifier,suffix):
            filename=name+suffix
            return dict(id=identifier,name=filename,size=97,state='uploaded',digest='sha256:'+'a'*64,
                browser_download_url='https://github.com/telemt/telemt/releases/download/3.5.13/'+filename,
                url=f'https://api.github.com/repos/telemt/telemt/releases/assets/{identifier}')
        responses={'/releases/1000':selected|{'assets':[asset(10,''),asset(11,'.sha256')]},
            '/git/ref/tags/3.5.13':dict(ref='refs/tags/3.5.13',object=dict(type='tag',sha='b'*40)),
            '/git/tags/'+'b'*40:dict(sha='b'*40,tag='3.5.13',object=dict(type='commit',sha='c'*40),
                verification=dict(verified=True,reason='valid',verified_at='2026-10-03T17:52:11Z'))}
        api=API(records); enumerate_api=api.api
        def endpoint(suffix):
            if suffix in responses: api.calls.append(suffix); return copy.deepcopy(responses[suffix])
            return enumerate_api(suffix)
        api.api=endpoint; policy=s.UpdateReleases(api)
        frozen=policy.freeze(policy.latest(),'x86_64')
        policy.recheck(frozen,require_latest=False)  # before download
        policy.recheck(frozen,require_latest=False)  # isolated precheck complete
        policy.recheck(frozen)  # final pre-STOP latest check
        count=len(api.calls); api.records.append(release('4.0.0',2000))
        policy.recheck(frozen,require_latest=False)  # activated transaction ignores new unrelated release
        self.assertEqual(api.calls[count:],list(responses))
        self.assertEqual(len(api.calls),27)
        self.assertEqual(sum(x.startswith('/releases?') for x in api.calls),8)
        with self.assertRaises(ValueError): policy.recheck(frozen)
        for key,mutation in (('/releases/1000',lambda x:x['assets'][0].update(digest='sha256:'+'f'*64)),
                             ('/git/tags/'+'b'*40,lambda x:x['object'].update(sha='f'*40)),
                             ('/git/ref/tags/3.5.13',lambda x:x['object'].update(type='commit'))):
            original=copy.deepcopy(responses[key]); mutation(responses[key]); count=len(api.calls)
            with self.assertRaises(ValueError): policy.recheck(frozen,require_latest=False)
            self.assertFalse(any(x.startswith('/releases?') for x in api.calls[count:]))
            responses[key]=original

    def test_empty_and_exact_pagination_lengths_require_terminal_page(self):
        for count in (0,100,101,200):
            api=API([release(f'0.0.{i}',i+1) for i in range(count)])
            if not count:
                with self.assertRaises(ValueError): s.UpdateReleases(api).latest()
            else:
                self.assertEqual(s.UpdateReleases(api).latest()['version'],f'0.0.{count-1}')
                self.assertEqual(api.calls.count(f'/releases?per_page=100&page={count//100+1}'),2)

    def test_incomplete_rate_limited_and_truncated_history_cannot_select(self):
        class Failure(API):
            def api(self,suffix):
                if suffix.endswith('page=2'): raise ValueError('API page unavailable')
                return super().api(suffix)
        with self.assertRaises(ValueError): s.UpdateReleases(Failure([release(f'0.0.{i}',i+1) for i in range(101)])).latest()
        for bad in ({'message':'rate limit'},None,[release()]*101):
            api=API([]); api.api=lambda suffix:dict(s.UPSTREAM_REPOSITORY) if not suffix else bad
            with self.assertRaises(ValueError): s.UpdateReleases(api).latest()

    def test_full_pagination_twice_and_all_version_series(self):
        records = [release(f'0.0.{i}', i+1) for i in range(199)] + [release('4.0.0', 201)]
        api = API(records)
        self.assertEqual(s.UpdateReleases(api).latest()['version'], '4.0.0')
        self.assertEqual(api.calls.count('/releases?per_page=100&page=3'), 2)

    def test_quarantine_exact_historical_identities_only(self):
        old = [dict(release(tag, number), published_at=published)
               for number, (tag, published) in s.LEGACY_RELEASES.items()]
        self.assertEqual(s.UpdateReleases(API(old + [release()])).latest()['version'], '3.5.13')
        for key in ('id', 'tag_name', 'published_at', 'html_url', 'url'):
            records = copy.deepcopy(old)
            records[0][key] = 999 if key == 'id' else str(records[0][key]) + 'changed'
            with self.subTest(key=key), self.assertRaises((ValueError, KeyError)):
                s.UpdateReleases(API(records + [release()])).latest()

    def test_unknown_malformed_stable_fails(self):
        for version in ('9.0.0.1', '1.02.3', '1.2', '3.5.13+custom', 'release-4.0.0', '4.0.0\n','9'*129+'.0.0'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                s.UpdateReleases(API([release(version)])).latest()

    def test_draft_and_mislabeled_prerelease_never_selected(self):
        records = [release(), dict(release('10.0.0', 2), draft=True, published_at=None),
                   release('11.0.0-rc.1', 3), dict(release('12.0.0', 4), prerelease=True)]
        self.assertEqual(s.UpdateReleases(API(records)).latest()['version'], '3.5.13')

    def test_equal_precedence_tags_and_duplicate_ids_fail(self):
        for second in (release('v3.5.13', 2), release('3.5.14', 1), release('3.5.13', 3)):
            with self.assertRaises(ValueError): s.UpdateReleases(API([release(), second])).latest()

    def test_repository_identity_and_inventory_drift_fail(self):
        api = API([release()]); original = api.api
        api.api = lambda suffix: dict(s.UPSTREAM_REPOSITORY, id=123) if not suffix else original(suffix)
        with self.assertRaises(ValueError): s.UpdateReleases(api).latest()
        class Drift(API):
            def api(self, suffix):
                if not suffix and self.calls: self.records = [release('3.5.14')]
                return super().api(suffix)
        with self.assertRaises(ValueError): s.UpdateReleases(Drift([release()])).latest()

    def test_duplicate_json_keys_and_nonfinite_numbers_fail(self):
        for raw in (b'{"id":1,"id":2}', b'{"size":NaN}', b'{"id":Infinity}'):
            with self.assertRaises(ValueError): s.update_json(raw)

    def test_signed_annotated_tag_and_exact_assets_required(self):
        record = s.UpdateReleases.release(release()) | {'version':'3.5.13'}
        asset_name = 'telemt-x86_64-linux-gnu.tar.gz'
        def asset(number, suffix=''):
            name = asset_name + suffix
            return dict(id=number, name=name, size=97 if suffix else 100, state='uploaded',
                        digest='sha256:' + 'a'*64,
                        browser_download_url='https://github.com/telemt/telemt/releases/download/3.5.13/' + name,
                        url=f'https://api.github.com/repos/telemt/telemt/releases/assets/{number}')
        responses = {
            '/releases/1': release() | {'assets':[asset(10), asset(11, '.sha256')]},
            '/git/ref/tags/3.5.13': dict(ref='refs/tags/3.5.13', object=dict(type='tag', sha='b'*40)),
            '/git/tags/' + 'b'*40: dict(sha='b'*40, tag='3.5.13', object=dict(type='commit', sha='c'*40),
                                     verification=dict(verified=True, reason='valid', verified_at='2026-10-03T17:52:11Z'))}
        api = API([]); api.api = lambda suffix: copy.deepcopy(responses[suffix])
        policy = s.UpdateReleases(api)
        self.assertEqual(policy.freeze(record,'x86_64')['commit_sha'], 'c'*40)
        mutations = [('/git/ref/tags/3.5.13', lambda r: r['object'].update(type='commit')),
            ('/git/tags/'+'b'*40, lambda r: r['verification'].update(verified=False)),
            ('/git/tags/'+'b'*40, lambda r: r.update(tag='3.5.14')),
            ('/git/tags/'+'b'*40, lambda r: r['object'].update(type='tag')),
            ('/releases/1', lambda r: r.update(target_commitish='d'*40)),
            ('/releases/1', lambda r: r['assets'].append(r['assets'][0])),
            ('/releases/1', lambda r: r['assets'].pop()),
            ('/releases/1', lambda r: r['assets'][0].update(digest=None)),
            ('/releases/1', lambda r: r['assets'][0].update(size=128*1024*1024+1)),
            ('/releases/1', lambda r: r['assets'][0].update(browser_download_url='https://foreign.example/file'))]
        for endpoint, mutate in mutations:
            original = copy.deepcopy(responses[endpoint]); mutate(responses[endpoint])
            with self.assertRaises(ValueError): policy.freeze(record, 'x86_64')
            responses[endpoint] = original

    def test_both_arches_actual_checksum_archive_extraction_and_receipt_agree(self):
        for arch in ('x86_64','aarch64'):
            for bad in (None,'checksum-entry','checksum-digest','archive-digest'):
                with self.subTest(arch=arch,bad=bad),tempfile.TemporaryDirectory() as temporary:
                    directory=Path(temporary); archive=io.BytesIO()
                    with tarfile.open(fileobj=archive,mode='w:gz') as tar:
                        entry=tarfile.TarInfo('telemt'); body=b'fixture ELF identity bytes'; entry.size=len(body)
                        tar.addfile(entry,io.BytesIO(body))
                    payload=archive.getvalue(); name='telemt-'+arch+'-linux-gnu.tar.gz'
                    digest=hashlib.sha256(payload).hexdigest()
                    checksum=(digest+'  '+name+'\n').encode()
                    base='https://github.com/telemt/telemt/releases/download/3.5.13/'
                    def asset(identifier,filename,raw):
                        return dict(id=identifier,name=filename,size=len(raw),state='uploaded',digest='sha256:'+hashlib.sha256(raw).hexdigest(),
                            browser_download_url=base+filename,url=f'https://api.github.com/repos/telemt/telemt/releases/assets/{identifier}')
                    assets=[asset(10,name,payload),asset(11,name+'.sha256',checksum)]
                    if bad=='checksum-entry':
                        checksum=(digest+'  foreign.tar.gz\n').encode(); assets[1]=asset(11,name+'.sha256',checksum)
                    if bad=='checksum-digest': assets[1]['digest']='sha256:'+'0'*64
                    if bad=='archive-digest': assets[0]['digest']='sha256:'+'0'*64
                    responses={'/releases/1':release()|{'assets':assets},
                        '/git/ref/tags/3.5.13':dict(ref='refs/tags/3.5.13',object=dict(type='tag',sha='b'*40)),
                        '/git/tags/'+'b'*40:dict(sha='b'*40,tag='3.5.13',object=dict(type='commit',sha='c'*40),
                            verification=dict(verified=True,reason='valid',verified_at='2026-10-03T17:52:11Z'))}
                    class Transport(s.UpdateHTTP):
                        def api(self,suffix): return copy.deepcopy(responses[suffix])
                        @staticmethod
                        def open(request):
                            result=io.BytesIO(checksum if request.full_url.endswith('.sha256') else payload)
                            result.url=request.full_url; return result
                    policy=s.UpdateReleases(Transport()); frozen=policy.freeze(s.UpdateReleases.release(release())|{'version':'3.5.13'},arch)
                    if bad:
                        with self.assertRaises(ValueError): policy.download(frozen,directory)
                        self.assertFalse((directory/'candidate').exists())
                    else:
                        binary=policy.download(frozen,directory)
                        receipt=s.UpdateReceipt.create(binary,'1'*32,'2'*32,frozen=frozen,arch=arch)
                        self.assertEqual(receipt['architecture'],arch); self.assertEqual(binary.read_bytes(),body)
                        self.assertEqual(receipt['archive_sha256'],digest)

    def test_release_tag_archive_checksum_disappear_or_change_fail_recheck(self):
        record=s.UpdateReleases.release(release())|{'version':'3.5.13'}
        # Recheck must compare the entire frozen tuple, even after downtime
        # when discovery may contain an unrelated newer stable release.
        frozen={'release':record,'architecture':'x86_64','installed_version':'3.5.13','identity':'original'}
        for identity in ('changed-tag','replaced-archive','replaced-checksum','disappeared'):
            policy=s.UpdateReleases(API([])); policy.latest=lambda:record
            policy.freeze=lambda release,arch:dict(frozen,identity=identity)
            with self.assertRaises(ValueError): policy.recheck(frozen,require_latest=False)
        policy.latest=lambda:dict(record,id=2,version='4.0.0')
        policy.freeze=lambda release,arch:frozen
        with self.assertRaises(ValueError): policy.recheck(frozen)
        policy.recheck(frozen,require_latest=False)


if __name__ == '__main__': unittest.main()
