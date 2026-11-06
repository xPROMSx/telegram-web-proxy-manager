"""Approved site resources and the exact new/legacy WEB deployment contracts."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from test_safety import ROOT, s


class SiteV03Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def config(self):
        result=subprocess.run(['bash','-c',
            'source ./telemt-web-manager.sh; DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10 DATA=/var/lib/telemt; generate_config 00000000000000000000000000000000'],
            cwd=ROOT,capture_output=True,check=True)
        return s.tomllib.loads(result.stdout.decode())

    def test_native_http_origin_is_an_exact_managed_contract(self):
        config=self.config()
        config['web']['vhosts'][0]['decoy']={'mode':'http_upstream','upstream':'http://127.0.0.1:18081'}
        self.assertEqual(s.managed_web_contract(config,'/var/lib/telemt'),
                         ('proxy.example.com','direct','203.0.113.10'))
        for upstream in ('http://0.0.0.0:18081','http://127.0.0.1:18082','https://127.0.0.1:18081',
                         'http://foreign.example/','http://127.0.0.1:18081/path'):
            bad=copy.deepcopy(config); bad['web']['vhosts'][0]['decoy']['upstream']=upstream
            with self.subTest(upstream=upstream),self.assertRaises(ValueError):
                s.managed_web_contract(bad,'/var/lib/telemt')

    def test_embedded_resources_are_verbatim_and_fail_before_generation_if_corrupt(self):
        values=s.site_resources()
        self.assertEqual(set(values),s.SITE_SOURCE_FILES)
        for name,source in values.items():
            self.assertEqual(source.encode(),(ROOT/'assets/cover-sites-v0.3'/name).read_bytes())
        with patch.object(s,'SITE_SOURCE_B85','broken'):
            with self.assertRaises(ValueError): s.site_generate(self.root/'bad')
        self.assertFalse((self.root/'bad').exists())

    def test_verbatim_generator_output_for_all_three_designs(self):
        path=ROOT/'assets/cover-sites-v0.3/generate.py'
        spec=importlib.util.spec_from_file_location('approved_v03_reference',path)
        approved=importlib.util.module_from_spec(spec); spec.loader.exec_module(approved)
        for theme in s.SITE_FILES:
            for last in (False,True):
                source=self.root/f'{theme}-{last}-source'; actual=self.root/f'{theme}-{last}-actual'
                with patch('secrets.choice',side_effect=lambda values:values[-1] if last else values[0]), \
                     patch('secrets.randbelow',side_effect=lambda n:n-1 if last else 0):
                    approved.generate(source,theme)
                    digest=s.site_generate(actual,theme)
                self.assertEqual({p.name:p.read_bytes() for p in source.iterdir()},
                                 {p.name:p.read_bytes() for p in actual.iterdir()})
                self.assertEqual(len(list(actual.iterdir())),11)
                self.assertEqual(digest,s.site_identity(actual))
                before={p:p.read_bytes() for p in actual.iterdir()}
                with self.assertRaises(ValueError): s.site_generate(actual)
                self.assertEqual({p:p.read_bytes() for p in before},before)

    def test_site_hash_and_exact_file_ownership(self):
        directory=self.root/'site'; digest=s.site_generate(directory,'botanical')
        path=directory/'robots.txt'; original=path.read_bytes()
        path.write_bytes(original+b'# altered\n')
        self.assertNotEqual(s.site_identity(directory),digest)
        path.write_bytes(original); self.assertEqual(s.site_identity(directory),digest)
        for defect in ('extra','symlink','hardlink','mode'):
            with self.subTest(defect=defect):
                if defect=='extra': (directory/'foreign.txt').write_text('foreign')
                elif defect=='symlink': path.unlink(); path.symlink_to(directory/'index.html')
                elif defect=='hardlink': path.unlink(); os.link(directory/'index.html',path)
                else: path.chmod(0o666)
                with self.assertRaises(ValueError): s.site_identity(directory)
                (directory/'foreign.txt').unlink(missing_ok=True)
                path.unlink(); path.write_bytes(original); path.chmod(0o644)

    def test_new_vhost_has_one_owned_loopback_origin_and_immutable_site_binding(self):
        import shutil
        nginx=self.root/'nginx'; shutil.copytree(ROOT/'tests/fixtures/nginx',nginx)
        (nginx/'conf.d').mkdir(exist_ok=True)
        site=self.root/'site'; digest=s.site_generate(site)
        output=self.root/'plan.json'
        s.nginx_plan(nginx,'proxy.example.com',output,site_digest=digest)
        plan=json.loads(output.read_text())
        for edit in plan['edits']: Path(edit['path']).write_text(edit['content'])
        vhost=nginx/'conf.d/telemt-web-manager.conf'
        self.assertEqual(vhost.read_text(),s.render_vhost('proxy.example.com',site_digest=digest))
        self.assertIn('listen 127.0.0.1:18081;',vhost.read_text())
        self.assertIn('keepalive 32;',vhost.read_text())
        s.nginx_plan(nginx,'proxy.example.com',output)
        self.assertEqual(json.loads(output.read_text())['edits'],[])
        config=self.root/'config.toml'
        result=subprocess.run(['bash','-c','source ./telemt-web-manager.sh; DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10 DATA=/var/lib/telemt; generate_config 00000000000000000000000000000000'],cwd=ROOT,capture_output=True,check=True)
        config.write_bytes(result.stdout)
        self.assertEqual(s.site_bound_identity(config,'/var/lib/telemt',nginx,site),digest)
        (site/'robots.txt').write_bytes(b'changed')
        with self.assertRaises(ValueError): s.site_bound_identity(config,'/var/lib/telemt',nginx,site)

    def test_origin_listener_and_root_are_never_adopted(self):
        import shutil
        for name,foreign in (
            ('ipv4','server { listen 127.0.0.1:18081; }'),
            ('wildcard','server { listen 18081; }'),
            ('ipv6','server { listen [::]:18081; }')):
            with self.subTest(listener=name):
                nginx=self.root/name; shutil.copytree(ROOT/'tests/fixtures/nginx',nginx)
                (nginx/'conf.d').mkdir(exist_ok=True)
                path=nginx/'conf.d/foreign.conf'; path.write_text(foreign)
                before={p:p.read_bytes() for p in nginx.rglob('*') if p.is_file()}
                with self.assertRaises(ValueError):
                    s.nginx_plan(nginx,'proxy.example.com',self.root/'plan',site_digest='a'*64)
                self.assertEqual({p:p.read_bytes() for p in before},before)
        foreign=self.root/'foreign-site'; foreign.mkdir(); (foreign/'keep.txt').write_text('keep')
        with self.assertRaises(ValueError): s.site_generate(foreign)
        self.assertEqual((foreign/'keep.txt').read_text(),'keep')


if __name__=='__main__': unittest.main()
