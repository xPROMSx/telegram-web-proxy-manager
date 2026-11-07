#!/usr/bin/env python3
"""Real root-owned bootstrap commit barrier; candidates are never executed."""
import importlib.util
import os
import py_compile
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('bootstrap_transaction_fixture',ROOT/'tests/update_transactions.py')
t=importlib.util.module_from_spec(spec); sys.modules[spec.name]=t; spec.loader.exec_module(t)
s=t.s


class BootstrapBarrier(unittest.TestCase):
    def fixture(self,manager_version=None):
        f=t.Fixture(); self.addCleanup(f.close)
        f.source=f.root/'candidate-pair'; f.source.mkdir(0o700)
        f.destination=f.root/'opt/telemt-web-manager'; f.destination.parent.mkdir(0o700)
        f.launcher=f.layout.binary.with_name('telemt-web-manager')
        f.marker=f.root/'candidate-executed'
        (f.source/'telemt-web-manager.sh').write_text((ROOT/'telemt-web-manager.sh').read_text()+
            '\ntouch "'+str(f.marker)+'"\n')
        (f.source/'safety.py').write_text((ROOT/'lib/safety.py').read_text()+
            '\nopen('+repr(str(f.marker))+', "w").write("EXECUTED")\n')
        for path in f.source.iterdir(): path.chmod(0o600)
        if manager_version is not None: self.candidate_version(f,manager_version)
        self.invoke(f,success=True)
        f.before=self.files(f)
        return f
    def files(self,f):
        paths=[f.launcher,f.launcher.with_name('telegram-web-proxy-manager'),*f.destination.rglob('*')]
        return {str(p):(p.stat().st_uid,p.stat().st_gid,p.stat().st_mode,
                       p.read_bytes() if p.is_file() else None) for p in paths if p.exists()}
    def candidate_version(self,f,version,previous='1.3.1'):
        for name,old,new in (('telemt-web-manager.sh','SCRIPT_VERSION='+previous,'SCRIPT_VERSION='+version),
                            ('safety.py',"UPDATE_MANAGER_VERSION = '"+previous+"'","UPDATE_MANAGER_VERSION = '"+version+"'")):
            path=f.source/name; text=path.read_text()
            self.assertEqual(text.count(old),1,'version mutation must change the candidate')
            path.write_text(text.replace(old,new))
    def invoke(self,f,success=False,tag='v1.3.1',explicit=''):
        code=('source "$1"; BOOTSTRAP_TMP=$2; INSTALL_DIR=$3; LAUNCHER=$4; BOOTSTRAP_LOCK=$5; '
              'MANAGER_TAG=$6; VERSION=$7; MANAGER_STATE=$8; MANAGER_SYSTEMD_ROOT=$9; commit_manager_pair')
        result=subprocess.run(['bash','-c',code,'fixture',str(ROOT/'install.sh'),str(f.source),
            str(f.destination),str(f.launcher),str(f.layout.path('/run/lock/telemt-web-manager.lock')),
            tag,explicit,str(f.layout.state),str(f.layout.recovery_unit.parent)],capture_output=True,timeout=15)
        self.assertEqual(result.returncode==0,success,'bootstrap result differs from expected barrier')
        self.assertFalse(f.marker.exists(),'downloaded manager/helper was executed')
        if not success: self.assertEqual(self.files(f),f.before,'barrier refusal changed installed manager pair')
    def test_supported_terminal_contract_commits_without_candidate_execution(self):
        f=self.fixture(); self.invoke(f,success=True)
        self.assertEqual(self.files(f),f.before)
    def test_actual_candidate_downgrade_refuses_even_with_higher_source_tag(self):
        f=self.fixture()
        self.candidate_version(f,'1.1.1')
        self.invoke(f,tag='v99.0.0')

    def test_112_upgrade_and_equal_131_preserve_old_receipt_recovery_and_data(self):
        f=self.fixture(manager_version='1.1.2')
        # Model the installed manager's original release receipt and terminal
        # journal; updating program files must not migrate either record.
        old=f.old|{'manager_version':'1.1.2'}
        s.update_write_json(f.layout.receipt,old)
        s.update_write_json(f.layout.generation,s.update_generation_value(old))
        journal=s.UpdateJournal(f.layout); journal.begin(old)
        journal.value['new']=journal.value['old']; journal.publish()
        journal.value['phase']='PREPARED'; journal.publish()
        journal.intent('COMMIT'); journal.result('COMMITTED')
        # Historical engine update under the old manager also leaves LKG and
        # recovery data. Pair replacement must preserve these bytes as well.
        with patch.object(s,'UPDATE_MANAGER_VERSION','1.1.2'):
            f.engine.update()
        def state():
            paths=[p for name in ('etc','var','root','usr','run/controller.json')
                   for p in [f.root/name,*(f.root/name).rglob('*')]]
            return {p:(p.read_bytes() if p.is_file() else None,
                       p.stat().st_uid,p.stat().st_gid,p.stat().st_mode) for p in paths}
        before=state()
        self.candidate_version(f,'1.3.1',previous='1.1.2')
        for _ in range(2):
            py_compile.compile(str(f.destination/'lib/safety.py'),doraise=True)
            self.invoke(f,success=True)
            self.assertEqual((f.destination/'telemt-web-manager.sh').read_bytes(),(f.source/'telemt-web-manager.sh').read_bytes())
            self.assertEqual((f.destination/'lib/safety.py').read_bytes(),(f.source/'safety.py').read_bytes())
            self.assertEqual(state(),before,'manager update changed Telemt state or recovery')
            self.assertEqual(s.UpdateReceipt.read(f.layout.receipt)['manager_version'],'1.1.2')
            s.update_service_gate(f.layout)
    def test_pending_critical_and_incomplete_cleanup_refuse_before_pair_staging(self):
        for phase in ('PREPARED','ROLLING_BACK','CRITICAL','COMMITTED'):
            with self.subTest(phase=phase):
                f=self.fixture(); value=s.UpdateJournal(f.layout).read(); value['phase']=phase
                if phase=='COMMITTED': value['intent']='NORMALIZE_LKG'
                s.update_write_json(f.layout.journal,value); self.invoke(f)
    def test_unknown_duplicate_malformed_missing_and_unsafe_records_refuse(self):
        for defect in ('unknown','duplicate','malformed','missing','mode','symlink','generation'):
            with self.subTest(defect=defect):
                f=self.fixture()
                if defect=='unknown': s.update_write_json(f.layout.receipt,f.old|{'schema':2})
                elif defect=='duplicate': s.update_write(f.layout.journal,b'{"schema":1,"schema":1}')
                elif defect=='malformed': s.update_write(f.layout.journal,b'{broken')
                elif defect=='missing': f.layout.journal.unlink()
                elif defect=='mode': f.layout.receipt.chmod(0o644)
                elif defect=='symlink': f.layout.receipt.unlink(); f.layout.receipt.symlink_to(f.layout.generation)
                else: s.update_write_json(f.layout.generation,s.update_generation_value(f.old)|{'receipt_sha256':'f'*64})
                self.invoke(f)
    def test_explicit_legacy_downgrade_cannot_remove_recovery_interpreter(self):
        f=self.fixture(); self.candidate_version(f,'0.1.4'); path=f.source/'telemt-web-manager.sh'
        text=path.read_text()
        path.write_text('\n'.join(line for line in text.splitlines() if 'UPDATE_' not in line)+'\n')
        self.invoke(f,tag='v0.1.4',explicit='v0.1.4')
    def test_semantically_corrupt_receipt_journal_binary_and_marker_refuse(self):
        # Matching schema numbers and generation hashes cannot bless a corrupt
        # terminal record. The bootstrap checks semantics without importing or
        # executing either downloaded member of the manager pair.
        for defect in ('signature','asset-url','asset-size','tag-target','release-time',
                       'service-state','supervisor','immutable','immutable-count','intent','binary','data-marker','extra-dropin'):
            with self.subTest(defect=defect):
                f=self.fixture(); receipt=dict(f.old); journal=s.UpdateJournal(f.layout).read()
                if defect=='signature': receipt['tag_verification']=receipt['tag_verification']|{'verified':False}
                elif defect=='asset-url': receipt['asset']=receipt['asset']|{'url':'https://foreign.example/asset'}
                elif defect=='asset-size': receipt['asset']=receipt['asset']|{'size':0}
                elif defect=='tag-target': receipt['release']=receipt['release']|{'target_commitish':'f'*40}
                elif defect=='release-time': receipt['release']=receipt['release']|{'published_at':'not-a-timestamp'}
                elif defect=='service-state': journal['service']='foreign-active'
                elif defect=='supervisor': journal['supervisor']['pid']=-1
                elif defect=='immutable': journal['immutable']={'config':'not-a-digest'}
                elif defect=='immutable-count': journal['immutable']={f'fixture-{i}':'a'*64 for i in range(257)}
                elif defect=='intent': journal['intent']='unknown-operation'
                elif defect=='binary': s.update_write(f.layout.binary,b'foreign executable',0o755)
                elif defect=='data-marker': s.update_write_json(f.layout.data/'.telemt-web-manager-generation.json',dict(schema=1,generation_id='f'*32))
                else: s.update_write(f.layout.dropin.parent/'foreign.conf',b'[Service]\n',0o644)
                if defect in ('signature','asset-url','asset-size','tag-target','release-time'):
                    # Keep the redundant generation hash consistent: refusal
                    # must come from the independent static semantic barrier.
                    s.update_write_json(f.layout.receipt,receipt)
                    s.update_write_json(f.layout.generation,s.update_generation_value(receipt))
                elif defect in ('service-state','supervisor','immutable','immutable-count','intent'):
                    s.update_write_json(f.layout.journal,journal)
                self.invoke(f)
    def test_schema_mismatch_and_changed_gate_require_manual_review(self):
        for defect in ('helper','dropin','recovery','orphan-state'):
            f=self.fixture()
            if defect=='helper':
                p=f.source/'safety.py'; p.write_text(p.read_text().replace('UPDATE_SCHEMA = 1','UPDATE_SCHEMA = 2'))
            elif defect=='dropin': s.update_write(f.layout.dropin,b'foreign gate\n',0o644)
            elif defect=='recovery': s.update_write(f.layout.recovery_unit,b'foreign recovery\n',0o644)
            else:
                for p in f.layout.state.iterdir(): p.unlink()
                f.layout.state.rmdir()
            self.invoke(f)

    def test_runtime_and_bootstrap_immutable_key_boundaries_agree(self):
        for key,accepted in (('a'*512,True),('a'*513,False),('',False),('é',False),('tab\tkey',False),('del\x7f',False)):
            with self.subTest(length=len(key),accepted=accepted):
                f=self.fixture(); journal=s.UpdateJournal(f.layout).read()
                journal['immutable']={key:'a'*64}
                if accepted: s.UpdateJournal.validate(journal)
                else:
                    with self.assertRaises(ValueError): s.UpdateJournal.validate(journal)
                s.update_write_json(f.layout.journal,journal)
                self.invoke(f,success=accepted)

    def test_generated_terminal_journals_pass_and_pending_housekeeping_refuses(self):
        for rollback in (False,True):
            f=self.fixture(); f.controller.fail_new=rollback
            if rollback:
                with self.assertRaises(ValueError): f.engine.update()
            else: f.engine.update()
            journal=s.UpdateJournal(f.layout).read(); s.UpdateJournal.validate(journal)
            self.invoke(f,success=True)
            journal['error']='cleanup-failed'; s.update_write_json(f.layout.journal,journal)
            self.invoke(f)


def verify_reviewed_bootstrap(artifacts):
    """Real terminal baseline records/ELFs; manager candidates remain data only."""
    for version, binary in (('3.5.12',Path(artifacts)/'baseline'),
                            ('3.5.16',Path(artifacts)/'fresh-x86_64/candidate')):
        case=BootstrapBarrier('test_supported_terminal_contract_commits_without_candidate_execution')
        try:
            f=case.fixture()
            f.layout.binary.unlink()
            s.update_copy_stream(binary,f.layout.binary,0o755)
            receipt=s.UpdateReceipt.create(f.layout.binary,'3'*32,'4'*32)
            assert receipt['installed_version']==version and receipt['origin']=='reviewed-baseline'
            s.update_write_json(f.layout.receipt,receipt)
            s.update_write_json(f.layout.generation,s.update_generation_value(receipt))
            s.update_write_json(f.layout.data/'.telemt-web-manager-generation.json',dict(schema=1,generation_id=receipt['generation_id']))
            journal=s.UpdateJournal(f.layout); journal.begin(receipt)
            journal.value['new']=journal.value['old']; journal.publish()
            journal.value['phase']='PREPARED'; journal.publish()
            journal.intent('COMMIT'); journal.result('COMMITTED')
            paths=[*f.layout.state.rglob('*'),*f.layout.data.rglob('*')]
            before={p:p.read_bytes() for p in paths if p.is_file()}
            case.invoke(f,success=True)
            assert before=={p:p.read_bytes() for p in before}
            print('REAL bootstrap over reviewed '+version+': manager pair accepted; receipt/journal/generation/DATA unchanged',flush=True)
        finally: case.doCleanups()


if __name__=='__main__':
    if os.geteuid()!=0: raise SystemExit('Use an isolated root test environment')
    unittest.main(verbosity=2)
