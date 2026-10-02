"""Read-only ownership planning and no-follow backup/remove/restore contracts."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from test_safety import ROOT, s


class UninstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.nginx = self.root / 'nginx'
        shutil.copytree(ROOT / 'tests/fixtures/nginx', self.nginx)
        (self.nginx / 'conf.d').mkdir()
        self.output = self.root / 'plan.json'
        self.host = 'proxy.example.com'

    def managed_nginx(self):
        original = {p: p.read_bytes() for p in self.nginx.rglob('*') if p.is_file()}
        s.nginx_plan(self.nginx, self.host, self.output)
        for edit in json.loads(self.output.read_text())['edits']:
            Path(edit['path']).write_text(edit['content'])
        return original

    def test_reverse_plan_preserves_exact_unrelated_bytes(self):
        original = self.managed_nginx()
        before = {p: p.read_bytes() for p in self.nginx.rglob('*') if p.is_file()}
        s.nginx_plan(self.nginx, self.host, self.output, uninstall=True)
        self.assertEqual(before, {p: p.read_bytes() for p in self.nginx.rglob('*') if p.is_file()})
        for edit in json.loads(self.output.read_text())['edits']:
            path = Path(edit['path'])
            if edit['content'] is None: s.planned_unlink(str(self.output), str(path))
            else: path.write_text(edit['content'])
        self.assertEqual(original, {p: p.read_bytes() for p in self.nginx.rglob('*') if p.is_file()})

    def test_reverse_preserves_original_map_indentation(self):
        path=self.nginx/'stream.conf'
        path.write_text(path.read_text().replace('\n}\nupstream panel','\n    }\nupstream panel'))
        self.test_reverse_plan_preserves_exact_unrelated_bytes()

    def test_changed_or_shared_stream_entries_refused(self):
        self.managed_nginx()
        path = self.nginx / 'stream.conf'; content = path.read_text()
        for changed in (content.replace('127.0.0.1:7444','127.0.0.1:7445'),
                        content.replace('# telemt-web-manager\n','\n'),
                        content.replace('panel.example.com panel','panel.example.com twm_frontend')):
            path.write_text(changed)
            with self.assertRaises(ValueError): s.nginx_plan(self.nginx,self.host,self.output,uninstall=True)
            self.assertEqual(path.read_text(),changed)
        path.write_text(content)
        vhost = self.nginx / 'conf.d/telemt-web-manager.conf'
        vhost.write_text(vhost.read_text()+'# manual edit\n')
        with self.assertRaises(ValueError): s.nginx_plan(self.nginx,self.host,self.output,uninstall=True)

    def test_unlink_rechecks_hash(self):
        self.managed_nginx()
        s.nginx_plan(self.nginx,self.host,self.output,uninstall=True)
        path = self.nginx / 'conf.d/telemt-web-manager.conf'
        path.write_text(path.read_text()+'# concurrent edit\n')
        with self.assertRaises(ValueError): s.planned_unlink(str(self.output),str(path))
        self.assertTrue(path.exists())

    def test_nofollow_tree_backup_removal_and_restore(self):
        roots = [self.root / name for name in ('binary','config','unit','data','state')]
        binary, config, unit, data, state = roots
        binary.write_text('binary'); unit.write_text('unit')
        for path in (config,data,state): path.mkdir()
        for path in (config/'telemt.toml',data/'cache',state/'manifest.json',state/'web-link.txt'):
            path.write_text(path.name)
        (state/'certificate.json').write_text('preserved')
        account = dict(user=['telemt','x',str(os.geteuid()),str(os.getegid()),'',str(data),'/usr/sbin/nologin'],
                       group=['telemt','x',str(os.getegid()),''])
        objects = s.uninstall_objects(list(map(str,roots)),account)
        plan = self.root/'ownership.json'
        s.fresh_save(plan,dict(schema=1, roots=list(map(str,roots)), account=account,objects=objects))
        backup = self.root/'backup'; backup.mkdir(mode=0o700)
        s.uninstall_backup(plan,backup)
        with mock.patch.object(s,'uninstall_quiet'):
            s.uninstall_remove(backup)
        self.assertTrue((state/'certificate.json').exists())
        self.assertFalse(config.exists()); self.assertFalse(data.exists())
        with mock.patch.object(s,'fresh_getent',side_effect=lambda db,key: account['user' if db=='passwd' else 'group']), \
             mock.patch.object(s,'fresh_identity',return_value=account), \
             mock.patch.object(s,'uninstall_uid_quiet'):
            s.uninstall_restore(backup)
        restored = s.uninstall_objects(list(map(str,roots)),account)
        for old, new in zip(objects,restored):
            for key in ('path','mode','uid','gid','sha256','directory'):
                self.assertEqual(old.get(key),new.get(key))

    def test_mount_symlink_and_hardlink_refused(self):
        root = self.root/'data'; root.mkdir()
        account = dict(user=['','',str(os.geteuid()),str(os.getegid())])
        path = root/'cache'; path.symlink_to('/etc/passwd')
        with self.assertRaises(ValueError): s.uninstall_objects([str(root)],account)
        path.unlink(); path.write_text('runtime'); os.link(path,root/'other')
        with self.assertRaises(ValueError): s.uninstall_objects([str(root)],account)
        with mock.patch.object(Path,'read_text',return_value=f'1 0 0:1 / {root} rw - ext4 x rw\n'):
            with self.assertRaises(ValueError): s.no_managed_mounts([str(root)])

    def test_certificate_state_is_schema_and_identity_strict(self):
        state=self.root/'state'; state.mkdir(mode=0o700)
        value=dict(schema=1,domain=self.host,cert_name=self.host,renewal_kind='standalone',acme_webroot='')
        s.fresh_save(state/'certificate.json',value)
        s.certificate_only_state(state)
        for update in ({'schema':2},{'cert_name':'foreign.example.com'},{'renewal_kind':'nginx'}):
            s.fresh_save(state/'certificate.json',value|update)
            with self.assertRaises(ValueError): s.certificate_only_state(state)
        (state/'certificate.json').write_text('{"schema":1,"schema":1}')
        with self.assertRaises(ValueError): s.certificate_only_state(state)

    def test_destructive_flags_require_uninstall_confirmation(self):
        for args in (['--check','--delete-certificate'],['--uninstall','--delete-certificate'],
                     ['--repair','--confirm-uninstall']):
            result=subprocess.run(['bash',str(ROOT/'telemt-web-manager.sh'),*args],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('require',result.stderr)

    def test_signal_cleanup_preserves_exit_status_after_successful_rollback(self):
        # Bash bare `return` in an EXIT trap can reuse the pre-trap status,
        # falsely reporting a successful rollback as failed. No files/services.
        code=('source "$1"; ARMED=1 UNINSTALLING=1 ROLLBACK_STATUS=$2; '
              'uninstall_rollback() { return "$ROLLBACK_STATUS"; }; '
              'trap cleanup EXIT; trap "exit $4" "$3"; kill -s "$3" "$BASHPID"')
        for signal, expected in (('INT',130),('TERM',143),('HUP',143)):
            for rollback_status in (0,1):
                result=subprocess.run(['bash','-c',code,'fixture',
                    str(ROOT/'telemt-web-manager.sh'),str(rollback_status),signal,str(expected)],
                    capture_output=True,text=True)
                self.assertEqual(result.returncode, expected if rollback_status == 0 else 1)

    def test_menu_uninstall_cancel_never_creates_backup(self):
        import pty
        import select
        import time
        master, slave=pty.openpty()
        code=('source "$1"; preflight() { :; }; need() { :; }; take_lock() { :; }; '
              'uninstall_load() { DOMAIN=proxy.example.com; }; '
              'backup_begin() { echo UNEXPECTED_BACKUP; exit 99; }; main')
        p=subprocess.Popen(['bash','-c',code,'fixture',str(ROOT/'telemt-web-manager.sh')],
                           stdin=slave,stdout=slave,stderr=slave)
        os.close(slave)
        output=b''
        try:
            os.write(master,b'5\nCANCEL\n')
            deadline=time.monotonic()+10
            while p.poll() is None and time.monotonic()<deadline:
                if select.select([master],[],[],0.1)[0]:
                    try: output+=os.read(master,4096)
                    except OSError: break
            p.wait(timeout=10)
            while select.select([master],[],[],0)[0]:
                try: output+=os.read(master,4096)
                except OSError: break
            self.assertEqual(p.returncode,0,output)
            self.assertIn(b'5. Uninstall Telemt',output)
            self.assertIn(b'6. Exit',output)
            self.assertIn(b'Type UNINSTALL',output)
            self.assertIn(b'Uninstall cancelled.',output)
            self.assertNotIn(b'UNEXPECTED_BACKUP',output)
            self.assertNotIn(b'Delete the Let',output)
        finally:
            if p.poll() is None: p.kill(); p.wait()
            os.close(master)
