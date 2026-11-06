"""Historical static_directory resources remain read-only compatibility data."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from test_safety import ROOT, s
from legacy_site_fixture import legacy_config


class LegacyCoverTests(unittest.TestCase):
    def test_historical_resource_hashes_are_preserved(self):
        root=ROOT/'assets/fake-sites'
        manifest=json.loads((root/'manifest.json').read_text())
        for entry in manifest['sites']:
            raw=(root/(entry['id']+'.html')).read_bytes()
            self.assertEqual(len(raw),entry['size'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(),entry['sha256'])
        raw=(root/'cover.css').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),manifest['stylesheet']['sha256'])
        self.assertFalse(hasattr(s,'cover_change'))
        self.assertFalse(hasattr(s,'cover_initial'))

    def test_legacy_mode_does_not_claim_or_modify_a_new_site_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); nginx=root/'nginx'; output=root/'plan.json'
            shutil.copytree(ROOT/'tests/fixtures/nginx',nginx); (nginx/'conf.d').mkdir(exist_ok=True)
            s.nginx_plan(nginx,'proxy.example.com',output)
            for edit in json.loads(output.read_text())['edits']: Path(edit['path']).write_text(edit['content'])
            raw=subprocess.check_output(['bash','-c','source ./telemt-web-manager.sh; DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10 DATA=/var/lib/telemt; generate_config 00000000000000000000000000000000'],cwd=ROOT)
            config=root/'config.toml'; config.write_bytes(legacy_config(raw)); config.chmod(0o640)
            foreign=root/'site'; foreign.write_bytes(b'foreign object must survive')
            for keepalive in (False,True):
                (nginx/'conf.d/telemt-web-manager.conf').write_text(s.render_vhost('proxy.example.com',keepalive=keepalive))
                s.runtime_contract(config,'/var/lib/telemt')
                self.assertIsNone(s.site_bound_identity(config,'/var/lib/telemt',nginx,foreign))
                self.assertEqual(foreign.read_bytes(),b'foreign object must survive')

    def test_covers_survive_existing_full_data_transaction(self):
        spec = importlib.util.spec_from_file_location('cover_transaction',ROOT/'tests/update_transactions.py')
        fixture = importlib.util.module_from_spec(spec); sys.modules[spec.name] = fixture; spec.loader.exec_module(fixture)
        for raw in [(ROOT/'tests/fixtures/legacy-service-status.html').read_bytes(), *((ROOT/'assets/fake-sites'/name).read_bytes() for name in ('site-02.html','site-03.html','site-04.html'))]:
            f = fixture.Fixture()
            try:
                path = f.layout.data/'public/index.html'; path.write_bytes(raw)
                css = f.layout.data/'public/cover.css'; css.write_bytes((ROOT/'assets/fake-sites/cover.css').read_bytes()); css.chmod(0o440)
                before = hashlib.sha256(raw).digest()
                f.engine.update()
                self.assertEqual(hashlib.sha256(path.read_bytes()).digest(),before)
                self.assertEqual(css.read_bytes(),(ROOT/'assets/fake-sites/cover.css').read_bytes())
                self.assertEqual(css.stat().st_mode & 0o777,0o440)
                self.assertEqual(path.stat().st_mode & 0o777,0o440)
            finally: f.close()


if __name__ == '__main__': unittest.main()
