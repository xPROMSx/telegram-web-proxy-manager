"""Bounded manager-owned covers, anchored publication and existing DATA Update."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_safety import s

ROOT = Path(__file__).resolve().parents[1]


class CoverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.public = self.root/'public'
        self.public.mkdir(0o750); self.path = self.public/'index.html'

    def test_embedded_exact_asset_manifest_and_local_html(self):
        assets = s.cover_assets()
        manifest = json.loads((ROOT/'assets/fake-sites/manifest.json').read_text())
        self.assertEqual(manifest,dict(schema=1,stylesheet={k:v for k,v in s.COVER_STYLESHEET.items() if k != 'css'},sites=[{k:v for k,v in item.items() if k != 'html'}
                                                      for item in s.COVER_BUNDLE['sites']]))
        for site, raw in assets.items():
            self.assertEqual(raw,(ROOT/'assets/fake-sites'/f'{site}.html').read_bytes())
        self.assertEqual(s.cover_stylesheet(),(ROOT/'assets/fake-sites/cover.css').read_bytes())
        for raw in [s.SERVICE_STATUS,*assets.values()]:
            self.assertNotIn(b'<style',raw.lower())
            self.assertEqual(raw.count(b'<link rel="stylesheet" href="/cover.css">'),1)
        self.assertIn(b'All systems operational',s.SERVICE_STATUS)
        self.assertNotIn(b'Telemt',s.SERVICE_STATUS)
        parser = s.CoverHTML(); parser.feed(s.SERVICE_STATUS.decode()); parser.close()

    def test_manifest_traversal_size_hash_and_html_refused(self):
        for defect in ('id','size','hash','extra','empty','count','schema'):
            bundle = copy.deepcopy(s.COVER_BUNDLE)
            if defect == 'id': bundle['sites'][0]['id'] = '../foreign'
            elif defect == 'size': bundle['sites'][0]['size'] = s.COVER_LIMIT+1
            elif defect == 'hash': bundle['sites'][0]['sha256'] = '0'*64
            elif defect == 'extra': bundle['foreign'] = True
            elif defect == 'empty': bundle['sites'] = []
            elif defect == 'count': bundle['sites'] *= 3
            else: bundle['schema'] = True
            with self.subTest(defect=defect),self.assertRaises(ValueError): s.cover_assets(bundle)
        for html in ('<script>alert(1)</script>','<iframe></iframe>','<form></form>',
                     '<link rel="stylesheet" href="https://foreign/x.css">',
                     '<link rel="stylesheet" href="/other.css">',
                     '<a href="/cover.css">x</a>', '<style>body{color:red}</style>',
                     '<img src="https://remote.example/x">','<style>@import "x";</style>',
                     '<style>a{background:url(x)}</style>',
                     '<meta http-equiv="refresh" content="0;url=x">','<div onclick="x"></div>'):
            raw = html.encode(); bundle = dict(schema=1,sites=[dict(id='site-01',html=html,
                size=len(raw),sha256=hashlib.sha256(raw).hexdigest())])
            with self.subTest(html=html),self.assertRaises(ValueError): s.cover_assets(bundle)

    def test_initial_random_and_corrupt_bundle_fallback(self):
        s.cover_initial(self.public)
        self.assertIn(self.path.read_bytes(),s.cover_assets().values())
        self.assertEqual(self.path.stat().st_mode & 0o777,0o440)
        self.assertEqual(self.path.stat().st_gid,self.public.stat().st_gid)
        final = self.root/'final'; final.mkdir(0o750)
        s.cover_initial(final,str(self.path))
        self.assertEqual((final/'index.html').read_bytes(),self.path.read_bytes())
        self.path.unlink(); (self.public/'cover.css').unlink()
        with patch.object(s,'COVER_BUNDLE',dict(schema=99,sites=[])): s.cover_initial(self.public)
        self.assertEqual(self.path.read_bytes(),s.SERVICE_STATUS)
        self.assertEqual(set(self.public.iterdir()),{self.path,self.public/'cover.css'})

    def test_stylesheet_integrity_and_resource_safety(self):
        for defect in ('size','hash','url','import','external','script'):
            item = copy.deepcopy(s.COVER_STYLESHEET)
            if defect == 'size': item['size'] += 1
            elif defect == 'hash': item['sha256'] = '0'*64
            else:
                item['css'] += dict(url='a{background:url(x)}',import_='@import "x";',
                                    external='https://example.com',script='<script>x</script>')[
                                        'import_' if defect == 'import' else defect]
                raw = item['css'].encode(); item.update(size=len(raw),sha256=hashlib.sha256(raw).hexdigest())
            with self.subTest(defect=defect),patch.object(s,'COVER_STYLESHEET',item),self.assertRaises(ValueError):
                s.cover_stylesheet()

    def test_initial_compatibility_staging_has_both_files(self):
        script = 'source "$1"; TMP=$2; prepare_compatibility_data "$TMP/compat-data"'
        subprocess.run(['bash','-c',script,'fixture',str(ROOT/'telemt-web-manager.sh'),str(self.root)],check=True)
        public = self.root/'compat-data/public'
        s.cover_stylesheet_check(public)
        self.assertIn((public/'index.html').read_bytes(),s.cover_assets().values())
        for filename in ('index.html','cover.css'):
            info = (public/filename).stat()
            self.assertEqual(info.st_uid,0); self.assertEqual(info.st_gid,public.stat().st_gid)
            self.assertEqual(info.st_mode & 0o777,0o440)

    def test_random_never_current_and_atomic_post_write_failure_restores(self):
        # Root metadata contract is also the workflow's existing unit-test contract.
        self.assertEqual(os.geteuid(),0)
        old = next(iter(s.cover_assets().values())); s.cover_atomic(self.public,old,initial=True)
        for _ in range(10): self.assertNotEqual(s.cover_choose(old),old)
        read = os.read
        def corrupt_read(fd,length):
            raw = read(fd,length)
            return b'corrupt' if raw == s.SERVICE_STATUS else raw
        with patch.object(s.os,'read',side_effect=corrupt_read),self.assertRaises(ValueError):
            s.cover_atomic(self.public,s.SERVICE_STATUS)
        self.assertEqual(self.path.read_bytes(),old)
        self.assertEqual(list(self.public.iterdir()),[self.path])
        s.cover_atomic(self.public,s.SERVICE_STATUS)
        self.assertEqual(self.path.read_bytes(),s.SERVICE_STATUS)

    def test_symlink_hardlink_mode_and_unsafe_ancestor_refused(self):
        self.assertEqual(os.geteuid(),0)
        old = s.SERVICE_STATUS; s.cover_atomic(self.public,old,initial=True)
        self.path.chmod(0o644)
        with self.assertRaises(ValueError): s.cover_atomic(self.public,old)
        self.path.chmod(0o440); os.chown(self.path,65534,65534)
        with self.assertRaises(ValueError): s.cover_atomic(self.public,old)
        os.chown(self.path,0,self.public.stat().st_gid)
        alias = self.root/'alias'; os.link(self.path,alias)
        with self.assertRaises(ValueError): s.cover_atomic(self.public,old)
        alias.unlink(); self.path.rename(alias); self.path.symlink_to(alias)
        with self.assertRaises(ValueError): s.cover_atomic(self.public,old)
        self.path.unlink(); alias.rename(self.path); self.public.chmod(0o777)
        with self.assertRaises(ValueError): s.cover_atomic(self.public,old)
        self.public.chmod(0o750)
        self.assertEqual(self.path.read_bytes(),old)

    def test_managed_change_restore_and_unknown_current_fail_closed(self):
        self.assertEqual(os.geteuid(),0)
        state = self.root/'manager'; state.mkdir(0o700)
        config = self.root/'telemt.toml'; host = 'proxy.example.com'; secret = 'a'*32
        raw = subprocess.check_output(['bash','-c','source "$1"; DOMAIN=$2 PUBLIC_IP=203.0.113.10; generate_config "$3" "$4"',
            'fixture',str(ROOT/'telemt-web-manager.sh'),host,secret,str(self.root)])
        config.write_bytes(raw); config.chmod(0o640)
        s.update_write_json(state/'manifest.json',dict(schema=1,domain=host,unit_sha256='a'*64,nginx_sha256='b'*64))
        s.update_write(state/'web-link.txt',f'tg://webproxy?server={host}&secret=dd{secret}\n'.encode())
        os.chown(self.public,0,1234)
        s.cover_atomic(self.public,s.cover_stylesheet(),initial=True,filename='cover.css')
        s.cover_atomic(self.public,s.SERVICE_STATUS,initial=True)
        controls = {p:p.read_bytes() for p in (config,self.public/'cover.css',*state.iterdir())}
        previous = self.root/'previous'
        with patch.object(s,'fresh_identity',return_value=dict(group=['telemt','x','1234',''])):
            s.cover_change(str(state),str(config),str(self.root),'random',str(previous))
            new = self.path.read_bytes(); self.assertIn(new,s.cover_assets().values())
            css = self.public/'cover.css'; expected = css.read_bytes(); index = self.path.read_bytes()
            for defect in ('missing','modified','symlink','mode','owner','group','hardlink'):
                previous.unlink()
                if defect == 'missing': css.unlink()
                elif defect == 'modified': css.write_bytes(b'changed')
                elif defect == 'symlink': css.unlink(); css.symlink_to(self.path)
                elif defect == 'mode': css.chmod(0o644)
                elif defect == 'owner': os.chown(css,65534,1234)
                elif defect == 'group': os.chown(css,0,0)
                else: os.link(css,self.root/'css-alias')
                with self.subTest(defect=defect),self.assertRaises(ValueError):
                    s.cover_change(str(state),str(config),str(self.root),'default',str(previous))
                self.assertEqual(self.path.read_bytes(),index); self.assertFalse(previous.exists())
                if (self.root/'css-alias').exists(): (self.root/'css-alias').unlink()
                css.unlink(missing_ok=True)
                s.cover_atomic(self.public,expected,initial=True,filename='cover.css')
                s.update_write(previous,s.SERVICE_STATUS)
            s.cover_change(str(state),str(config),str(self.root),'restore',str(previous))
            self.assertEqual(self.path.read_bytes(),s.SERVICE_STATUS)
            previous.unlink()
            s.cover_change(str(state),str(config),str(self.root),'default',str(previous))
            self.assertEqual(self.path.read_bytes(),s.SERVICE_STATUS)
            previous.unlink(); self.path.write_bytes(b'manually managed site')
            with self.assertRaisesRegex(ValueError,'Unknown current cover'):
                s.cover_change(str(state),str(config),str(self.root),'random',str(previous))
            self.assertFalse(previous.exists())
        self.assertEqual({p:p.read_bytes() for p in controls},controls)

    def test_shell_cover_restart_and_failed_activation_restore(self):
        for fail in (False,True):
            script = '''source "$1"
load_installation() { :; }
helper() { printf 'helper:%s\\n' "$5"; }
now() { printf 1; }
restart_service() { printf restart; }
wait_ready() { :; }
path_health() { [[ ! -f "$2" ]]; }
recent_logs() { :; }
'''
            # All assertions are on lifecycle events, with no candidate or host mutation.
            script = script.replace('path_health() { [[ ! -f "$2" ]]; }',
                                    'path_health() { '+('return 1;' if fail else 'return 0;')+' }')
            script += 'change_cover_site'
            result = subprocess.run(['bash','-c',script,'fixture',str(ROOT/'telemt-web-manager.sh')],
                                    input=b'1\n',capture_output=True)
            self.assertIn(b'helper:random',result.stdout)
            self.assertEqual(result.stdout.count(b'restart'),2 if fail else 1)
            self.assertEqual(b'helper:restore' in result.stdout,fail)
            self.assertEqual(result.returncode == 0,not fail)

    def test_covers_survive_existing_full_data_transaction(self):
        spec = importlib.util.spec_from_file_location('cover_transaction',ROOT/'tests/update_transactions.py')
        fixture = importlib.util.module_from_spec(spec); sys.modules[spec.name] = fixture; spec.loader.exec_module(fixture)
        for raw in (s.SERVICE_STATUS,*s.cover_assets().values()):
            f = fixture.Fixture()
            try:
                path = f.layout.data/'public/index.html'; path.write_bytes(raw)
                css = f.layout.data/'public/cover.css'; css.write_bytes(s.cover_stylesheet()); css.chmod(0o440)
                before = hashlib.sha256(raw).digest()
                f.engine.update()
                self.assertEqual(hashlib.sha256(path.read_bytes()).digest(),before)
                self.assertEqual(css.read_bytes(),s.cover_stylesheet())
                self.assertEqual(css.stat().st_mode & 0o777,0o440)
                self.assertEqual(path.stat().st_mode & 0o777,0o440)
            finally: f.close()


if __name__ == '__main__': unittest.main()
