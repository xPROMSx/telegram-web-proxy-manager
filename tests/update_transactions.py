#!/usr/bin/env python3
"""Root-only REAL filesystem/journal/gate crash matrix; service/API/isolation mocked.

No candidate executable runs here. update_boot.sh supplies real Ubuntu boot,
real systemd, verified official binaries and private runtime namespaces.
"""
import copy
import errno
import importlib.util
import json
import os
import signal
import stat
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('transaction_safety',ROOT/'lib/safety.py')
s=importlib.util.module_from_spec(spec); sys.modules[spec.name]=s; spec.loader.exec_module(s)
UID=1234; GID=1234


def frozen(version,arch='x86_64'):
    tag=version; release_id=100; base='https://github.com/telemt/telemt/releases/download/'+tag+'/'
    def asset(suffix,number):
        name='telemt-'+arch+'-linux-gnu.tar.gz'+suffix
        return dict(id=number,name=name,size=97 if suffix else 100,url=base+name,
                    api_url=f'https://api.github.com/repos/telemt/telemt/releases/assets/{number}',sha256='a'*64)
    return dict(repository=s.UPSTREAM_REPOSITORY,architecture=arch,installed_version=version,tag=tag,
        tag_object_sha='b'*40,commit_sha='c'*40,
        tag_verification=dict(verified=True,reason='valid',verified_at='2026-10-04T00:00:00Z'),
        release=dict(id=release_id,tag=tag,published_at='2026-10-04T00:00:00Z',draft=False,prerelease=False,
                     target_commitish='main',url=f'https://api.github.com/repos/telemt/telemt/releases/{release_id}',
                     html_url='https://github.com/telemt/telemt/releases/tag/'+tag),
        asset=asset('',200),checksum_asset=asset('.sha256',201))


class Releases:
    def __init__(self,version='3.5.13',drift=None,arch='x86_64'): self.version=version; self.checks=0; self.drift=drift; self.arch=arch
    def latest(self): return dict(version=self.version,id=100)
    def freeze(self,release,arch): assert arch==self.arch; return frozen(self.version,arch)
    def recheck(self,record,require_latest=True):
        self.checks+=1
        if self.drift==self.checks: raise ValueError('frozen release drift')
        assert record==frozen(self.version,self.arch)
    def download(self,record,directory):
        path=directory/'candidate'; s.update_write(path,('official-fixture-'+self.version).encode(),0o755); return path


class Controller:
    def __init__(self,layout,fail_new=False,fail_old=False):
        self.layout=layout; self.path=layout.path('/run/controller.json'); self.fail_new=fail_new; self.fail_old=fail_old
    def show(self): return s.update_json(s.update_read(self.path))
    def state(self,active): s.update_write_json(self.path,dict(ActiveState='active' if active else 'inactive',NRestarts='0'))
    def identity(self,receipt):
        assert self.show()['ActiveState']=='active'
        assert s.update_hash(self.layout.binary)==receipt['binary']
        assert stat.S_IMODE(self.layout.binary.stat().st_mode)==0o755
        if (receipt['installed_version']=='3.5.12' and self.fail_old) or (receipt['installed_version']!='3.5.12' and self.fail_new):
            raise ValueError('fixture objective health failure')
        return dict(pid=100,starttime='1',invocation='a'*32,restarts='0')
    def path_health(self): pass
    def journal(self,invocation): pass
    def firewall(self,clean=False): return b'foreign firewall retained'
    def quiet(self): assert self.show()['ActiveState']=='inactive'
    def stop(self,candidate=False): self.state(False)
    def start(self):
        s.update_service_gate(self.layout)
        self.state(True)
        receipt=s.UpdateReceipt.read(self.layout.receipt)
        # A candidate deliberately persists incompatible private runtime bytes.
        # Successful rollback must restore ALL files, not only the old binary.
        if receipt['installed_version']!='3.5.12':
            p=self.layout.data/'state/quota'; p.write_bytes(b'candidate persisted 999999'); p.chmod(0o600); os.chown(p,UID,GID)
    def reload(self): pass
    def ensure_recovery(self): pass


class Isolation:
    def __init__(self,engine,behavior='compatible'): self.engine=engine; self.behavior=behavior; self.calls=[]
    def prepare(self,path,binary,source=None,index=None):
        path.mkdir(0o700)
        if source: self.engine.tree.clone(source,path/'data',index)
        else: (path/'data').mkdir(0o700)
        return path
    def run(self,path,version,rehearsal=False,parse_only=False):
        self.calls.append((version,rehearsal))
        if self.behavior in ('incompatible','noop','quota-reset'):
            raise ValueError('fixture candidate contract rejected')
        if self.behavior=='mutate':
            self.engine.layout.config.write_bytes(b'concurrent manual config edit')
        if rehearsal: (path/'data/state/quota').write_bytes(b'rehearsal must never publish this')
    def quiet(self,backup): pass


class Engine(s.UpdateEngine):
    def ownership(self): pass  # This fixture mocks platform/controller identity only.
    def immutable(self):
        return dict(config=s.update_hash(self.layout.config)['sha256'],**{
                name:s.update_hash(self.layout.path('/etc/'+name))['sha256']
                for name in ('config-identity','nginx-identity','certificate-identity','unit-identity','link-identity')})
    def accept(self,receipt,first=150,second=None):
        self.systemd.identity(receipt); self.verify_immutable(); assert s.update_generation(self.layout)==receipt
        if second is not None:
            self.step('STOP_CANDIDATE',lambda:self.systemd.stop(candidate=True))
            self.journal.intent('START_CANDIDATE'); s.update_permit(self.layout,self.journal,receipt)
            self.systemd.start(); self.journal.result(); s.update_permit(self.layout,self.journal,receipt)
            self.accept(receipt,first=second)


class Fixture:
    def __init__(self,version='3.5.13',behavior='compatible',fail_new=False,fail_old=False,drift=None,arch='x86_64'):
        self.temp=tempfile.TemporaryDirectory(prefix='twm-update-filesystem-'); self.root=Path(self.temp.name)
        self.layout=s.UpdateLayout(self.root)
        for name in ('etc','etc/telemt','etc/systemd','etc/systemd/system','usr','usr/local','usr/local/bin',
                     'var','var/lib','var/lib/telemt','var/lib/telemt/state','var/lib/telemt/public',
                     'var/lib/telemt-web-manager','root','run','run/lock'):
            self.layout.path('/'+name).mkdir(0o700)
        for name in ('config-identity','nginx-identity','certificate-identity','unit-identity','link-identity'):
            s.update_write(self.layout.path('/etc/'+name),('unchanged-'+name).encode())
        s.update_write(self.layout.config,b'unchanged managed TOML',0o640)
        s.update_write(self.layout.binary,b'official-fixture-3.5.12',0o755)
        s.update_write(self.layout.data/'public/index.html',b'decoy',0o440)
        quota=self.layout.data/'state/quota'; s.update_write(quota,b'old nonzero quota 8192')
        for path in (self.layout.data/'state',quota): os.chown(path,UID,GID)
        self.arch=patch.object(s,'update_architecture',return_value=arch); self.arch.start()
        self.old=s.UpdateReceipt.create(self.layout.binary,'1'*32,'2'*32,frozen=frozen('3.5.12',arch))
        s.update_write_json(self.layout.receipt,self.old)
        s.update_write_json(self.layout.generation,s.update_generation_value(self.old))
        s.update_write_json(self.layout.data/'.telemt-web-manager-generation.json',dict(schema=1,generation_id='2'*32))
        s.update_gate_publish(self.layout)
        journal=s.UpdateJournal(self.layout); journal.begin(self.old); journal.value['new']=journal.value['old']; journal.publish()
        journal.value['phase']='PREPARED'; journal.publish(); journal.intent('COMMIT'); journal.result('COMMITTED')
        self.controller=Controller(self.layout,fail_new,fail_old); self.controller.state(True)
        identity=dict(user=['telemt','x',str(UID),str(GID),'',str(self.layout.data),'/usr/sbin/nologin'],
                      group=['telemt','x',str(GID),''])
        self.account=patch.object(s,'fresh_identity',return_value=identity); self.account.start()
        self.commands=patch.object(s,'update_run',side_effect=lambda args,**kwargs:b'enabled\n' if args[:2]==['systemctl','is-enabled'] else b'')
        self.commands.start()
        self.engine=Engine(self.layout,self.controller,Releases(version,drift,arch)); self.engine.isolation=Isolation(self.engine,behavior)
        self.original=self.engine.tree.inventory(self.layout.data); self.controls=self.engine.immutable()
    def close(self): self.commands.stop(); self.account.stop(); self.arch.stop(); self.temp.cleanup()
    def assert_old(self):
        assert s.update_generation(self.layout)==self.old
        assert self.engine.tree.inventory(self.layout.data)==self.original
        assert self.engine.immutable()==self.controls
        assert self.controller.show()['ActiveState']=='active'
        assert s.UpdateJournal(self.layout).read()['phase']=='ROLLBACK_COMPLETE'
        s.update_service_gate(self.layout)


class Transactions(unittest.TestCase):
    def fixture(self,**kwargs):
        result=Fixture(**kwargs); self.addCleanup(result.close); return result

    def test_compatible_3_5_13_and_future_4_have_identical_decision_path(self):
        for version in ('3.5.13','4.0.0'):
            f=self.fixture(version=version); f.engine.update()
            result=s.update_generation(f.layout)
            self.assertEqual(result['installed_version'],version)
            self.assertEqual(f.engine.immutable(),f.controls)
            self.assertEqual(f.engine.isolation.calls,[(version,False),(version,True)])
            journal=s.UpdateJournal(f.layout).read()
            self.assertEqual(journal['phase'],'COMMITTED'); self.assertTrue(journal['normalized'])
            saved=f.layout.trees(journal['transaction_id'])/'old'
            expected=copy.deepcopy(f.original)
            for record in expected['entries']: record.update(uid=0,gid=0)
            self.assertEqual(f.engine.tree.inventory(saved),expected)
            self.assertEqual(s.UpdateReceipt.read(f.layout.backup(journal['transaction_id'])/'old-receipt.json'),f.old)
            self.assertFalse((f.layout.backup(journal['transaction_id'])/'rehearsal').exists())

    def test_arm64_policy_receipt_generation_and_full_rollback_match_x86(self):
        for bad in (False,True):
            f=self.fixture(arch='aarch64',version='4.0.0',fail_new=bad)
            if bad:
                with self.assertRaises(ValueError): f.engine.update()
                f.assert_old()
            else:
                f.engine.update(); receipt=s.update_generation(f.layout)
                self.assertEqual(receipt['architecture'],'aarch64')
                self.assertEqual(receipt['installed_version'],'4.0.0')
                self.assertEqual(receipt['asset']['name'],'telemt-aarch64-linux-gnu.tar.gz')
                self.assertEqual(f.engine.immutable(),f.controls)

    def test_manager_and_recovery_umask_0077_preserve_executable_modes(self):
        original=os.umask(0o077)
        try:
            for failure in (False,True):
                f=self.fixture(fail_new=failure)
                if failure:
                    with self.assertRaises(ValueError): f.engine.update()
                    f.assert_old()
                else: f.engine.update()
                self.assertEqual(stat.S_IMODE(f.layout.binary.stat().st_mode),0o755)
                f.controller.identity(s.UpdateReceipt.read(f.layout.receipt))
        finally: os.umask(original)

    def test_dead_readonly_check_scratch_reaped_before_mutation_without_deleting_foreign_objects(self):
        for defect in (None,'live','unknown','link'):
            f=self.fixture(); s.update_private_directory(f.layout.stash)
            temporary=f.layout.stash/('.readonly-'+'a'*32); s.update_private_directory(temporary)
            proof=dict(schema=1,kind='read-only-compatibility',supervisor=s.update_supervisor())
            if defect!='live': proof['supervisor']['boot_id']='0'*36
            if defect=='unknown': proof['schema']=2
            s.update_write_json(temporary/'readonly.json',proof)
            scratch=temporary/'root'; scratch.mkdir(0o700)
            state=scratch/'owned-state'; state.write_bytes(b'private candidate state'); os.chown(state,UID,GID)
            foreign=f.root/'unrelated'; s.update_write(foreign,b'must not be followed or deleted')
            if defect=='link':
                (temporary/'readonly.json').unlink(); (temporary/'readonly.json').symlink_to(foreign)
            (scratch/'untrusted-link').symlink_to(foreign)
            calls=[]; f.engine.isolation.quiesce=lambda path:calls.append(path)
            if defect:
                with self.assertRaises(ValueError): f.engine.clean_readonly()
                self.assertTrue(state.exists()); self.assertFalse(calls)
            else:
                f.engine.clean_readonly(); self.assertFalse(temporary.exists()); self.assertEqual(calls,[scratch])
                self.assertFalse(any(p.lstat().st_uid==UID or p.lstat().st_gid==GID for p in f.layout.stash.rglob('*')))
            self.assertEqual(foreign.read_bytes(),b'must not be followed or deleted')
            self.assertEqual(s.update_generation(f.layout),f.old)

    def test_failed_compatible_runtime_restores_full_data_not_only_binary(self):
        f=self.fixture(fail_new=True)
        with self.assertRaises(ValueError): f.engine.update()
        f.assert_old(); f.engine.recover(); f.assert_old()

    def test_no_journal_retained_lkg_allows_fresh_recovery_without_a_telemt_account(self):
        f=self.fixture(); f.engine.update()
        for path in (f.layout.receipt,f.layout.generation,f.layout.journal): path.unlink()
        with patch.object(s,'UpdateLayout',return_value=f.layout),patch.object(s,'UpdateEngine',side_effect=AssertionError('no deployment account after Uninstall')):
            s.update_command('update-recover',[])
        self.assertTrue(any(f.layout.stash.iterdir()),'retained root-owned LKG must remain')

    def test_actual_identity_predicates_reject_uid_capability_listener_image_and_oom_changes(self):
        for defect in (None,'uid','gid','capability','groups','listener','oom','oom-kill','image','pid-race'):
            with self.subTest(defect=defect):
                f=self.fixture(); proc=f.root/'proc/100'; proc.mkdir(parents=True)
                (proc/'exe').symlink_to(f.layout.binary if defect!='image' else f.layout.config)
                status=f'Uid:\t{UID} {UID} {UID} {UID}\nGid:\t{GID} {GID} {GID} {GID}\nGroups:\t{GID}\nCapEff:\t0000000000001000\n'
                if defect=='uid': status=status.replace(f'Uid:\t{UID}', 'Uid:\t0')
                elif defect=='gid': status=status.replace(f'Gid:\t{GID}', 'Gid:\t0')
                elif defect=='capability': status=status.replace('0000000000001000','0000000000000000')
                elif defect=='groups': status=status.replace(f'Groups:\t{GID}',f'Groups:\t{GID} 0')
                (proc/'status').write_text(status)
                group=f.root/'sys/fs/cgroup/telemt'; group.mkdir(parents=True)
                (group/'memory.events').write_text('oom '+('1' if defect=='oom' else '0')+'\noom_kill '+('1' if defect=='oom-kill' else '0')+'\n')
                value=dict(ActiveState='active',SubState='running',MainPID='100',InvocationID='a'*32,NRestarts='0',ControlGroup='/telemt')
                controller=s.UpdateSystemd(f.layout); controller.show=lambda:value; controller.conntrack=lambda:None
                def path(*args):
                    result=Path(*args)
                    return f.root/str(result).lstrip('/') if result.is_relative_to('/proc') or result.is_relative_to('/sys/fs/cgroup') else result
                lookup=iter(('1','2' if defect=='pid-race' else '1'))
                listener=b'LISTEN 0 128 127.0.0.1:18080 0.0.0.0:* users:(("telemt",pid=100,fd=4))\n'
                if defect=='listener': listener=listener.replace(b'pid=100,',b'pid=101,')
                with patch.object(s,'Path',side_effect=path),patch.object(s,'update_starttime',side_effect=lambda pid:next(lookup)),patch.object(s,'update_run',return_value=listener):
                    if defect:
                        with self.assertRaises(ValueError): controller.identity(f.old)
                    else: self.assertEqual(controller.identity(f.old)['pid'],100)

    def test_late_acceptance_failure_rolls_back_full_generation_without_objective_retry(self):
        config=dict(web=dict(vhosts=[dict(host='proxy.example.com')]),access=dict(users={'web-user':'1'*32}))
        for defect in ('death','restarts','path','journal','WEB','restart-window'):
            with self.subTest(defect=defect):
                f=self.fixture(); clock=[0.0]; identity=f.controller.identity; calls=[0]; new_starts=[0]
                start=f.controller.start
                def start_count():
                    start()
                    if s.UpdateReceipt.read(f.layout.receipt)!=f.old: new_starts[0]+=1
                f.controller.start=start_count
                def fail(kind):
                    if kind==defect and s.UpdateReceipt.read(f.layout.receipt)!=f.old and clock[0]>=15:
                        calls[0]+=1; raise ValueError('objective acceptance failure')
                def lookup(receipt):
                    fail('death'); result=identity(receipt)
                    if receipt!=f.old and clock[0]>=15 and defect=='restarts':
                        calls[0]+=1; result['restarts']='1'
                    if receipt!=f.old and new_starts[0]>=2 and clock[0]>=165 and defect=='restart-window':
                        calls[0]+=1; raise ValueError('restarted candidate unhealthy')
                    return result
                f.controller.identity=lookup; f.controller.path_health=lambda:fail('path'); f.controller.journal=lambda invocation:fail('journal')
                original=f.engine.accept
                f.engine.accept=lambda receipt,**kwargs: original(receipt,**kwargs) if receipt==f.old else s.UpdateEngine.accept(f.engine,receipt,**kwargs)
                with patch.object(s,'read_config',return_value=config),patch.object(s.UpdateWEBProbe,'run',side_effect=lambda **kwargs:fail('WEB')),patch.object(s.time,'monotonic',side_effect=lambda:clock[0]),patch.object(s.time,'sleep',side_effect=lambda delay:clock.__setitem__(0,clock[0]+delay)):
                    with self.assertRaises(ValueError): f.engine.update()
                f.assert_old(); self.assertEqual(calls[0],1,'a failed objective assertion must not be retried')

    def test_graceful_candidate_restart_stop_and_start_failures_restore_full_old_generation(self):
        config=dict(web=dict(vhosts=[dict(host='proxy.example.com')]),access=dict(users={'web-user':'1'*32}))
        for defect in ('stop','start'):
            f=self.fixture(); clock=[0.0]; failures=[0]; stops=f.controller.stop; starts=f.controller.start; new_starts=[0]
            def stop(*args,**kwargs):
                if defect=='stop' and s.UpdateReceipt.read(f.layout.receipt)!=f.old and clock[0]>=150 and not failures[0]:
                    failures[0]+=1; raise ValueError('graceful candidate restart stop failed')
                return stops(*args,**kwargs)
            def start():
                if s.UpdateReceipt.read(f.layout.receipt)!=f.old:
                    new_starts[0]+=1
                    if defect=='start' and new_starts[0]==2:
                        failures[0]+=1; raise ValueError('candidate restart failed')
                return starts()
            f.controller.stop=stop; f.controller.start=start
            original=f.engine.accept
            f.engine.accept=lambda receipt,**kwargs: original(receipt,**kwargs) if receipt==f.old else s.UpdateEngine.accept(f.engine,receipt,**kwargs)
            with patch.object(s,'read_config',return_value=config),patch.object(s.UpdateWEBProbe,'run'),patch.object(s.time,'monotonic',side_effect=lambda:clock[0]),patch.object(s.time,'sleep',side_effect=lambda delay:clock.__setitem__(0,clock[0]+delay)):
                with self.assertRaises(ValueError): f.engine.update()
            f.assert_old(); self.assertEqual(failures[0],1)

    def test_future_incompatible_noop_quota_reset_and_immutable_edit_refuse(self):
        for behavior in ('incompatible','noop','quota-reset','mutate'):
            f=self.fixture(version='4.0.0',behavior=behavior)
            with self.assertRaises(ValueError): f.engine.update()
            if behavior=='mutate':
                self.assertEqual(s.UpdateJournal(f.layout).read()['phase'],'CRITICAL')
                with self.assertRaises(ValueError): s.update_service_gate(f.layout)
            else: f.assert_old()

    def test_frozen_drift_all_four_boundaries(self):
        for check in range(1,5):
            f=self.fixture(drift=check)
            with self.assertRaises(ValueError): f.engine.update()
            f.assert_old()

    def test_newer_no_downgrade_and_equal_health_provenance_no_snapshot(self):
        f=self.fixture(version='3.5.11')
        with self.assertRaises(ValueError): f.engine.update()
        self.assertEqual(s.update_generation(f.layout),f.old)
        f.engine.releases=Releases('3.5.12'); f.engine.update()
        self.assertFalse(f.layout.stash.exists())
        self.assertEqual(s.update_generation(f.layout),f.old)

    def test_every_durable_journal_boundary_hard_crash_and_idempotent_recovery(self):
        golden=self.fixture(); trace=[]; original=golden.engine.journal.publish
        def record():
            original(); trace.append((golden.engine.journal.value['phase'],golden.engine.journal.value['intent'],golden.engine.journal.value['sequence']))
        golden.engine.journal.publish=record; golden.engine.update()
        self.assertGreaterEqual(len(trace),25)
        for position,stage in enumerate(trace):
            with self.subTest(position=position,stage=stage):
                f=self.fixture(); count=[0]; publish=f.engine.journal.publish
                def crash():
                    publish()
                    if count[0]==position: os._exit(75)
                    count[0]+=1
                pid=os.fork()
                if pid==0:
                    f.engine.journal.publish=crash
                    try: f.engine.update()
                    except BaseException: os._exit(76)
                    os._exit(77)
                _,status=os.waitpid(pid,0); self.assertEqual(os.waitstatus_to_exitcode(status),75)
                journal=s.UpdateJournal(f.layout).read()
                if journal['phase']=='COMMITTED':
                    f.engine.recover(); self.assertEqual(s.update_generation(f.layout)['installed_version'],'3.5.13')
                    s.update_service_gate(f.layout)
                else:
                    with self.assertRaises((ValueError,FileNotFoundError)): s.update_service_gate(f.layout)
                    f.engine.recover(); f.assert_old(); f.engine.recover(); f.assert_old()
        print(f'REAL filesystem crash matrix: {len(trace)} durable boundaries, each recovered twice; no skipped cases',flush=True)

    def test_binary_receipt_generation_partial_publication_crashes(self):
        for target in ('binary','receipt','generation'):
            with self.subTest(target=target):
                f=self.fixture(); original=s.update_write_json; publish=f.engine.publish_binary
                def json_crash(path,value):
                    original(path,value)
                    if path==getattr(f.layout,target) and value!=f.old and f.engine.journal.value['new']:
                        os._exit(75)
                def binary_crash(source,expected):
                    publish(source,expected); os._exit(75)
                pid=os.fork()
                if pid==0:
                    if target=='binary': f.engine.publish_binary=binary_crash
                    else: s.update_write_json=json_crash
                    f.engine.update(); os._exit(77)
                _,status=os.waitpid(pid,0); self.assertEqual(os.waitstatus_to_exitcode(status),75)
                f.engine.recover(); f.assert_old()

    def test_every_rollback_intent_and_result_hard_crash_recovers_idempotently(self):
        golden=self.fixture(fail_new=True); trace=[]; publish=golden.engine.journal.publish
        def record():
            publish()
            if golden.engine.journal.value['phase'] in ('ROLLING_BACK','ROLLBACK_COMPLETE'):
                trace.append((golden.engine.journal.value['phase'],golden.engine.journal.value['intent']))
        golden.engine.journal.publish=record
        with self.assertRaises(ValueError): golden.engine.update()
        self.assertGreaterEqual(len(trace),12)
        for position,stage in enumerate(trace):
            with self.subTest(position=position,stage=stage):
                f=self.fixture(fail_new=True); original=f.engine.journal.publish; count=[0]
                def crash():
                    original()
                    if f.engine.journal.value['phase'] in ('ROLLING_BACK','ROLLBACK_COMPLETE'):
                        if count[0]==position: os._exit(75)
                        count[0]+=1
                pid=os.fork()
                if pid==0:
                    f.engine.journal.publish=crash
                    try: f.engine.update()
                    except BaseException: os._exit(76)
                    os._exit(77)
                _,status=os.waitpid(pid,0); self.assertEqual(os.waitstatus_to_exitcode(status),75)
                f.engine.recover(); f.assert_old(); f.engine.recover(); f.assert_old()
                self.assertTrue(s.UpdateJournal(f.layout).read()['normalized'])
        print(f'REAL rollback crash matrix: {len(trace)} intent/result boundaries, each recovered twice',flush=True)

    def test_partial_clone_and_stopped_index_crash_never_publish_incomplete_candidate(self):
        for stage in ('sealed-index','partial-working-clone'):
            f=self.fixture(); write=s.update_write_json; clone=f.engine.tree.clone
            def crash_index(path,value):
                write(path,value)
                if path.name=='stopped-data-index.json': os._exit(75)
            def crash_clone(source,destination,index,normalized=False):
                if destination.name=='working':
                    destination.mkdir(0o700); s.update_write(destination/'incomplete',b'partial clone'); os._exit(75)
                return clone(source,destination,index,normalized)
            pid=os.fork()
            if pid==0:
                if stage=='sealed-index': s.update_write_json=crash_index
                else: f.engine.tree.clone=crash_clone
                f.engine.update(); os._exit(77)
            _,status=os.waitpid(pid,0); self.assertEqual(os.waitstatus_to_exitcode(status),75)
            f.engine.recover(); f.assert_old(); self.assertEqual(s.update_generation(f.layout),f.old)

    def test_catchable_signals_after_candidate_mutation_restore_all_old_state(self):
        for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):
            f=self.fixture(); start=f.controller.start
            def start_signal():
                start()
                if s.UpdateReceipt.read(f.layout.receipt)!=f.old: os.kill(os.getpid(),sig)
            pid=os.fork()
            if pid==0:
                def interrupted(number,frame): raise InterruptedError('fixture signal')
                signal.signal(sig,interrupted); f.controller.start=start_signal
                try: f.engine.update()
                except InterruptedError: os._exit(75)
                except BaseException: os._exit(76)
                os._exit(77)
            _,status=os.waitpid(pid,0); self.assertEqual(os.waitstatus_to_exitcode(status),75)
            f.assert_old(); f.engine.recover(); f.assert_old()
        print('SIGINT/SIGTERM/SIGHUP: full old DATA/binary/receipt restored; no partial success',flush=True)

    def test_space_blocks_and_inodes_fail_before_old_stop_without_deleting_lkg(self):
        class Space:
            f_bavail=0; f_frsize=4096; f_favail=1000000
        for lacking in ('blocks','inodes'):
            f=self.fixture(); f.engine.update(); before=s.UpdateJournal(f.layout).read(); root=f.layout.trees(before['transaction_id'])
            f.engine.releases=Releases('4.0.0')
            value=Space()
            if lacking=='inodes': value.f_bavail=2**40; value.f_favail=0
            with patch.object(os,'statvfs',return_value=value),self.assertRaises(ValueError): f.engine.update()
            self.assertTrue(root.exists()); self.assertEqual(s.update_generation(f.layout)['installed_version'],'3.5.13')
            self.assertEqual(f.controller.show()['ActiveState'],'active')

    def test_partial_lkg_retirement_powerloss_is_resumable_and_keeps_new_commit(self):
        f=self.fixture(); f.engine.update(); prior=s.UpdateJournal(f.layout).read()['transaction_id']
        f.engine.releases=Releases('4.0.0'); discard=f.engine.discard_private
        def crash_retirement(path,root_only=False):
            if root_only:
                (Path(path)/'old/state/quota').unlink(); s.update_fsync(Path(path)/'old/state'); os._exit(75)
            return discard(path,root_only)
        pid=os.fork()
        if pid==0: f.engine.discard_private=crash_retirement; f.engine.update(); os._exit(77)
        _,status=os.waitpid(pid,0); self.assertEqual(os.waitstatus_to_exitcode(status),75)
        journal=s.UpdateJournal(f.layout).read(); self.assertEqual(journal['phase'],'COMMITTED')
        self.assertNotEqual(journal['transaction_id'],prior); self.assertEqual(s.update_generation(f.layout)['installed_version'],'4.0.0')
        f.engine.recover(); f.engine.recover(); self.assertFalse(f.layout.trees(prior).exists())
        self.assertEqual(len(list(f.layout.stash.iterdir())),1); s.update_service_gate(f.layout)

    def test_data_rename_operation_result_gaps_restore_exact_old_generation(self):
        for target in ('old','live','failed','restored'):
            f=self.fixture(fail_new=target in ('failed','restored')); rename=f.engine.rename
            def crash_rename(source,destination):
                rename(source,destination)
                hit=(target=='old' and Path(destination).name=='old' or
                     target=='live' and Path(destination)==f.layout.data and Path(source).name=='working' or
                     target=='failed' and Path(destination).name=='failed' or
                     target=='restored' and Path(source).name=='old' and Path(destination)==f.layout.data)
                if hit: os._exit(75)
            pid=os.fork()
            if pid==0: f.engine.rename=crash_rename; f.engine.update(); os._exit(77)
            _,status=os.waitpid(pid,0); self.assertEqual(os.waitstatus_to_exitcode(status),75)
            f.engine.recover(); f.assert_old(); f.engine.recover(); f.assert_old()

    def test_copy_enospc_and_eio_preserve_sealed_original_and_do_not_activate(self):
        for number in (errno.ENOSPC,errno.EIO):
            f=self.fixture(); clone=f.engine.tree.clone; activated=[]; start=f.controller.start
            def failed_clone(source,destination,index,normalized=False):
                if Path(destination).name=='working':
                    destination.mkdir(0o700); s.update_write(destination/'partial',b'partial DATA')
                    raise OSError(number,'fixture copy failure')
                return clone(source,destination,index,normalized)
            def track_start():
                activated.append(s.UpdateReceipt.read(f.layout.receipt)['installed_version']); start()
            f.engine.tree.clone=failed_clone; f.controller.start=track_start
            with self.assertRaises(OSError): f.engine.update()
            f.assert_old(); self.assertEqual(activated,['3.5.12'])

    def test_corrupt_journal_and_sealed_index_refuse_recovery_without_guessing(self):
        for target in ('journal','index'):
            f=self.fixture(); operation=f.engine.step
            def crash(intent,callback,phase=None):
                operation(intent,callback,phase)
                if intent=='REPLACE_BINARY': os._exit(75)
            pid=os.fork()
            if pid==0: f.engine.step=crash; f.engine.update(); os._exit(77)
            os.waitpid(pid,0)
            journal=s.UpdateJournal(f.layout).read(); index=f.layout.backup(journal['transaction_id'])/'stopped-data-index.json'
            if target=='journal': s.update_write(f.layout.journal,b'{"schema":1,"schema":1}')
            else: s.update_write(index,b'{"schema":1,"entries":[]}')
            with self.assertRaises(ValueError): f.engine.recover()
            with self.assertRaises(ValueError): s.update_service_gate(f.layout)
            self.assertTrue((f.layout.trees(journal['transaction_id'])/'old').exists())

    def test_initial_proc_exec_race_waits_for_readiness_but_later_disappearance_is_fatal(self):
        config=dict(web=dict(vhosts=[dict(host='proxy.example.com')]),access=dict(users={'web-user':'1'*32}))
        for after_readiness in (False,True):
            f=self.fixture(); identity=f.controller.identity; calls=[0]; f.engine.journal.read()
            f.engine.journal.value['immutable']=f.controls; f.engine.journal.publish()
            def lookup(receipt):
                calls[0]+=1
                if calls[0]==(2 if after_readiness else 1): raise FileNotFoundError('transient /proc image')
                return identity(receipt)
            f.controller.identity=lookup
            with patch.object(s,'read_config',return_value=config),patch.object(s.UpdateWEBProbe,'run'):
                if after_readiness:
                    with self.assertRaises(FileNotFoundError): s.UpdateEngine.accept(f.engine,f.old,first=0)
                else: s.UpdateEngine.accept(f.engine,f.old,first=0)
            self.assertEqual(calls[0],2 if after_readiness else 3)

    def test_ambiguous_foreign_binary_and_missing_snapshot_close_gate(self):
        for corruption in ('binary','snapshot','receipt'):
            f=self.fixture(); old=f.engine.step
            def fail(operation,callback,phase=None):
                old(operation,callback,phase)
                if operation=='REPLACE_BINARY': os._exit(75)
            pid=os.fork()
            if pid==0: f.engine.step=fail; f.engine.update(); os._exit(77)
            os.waitpid(pid,0)
            if corruption=='binary': s.update_write(f.layout.binary,b'foreign executable',0o755)
            elif corruption=='receipt': s.update_write_json(f.layout.receipt,dict(schema=99))
            else:
                tx=s.UpdateJournal(f.layout).read()['transaction_id']; (f.layout.backup(tx)/'stopped-data-index.json').unlink()
            with self.assertRaises((ValueError,FileNotFoundError)): f.engine.recover()
            self.assertEqual(s.UpdateJournal(f.layout).read()['phase'],'CRITICAL')
            with self.assertRaises(ValueError): s.update_service_gate(f.layout)
            self.assertEqual(f.controller.show()['ActiveState'],'inactive')

    def test_old_health_failure_never_reports_rollback_complete(self):
        f=self.fixture(fail_new=True)
        original=f.engine.accept
        def accept(receipt,**kwargs):
            if receipt==f.old: raise ValueError('old health failed after restoration')
            return original(receipt,**kwargs)
        f.engine.accept=accept
        with self.assertRaises(ValueError): f.engine.update()
        self.assertEqual(s.UpdateJournal(f.layout).read()['phase'],'CRITICAL')
        self.assertEqual(f.controller.show()['ActiveState'],'inactive')

    def test_gate_stale_permit_corrupt_and_missing_journal(self):
        f=self.fixture(); journal=f.engine.journal; journal.read(); journal.value['phase']='CANDIDATE_ACTIVATED'
        journal.value['new']=journal.value['old']
        journal.value['snapshot']=dict(sha256='a'*64,entries=1,logical_bytes=0,generation_id=f.old['generation_id'])
        journal.publish()
        with self.assertRaises(FileNotFoundError): s.update_service_gate(f.layout)
        s.update_permit(f.layout,journal,f.old); s.update_service_gate(f.layout)
        permit=s.update_json(s.update_read(f.layout.permit)); permit['boot_id']='0'*36
        s.update_write_json(f.layout.permit,permit)
        with self.assertRaises(ValueError): s.update_service_gate(f.layout)
        f.layout.journal.unlink()
        with self.assertRaises(ValueError): s.update_service_gate(f.layout)

    def test_only_one_lkg_after_two_updates_and_cleanup_failure_keeps_commit(self):
        f=self.fixture(); f.engine.update()
        first=s.UpdateJournal(f.layout).read()['transaction_id']
        f.engine.releases=Releases('4.0.0'); f.engine.update()
        journal=s.UpdateJournal(f.layout).read()
        self.assertEqual(s.update_generation(f.layout)['installed_version'],'4.0.0')
        self.assertEqual([p.name for p in f.layout.stash.iterdir()],[journal['transaction_id']])
        self.assertTrue((f.layout.backup(first)/'lkg-retired.json').exists())
        self.assertEqual(s.UpdateReceipt.read(f.layout.backup(journal['transaction_id'])/'old-receipt.json')['installed_version'],'3.5.13')
        g=self.fixture(); original=g.engine.finish_committed
        def fail_cleanup():
            if not g.engine.journal.value['snapshot']: return original()
            raise OSError('fixture post-commit cleanup failure')
        g.engine.finish_committed=fail_cleanup; g.engine.update()
        self.assertEqual(s.update_generation(g.layout)['installed_version'],'3.5.13')
        self.assertEqual(s.UpdateJournal(g.layout).read()['phase'],'COMMITTED')
        self.assertEqual(g.controller.show()['ActiveState'],'active')
        g.engine.finish_committed=original; g.engine.recover()
        self.assertTrue(s.UpdateJournal(g.layout).read()['normalized'])

    def test_strict_receipt_permissions_owner_and_schema(self):
        for change in ({'schema':2},{'origin':'foreign'},{'architecture':'mips'},
                       {'installed_version':'3.5.12+custom'},{'extra':True},
                       {'binary':{'sha256':'f'*64,'size':1}}):
            f=self.fixture(); s.update_write_json(f.layout.receipt,f.old|change)
            with self.assertRaises(ValueError): f.engine.local_receipt()
        for action in ('chmod','chown','symlink','missing-journal'):
            f=self.fixture()
            if action=='chmod': f.layout.receipt.chmod(0o644)
            elif action=='chown': os.chown(f.layout.receipt,UID,GID)
            elif action=='missing-journal': f.layout.journal.unlink()
            else:
                target=f.layout.receipt.with_name('foreign'); f.layout.receipt.rename(target); f.layout.receipt.symlink_to(target)
            with self.assertRaises(ValueError): f.engine.local_receipt()

    def test_readonly_receipt_check_does_not_query_github_for_future_4(self):
        f=self.fixture(version='4.0.0'); f.engine.update()
        f.engine.releases.latest=lambda: (_ for _ in ()).throw(AssertionError('offline Check must not query GitHub'))
        before=f.engine.tree.inventory(f.layout.data)
        self.assertEqual(f.engine.local_receipt()['installed_version'],'4.0.0')
        self.assertEqual(f.engine.tree.inventory(f.layout.data),before)

    def test_recovery_crash_after_old_started_does_not_revert_new_old_writes(self):
        f=self.fixture(fail_new=True); start=f.controller.start
        def crash_after_restored_start():
            start()
            if s.UpdateReceipt.read(f.layout.receipt)==f.old:
                (f.layout.data/'state/quota').write_bytes(b'old restarted and persisted 8193')
                os._exit(75)
        pid=os.fork()
        if pid==0: f.controller.start=crash_after_restored_start; f.engine.update(); os._exit(77)
        _,status=os.waitpid(pid,0); self.assertEqual(os.waitstatus_to_exitcode(status),75)
        f.engine.recover(); f.engine.recover()
        self.assertEqual((f.layout.data/'state/quota').read_bytes(),b'old restarted and persisted 8193')
        self.assertEqual(s.update_generation(f.layout),f.old)
        self.assertEqual(s.UpdateJournal(f.layout).read()['phase'],'ROLLBACK_COMPLETE')


if __name__=='__main__':
    if os.geteuid()!=0: raise SystemExit('Run the real filesystem fixture as root in an isolated CI environment')
    unittest.main(verbosity=2)
