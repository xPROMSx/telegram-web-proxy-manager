"""Exact HTTP formats and explicit optimization; real files/PTY, fixture services."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from test_safety import ROOT, s
from test_ui import terminal


LEGACY = (ROOT/'tests/fixtures/nginx-vhost-legacy.conf').read_text()
HOST = 'proxy.example.com'


class KeepaliveTests(unittest.TestCase):
    def fixture(self, includes=False, legacy=True):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        base=Path(temp.name); root=base/'nginx'
        shutil.copytree(ROOT/('tests/fixtures/nginx-3x-includes' if includes else 'tests/fixtures/nginx'),root)
        for name in ('conf.d','stream-sni.d','stream-upstreams.d','snippets/x-ui-auto-optional'):
            (root/name).mkdir(parents=True,exist_ok=True); (root/name).chmod(0o755)
        output=base/'plan.json'
        s.nginx_plan(root,HOST,output)
        for edit in json.loads(output.read_text())['edits']:
            Path(edit['path']).write_text(edit['content']); Path(edit['path']).chmod(0o644)
        vhost=root/'conf.d/telemt-web-manager.conf'
        if legacy: vhost.write_text(LEGACY)
        state=base/'state'; state.mkdir(0o700)
        manifest=state/'manifest.json'
        manifest.write_text(json.dumps(dict(schema=1,domain=HOST,public_ip='203.0.113.10',
            unit_sha256='1'*64,nginx_sha256=hashlib.sha256(vhost.read_bytes()).hexdigest(),acme_webroot='')))
        manifest.chmod(0o600)
        for name in ('telemt','telemt.toml','telemt.service','data/state/quota','certificates/lineage'):
            path=base/'controls'/name; path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(b'unchanged fixture control bytes'); path.chmod(0o600)
        return base,root,vhost,manifest,output

    def snapshot(self,root):
        return {p.relative_to(root):(p.read_bytes(),p.stat().st_mode,p.stat().st_uid,p.stat().st_gid)
                for p in root.rglob('*') if p.is_file() and p.relative_to(root).parts[0] not in ('tmp','lock')}

    def test_two_exact_http_formats_with_both_stream_formats(self):
        self.assertEqual(s.render_vhost(HOST,keepalive=False),LEGACY,'historical bytes must stay fixed')
        for includes in (False,True):
            for legacy in (False,True):
                with self.subTest(includes=includes,legacy=legacy):
                    _,root,_,_,output=self.fixture(includes,legacy)
                    before=self.snapshot(root)
                    s.nginx_plan(root,HOST,output)
                    self.assertEqual(json.loads(output.read_text())['edits'],[])
                    s.nginx_plan(root,HOST,output,uninstall=True)
                    self.assertEqual(self.snapshot(root),before)
                    self.assertTrue(any(e['content'] is None for e in json.loads(output.read_text())['edits']))

    def test_single_vhost_plan_binds_manifest_and_preserves_stream_format(self):
        for includes in (False,True):
            _,root,vhost,manifest,output=self.fixture(includes)
            before=self.snapshot(root)
            s.nginx_keepalive_plan(root,HOST,output,'/var/lib/telemt-web-manager-acme',manifest)
            plan=json.loads(output.read_text())
            self.assertEqual(self.snapshot(root),before)
            self.assertEqual([e['path'] for e in plan['edits']],[str(vhost)])
            self.assertIn(str(manifest),plan['snapshot'])
            vhost.write_text(plan['edits'][0]['content'])
            value=json.loads(manifest.read_text()); value['nginx_sha256']=hashlib.sha256(vhost.read_bytes()).hexdigest()
            manifest.write_text(json.dumps(value))
            s.nginx_keepalive_plan(root,HOST,output,'/var/lib/telemt-web-manager-acme',manifest)
            self.assertEqual(json.loads(output.read_text())['edits'],[])
            self.assertEqual({p:v for p,v in self.snapshot(root).items() if p!=vhost.relative_to(root)},
                             {p:v for p,v in before.items() if p!=vhost.relative_to(root)})

    def test_changed_vhost_or_manifest_hash_never_becomes_trusted(self):
        for legacy in (False,True):
            _,root,vhost,manifest,output=self.fixture(legacy=legacy)
            original=vhost.read_text()
            for text,bind_hash in ((original,False),(original+'# manual edit\n',True),
                                   (original.replace('18080','18081'),True),
                                   (original.replace('keepalive 32','keepalive 64') if not legacy else original+'\n',True)):
                vhost.write_text(text)
                value=json.loads(manifest.read_text())
                value['nginx_sha256']=hashlib.sha256(vhost.read_bytes()).hexdigest() if bind_hash else '0'*64
                manifest.write_text(json.dumps(value)); before=self.snapshot(root)
                with self.assertRaises(ValueError): s.nginx_keepalive_plan(root,HOST,output,'/var/lib/telemt-web-manager-acme',manifest)
                self.assertEqual(self.snapshot(root),before)

    def test_foreign_definitions_references_and_dynamic_backends_refuse(self):
        _,root,_,manifest,output=self.fixture()
        path=root/'conf.d/neighbor.conf'
        for source in ('upstream twpm_web_backend { server 127.0.0.1:18080; }',
                       'upstream "TWPM_WEB_BACKEND" { server 127.0.0.1:18080; }',
                       r'upstream twpm_web_\backend { server 127.0.0.1:18080; }',
                       'server { location / { proxy_pass http://twpm_web_backend; } }',
                       'server { location / { proxy_pass "http://TWPM_WEB_BACKEND:80"; } }',
                       'map $host $backend { default twpm_web_backend; }',
                       'server { location / { proxy_pass http://$backend; } }'):
            path.write_text(source); before=self.snapshot(root)
            # The historical direct vhost does not claim this namespace;
            # attempting to enable it must prove exclusive ownership.
            s.nginx_plan(root,HOST,output)
            with self.subTest(source=source),self.assertRaises(ValueError):
                s.nginx_keepalive_plan(root,HOST,output,'/var/lib/telemt-web-manager-acme',manifest)
            self.assertEqual(self.snapshot(root),before)
        path.unlink()
        (root/'conf.d/telemt-web-manager.conf').write_text(s.render_vhost(HOST))
        path.write_text('server { location / { proxy_pass http://twpm_web_backend; } }')
        for uninstall in (False,True):
            with self.assertRaises(ValueError): s.nginx_plan(root,HOST,output,uninstall=uninstall)

    def interactive(self,base,answer=b'y\n',language='en',failure='',interactive=True,tty=True):
        # Ownership and service identity have their own real lifecycle fixtures.
        # Keep actual planning, lock, backups, publication and rollback here.
        code='''source ./telemt-web-manager.sh
NGINX_ROOT=$1/nginx STATE=$1/state TMP=$1/tmp BACKUP_ROOT=$1/backups LOCK=$1/lock
mkdir -p "$TMP"
DOMAIN=proxy.example.com UI_LANG=$2 UI_INTERACTIVE=$3 INTERACTIVE_INSTALL=$3
BIN=$1/controls/telemt CONFIG=$1/controls/telemt.toml UNIT=$1/controls/telemt.service
DATA=$1/controls/data CERT_ROOT=$1/controls/certificates
failure=$4
load_installation() { [[ $failure != ownership ]]; }
path_health() { [[ $failure != health ]] || ! grep -q 'keepalive 32' "$NGINX_ROOT/conf.d/telemt-web-manager.conf"; }
nginx_test() { [[ $failure != test ]] || ! grep -q 'keepalive 32' "$NGINX_ROOT/conf.d/telemt-web-manager.conf"; }
nginx_reload() { [[ $failure != reload ]] || ! grep -q 'keepalive 32' "$NGINX_ROOT/conf.d/telemt-web-manager.conf"; }
systemctl() { printf UNEXPECTED_TELEMT_MUTATION; return 1; }
restart_service() { printf UNEXPECTED_TELEMT_MUTATION; return 1; }
eval "$(declare -f atomic_copy | sed '1s/atomic_copy/original_copy/')"
atomic_copy() {
    if [[ $failure == manifest && $1 == "$TMP/manifest-keepalive.json" ]]; then return 1; fi
    if [[ $failure == write && $1 == "$TMP/nginx-stage" ]]; then return 1; fi
    original_copy "$@"
}
trap cleanup EXIT
take_lock
install_manager
'''
        # Real file backup/rollback probes need a transaction bound; existing
        # menu-only PTYs retain their default ten seconds.
        return terminal(code,answer,args=(str(base),language,str(int(interactive)),failure),
                        input_tty=tty,output_tty=tty,timeout=30)

    def test_explicit_optimization_both_languages_and_idempotence(self):
        for includes in (False,True):
            for language in ('en','ru'):
                base,root,vhost,manifest,_=self.fixture(includes)
                before=json.loads(manifest.read_text()); nginx_before=self.snapshot(root)
                controls=self.snapshot(base/'controls')
                result,out,err=self.interactive(base,('Да\n' if language=='ru' else 'Yes\n').encode(),language=language)
                self.assertEqual(result,0,(out+err).decode())
                self.assertIn(('Включить Nginx upstream keepalive?' if language=='ru'
                               else 'Enable Nginx upstream keepalive?').encode(),out)
                self.assertIn(('Telemt не перезапускался.' if language=='ru'
                               else 'Telemt was not restarted.').encode(),out)
                self.assertNotIn(b'UNEXPECTED_TELEMT_MUTATION',out+err)
                self.assertEqual(vhost.read_text(),s.render_vhost(HOST))
                self.assertEqual(self.snapshot(base/'controls'),controls)
                after=json.loads(manifest.read_text())
                self.assertEqual(after,before|{'nginx_sha256':hashlib.sha256(vhost.read_bytes()).hexdigest()})
                self.assertEqual({p:v for p,v in self.snapshot(root).items() if p!=vhost.relative_to(root)},
                                 {p:v for p,v in nginx_before.items() if p!=vhost.relative_to(root)})
                before=self.snapshot(base)
                result,out,err=self.interactive(base,language=language)
                self.assertEqual(result,0); self.assertEqual(self.snapshot(base),before)
                self.assertNotIn(b'[y/N]',out); self.assertNotIn('[д/Н]'.encode(),out)

    def test_cancel_cli_eof_and_absent_tty_do_not_optimize(self):
        for answer,interactive,tty in ((b'n\n',True,True),(b'\x04',True,True),
                                       (b'y\n',False,True),(b'y\n',True,False)):
            base,_,_,_,_=self.fixture(); before=self.snapshot(base)
            result,out,err=self.interactive(base,answer,interactive=interactive,tty=tty)
            self.assertEqual(result,0)
            after=self.snapshot(base)
            # The existing lock file is the only orchestration artifact.
            self.assertEqual({p:v for p,v in after.items() if str(p)!='lock'},before)
            self.assertFalse((base/'backups').exists())
            self.assertNotIn(b'UNEXPECTED_TELEMT_MUTATION',out+err)

    def test_faults_restore_vhost_manifest_and_web_without_telemt_restart(self):
        for failure in ('ownership','write','test','reload','health','manifest'):
            for includes in (False,True):
                base,root,vhost,manifest,_=self.fixture(includes)
                before=self.snapshot(root); original=manifest.read_bytes()
                controls=self.snapshot(base/'controls')
                result,out,err=self.interactive(base,failure=failure)
                self.assertNotEqual(result,0)
                self.assertEqual(self.snapshot(root),before); self.assertEqual(manifest.read_bytes(),original)
                self.assertEqual(self.snapshot(base/'controls'),controls)
                self.assertNotIn(b'UNEXPECTED_TELEMT_MUTATION',out+err)
                if failure=='ownership': self.assertNotIn(b'[y/N]',out)


if __name__=='__main__': unittest.main()
