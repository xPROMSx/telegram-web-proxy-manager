#!/usr/bin/env python3
"""Disposable offline QEMU guest: real systemd, official ELF, WEB, Nginx/TLS.

Only GitHub transport is replayed from the already verified official download;
no service/process/namespace/journal/cgroup/filesystem operation is mocked.
"""
import copy
import faulthandler
import importlib.util
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import signal
import subprocess
import sys
import time
import traceback

MANAGER=Path('/opt/telemt-web-manager')
ARTIFACTS=Path('/mnt/evidence')
spec=importlib.util.spec_from_file_location('boot_safety',MANAGER/'lib/safety.py')
s=importlib.util.module_from_spec(spec); sys.modules[spec.name]=s; spec.loader.exec_module(s)
layout=s.UpdateLayout(); PHASE=Path('/root/twm-boot-phase.json')
HOST='proxy.example.com'
faulthandler.dump_traceback_later(120,repeat=True)  # Stack locations only; no exception values or locals.


def foreign_fixture_state():
    # Test-only, named unhooked fixtures. Production never fingerprints foreign
    # host state; retain this independent assertion against accidental flushing.
    return [s.update_run(command).decode() for command in (
        ['nft','list','table','inet','twm_foreign_fixture'],
        ['iptables','-S','TWM_FOREIGN_FIXTURE'],['ip6tables','-S','TWM_FOREIGN_FIXTURE'])]


def bash(function, secret=None):
    code='source "$1"; DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10; '+function
    return subprocess.check_output(['bash','-c',code,'twm-guest',str(MANAGER/'telemt-web-manager.sh')],
                                   input=secret.encode()+b'\n' if secret else None)


def setup():
    assert Path('/proc/1/comm').read_text().strip()=='systemd'
    s.update_run(['useradd','--system','--user-group','--home-dir','/var/lib/telemt','--no-create-home',
                  '--shell','/usr/sbin/nologin','telemt'])
    account=pwd.getpwnam('telemt'); uid,gid=account.pw_uid,account.pw_gid
    print('TWM_SETUP_ACCOUNT_OK',flush=True)
    # Foreign chains have no hooks/jumps and cannot affect the fixture traffic.
    # The enabled test-only unit recreates identical state BEFORE recovery on
    # every boot, as an existing host firewall service would.
    firewall=Path('/opt/twm-foreign-firewall.py')
    s.update_write(firewall,b'''import subprocess
commands=[['nft','add','table','inet','twm_foreign_fixture'],
['nft','add','chain','inet','twm_foreign_fixture','unrelated'],
['nft','add','rule','inet','twm_foreign_fixture','unrelated','counter','return']]
for family in ('iptables','ip6tables'):
    commands.extend([[family,'-N','TWM_FOREIGN_FIXTURE'],[family,'-A','TWM_FOREIGN_FIXTURE','-j','RETURN']])
for command in commands: subprocess.run(command,check=True)
''',0o644)
    s.update_write(Path('/etc/systemd/system/twm-foreign-firewall.service'),b'''[Unit]
Before=telemt-web-manager-recovery.service telemt.service
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/twm-foreign-firewall.py
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
''',0o644)
    s.update_run(['systemctl','daemon-reload'])
    s.update_run(['systemctl','enable','--now','twm-foreign-firewall.service'])
    s.update_write_json(Path('/root/twm-foreign-expected.json'),foreign_fixture_state())
    for path in (layout.config.parent,layout.data,layout.data/'state',layout.data/'public',layout.state,layout.backups):
        path.mkdir(mode=0o700)
        path.chmod(0o700 if path in (layout.state,layout.backups) else 0o750)
        os.chown(path,uid if path==layout.data/'state' else 0,0 if path in (layout.state,layout.backups) else gid)
    secret=secrets.token_hex(16)
    s.update_write(layout.config,bash('read -r token; generate_config "$token"',secret),0o640); os.chown(layout.config,0,gid)
    s.update_write(layout.data/'public/index.html',
                   b'<!doctype html><html lang="en"><meta charset="utf-8"><title>Welcome</title><h1>Welcome</h1></html>\n',0o440)
    os.chown(layout.data/'public/index.html',0,gid)
    s.update_copy_stream(ARTIFACTS/'baseline',layout.binary,0o755)
    assert s.update_hash(layout.binary)['sha256']==s.BASELINE_HASHES['x86_64'][1]
    s.update_write(layout.path('/etc/systemd/system/telemt.service'),bash('generate_unit'),0o644)
    cert_root=Path('/etc/letsencrypt'); cert_root.mkdir(mode=0o755,exist_ok=True)
    for directory in (cert_root/'archive'/HOST,cert_root/'live'/HOST,cert_root/'renewal',cert_root/'renewal-hooks/deploy'):
        directory.mkdir(mode=0o755,parents=True,exist_ok=True)
    archive=cert_root/'archive'/HOST
    s.update_run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','30','-subj','/CN='+HOST,
                  '-addext','subjectAltName=DNS:'+HOST,'-keyout',str(archive/'privkey1.pem'),'-out',str(archive/'cert1.pem')],timeout=90)
    (archive/'privkey1.pem').chmod(0o600)
    for part in ('cert','chain','fullchain','privkey'):
        if part in ('chain','fullchain'): shutil.copyfile(archive/'cert1.pem',archive/(part+'1.pem'))
        (cert_root/'live'/HOST/(part+'.pem')).symlink_to('../../archive/'+HOST+'/'+part+'1.pem')
    trust=Path('/usr/local/share/ca-certificates/twm-boot-fixture.crt'); shutil.copyfile(archive/'cert1.pem',trust)
    s.update_run(['update-ca-certificates'],timeout=60)
    renewal='version = 2.9.0\narchive_dir = '+str(archive)+'\n'
    for part in ('cert','chain','fullchain','privkey'): renewal+=part+' = '+str(cert_root/'live'/HOST/(part+'.pem'))+'\n'
    renewal+='[renewalparams]\nauthenticator = standalone\nserver = https://acme.invalid/directory\n'
    s.update_write(cert_root/'renewal'/(HOST+'.conf'),renewal.encode(),0o644)
    s.update_write(cert_root/'renewal-hooks/deploy/telemt-web-manager',bash('generate_renewal_hook'),0o755)
    nginx=Path('/etc/nginx')
    s.update_write(nginx/'nginx.conf',b'load_module /usr/lib/nginx/modules/ngx_stream_module.so;\npid /run/nginx.pid;\nevents { worker_connections 1024; }\nstream { include twm-stream.conf; }\nhttp { include conf.d/*.conf; }\n',0o644)
    s.update_write(nginx/'twm-stream.conf',(ROOT/'tests/fixtures/nginx/stream.conf').read_bytes(),0o644)
    plan_path=Path('/root/nginx-plan.json'); s.nginx_plan(nginx,HOST,plan_path)
    plan=s.update_json(plan_path.read_bytes())
    for edit in plan['edits']: s.update_write(Path(edit['path']),edit['content'].encode(),0o644)
    with Path('/etc/hosts').open('a') as output: output.write('\n127.0.0.1 '+HOST+'\n')
    manifest=dict(schema=1,domain=HOST,public_ip='203.0.113.10',
        unit_sha256=s.update_hash(layout.path('/etc/systemd/system/telemt.service'))['sha256'],
        nginx_sha256=s.update_hash(nginx/'conf.d/telemt-web-manager.conf')['sha256'],acme_webroot='')
    s.update_write_json(layout.state/'manifest.json',manifest)
    s.update_write_json(layout.state/'certificate.json',dict(schema=1,domain=HOST,cert_name=HOST,renewal_kind='standalone',acme_webroot=''))
    link='tg://webproxy?server='+HOST+'&secret=dd'+secret
    s.update_write(layout.state/'web-link.txt',link.encode()+b'\n')
    print('TWM_SETUP_DAEMON_RELOAD_BEGIN',flush=True)
    s.update_run(['systemctl','daemon-reload'])
    print('TWM_SETUP_NGINX_RESTART_BEGIN',flush=True)
    s.update_run(['systemctl','restart','nginx'],timeout=90)
    print('TWM_SETUP_NGINX_RESTART_OK',flush=True)
    s.update_run(['systemctl','enable','--now','telemt.service'],timeout=100)
    print('TWM_SETUP_SERVICE_STARTED',flush=True)
    engine=s.UpdateEngine(); old=engine.local_receipt(allow_legacy=True)
    deadline=time.monotonic()+90
    while True:
        try: engine.systemd.identity(old); engine.systemd.path_health(); break
        except (ValueError,s.UpdateCommandFailed):
            assert time.monotonic()<deadline; time.sleep(.2)
    # Real independent state, quota and full snapshot inputs.
    s.update_run(['systemctl','stop','telemt.service'],timeout=190); engine.systemd.quiet()
    print('TWM_SETUP_OLD_HEALTH_AND_GRACEFUL_STOP_OK',flush=True)
    quota=layout.data/'state/telemt.limit.json'
    if quota.exists(): quota.unlink()
    s.update_quota_seed(quota,dict(last_reset_epoch_secs=1700000000,
        users={'web-user':dict(used_bytes=8192,last_reset_epoch_secs=1700000000)}),uid,gid)
    s.update_run(['systemctl','start','telemt.service'],timeout=100)
    return engine


class RecordedHTTP:
    def download(self,url,path,size,digest):
        frozen=s.update_json((ARTIFACTS/'x86_64/frozen.json').read_bytes())
        item=next((key for key in ('asset','checksum_asset') if frozen[key]['url']==url),None)
        assert item and frozen[item]['size']==size and frozen[item]['sha256']==digest
        source=ARTIFACTS/'x86_64'/('archive.tar.gz' if item=='asset' else 'archive.sha256')
        assert s.update_hash(source)==dict(sha256=digest,size=size)
        s.update_copy_stream(source,path)


class RecordedReleases(s.UpdateReleases):
    def __init__(self): super().__init__(RecordedHTTP()); self.record=s.update_json((ARTIFACTS/'x86_64/frozen.json').read_bytes())
    def latest(self): return dict(self.record['release'],version=self.record['installed_version'])
    def freeze(self,release,arch): assert arch=='x86_64'; return copy.deepcopy(self.record)
    def recheck(self,record,require_latest=True):
        assert record==self.record==s.update_json((ARTIFACTS/'x86_64/frozen.json').read_bytes())


def assert_running(version):
    engine=s.UpdateEngine(); receipt=engine.local_receipt(); assert receipt['installed_version']==version
    engine.systemd.identity(receipt); engine.systemd.path_health(); s.update_service_gate(layout)
    engine.systemd.journal(engine.systemd.identity(receipt)['invocation'])
    assert foreign_fixture_state()==s.update_json(s.update_read(Path('/root/twm-foreign-expected.json')))
    return engine


def arm_terminal_housekeeping(engine):
    journal=engine.journal.read(); assert journal['phase'] in s.UPDATE_TERMINAL
    backup=layout.backup(journal['transaction_id']); path=backup/'precheck'
    assert not os.path.lexists(path)
    canary=Path('/root/twm-terminal-cleanup-canary')
    s.update_write(canary,b'cleanup must never follow this fixture link')
    path.symlink_to(canary); s.update_fsync(backup)
    # Known disposable evidence is deliberately unsafe to traverse. This faults
    # real finish_* persistently, without touching authoritative BIN/DATA/receipt.
    journal.update(normalized=False,error=None); engine.journal.publish()
    s.update_write(layout.data/'terminal-authority-canary',b'authoritative DATA must survive cleanup failure')
    return s.update_generation(layout)


def assert_terminal_housekeeping_boot(version,authority,terminal):
    engine=assert_running(version); journal=engine.journal.read()
    deadline=time.monotonic()+15
    while journal['error']!='cleanup-failed':
        assert time.monotonic()<deadline, 'terminal cleanup failure was not durably recorded'
        time.sleep(.1); journal=engine.journal.read()
    assert journal['phase']==terminal and journal['error']=='cleanup-failed' and not journal['normalized']
    assert s.update_generation(layout)==authority
    canary=layout.data/'terminal-authority-canary'
    assert s.update_read(canary)==b'authoritative DATA must survive cleanup failure'
    status=s.update_run(['systemctl','show','telemt-web-manager-recovery.service','-pActiveState','-pResult']).decode()
    assert 'ActiveState=active' in status and 'Result=success' in status
    before=s.update_hash(layout.binary); marker=s.update_read(layout.data/'.telemt-web-manager-generation.json')
    refused=subprocess.run(['bash',str(MANAGER/'telemt-web-manager.sh'),'--repair'],capture_output=True,timeout=120)
    assert refused.returncode!=0 and b'tg://' not in refused.stdout+refused.stderr
    assert s.update_hash(layout.binary)==before and s.update_generation(layout)==authority
    assert s.update_read(layout.data/'.telemt-web-manager-generation.json')==marker
    assert s.update_read(canary)==b'authoritative DATA must survive cleanup failure'
    engine.systemd.identity(authority)
    path=layout.backup(journal['transaction_id'])/'precheck'; assert path.is_symlink()
    assert s.update_read(Path('/root/twm-terminal-cleanup-canary'))==b'cleanup must never follow this fixture link'
    path.unlink(); s.update_fsync(path.parent)
    engine.recover(); repaired=engine.journal.read()
    assert repaired['normalized'] and repaired['error'] is None
    print('TWM_TERMINAL_HOUSEKEEPING_BOOT_OK '+terminal+': authoritative service active; persistent cleanup pending; normal CLI mutation refused; safe cleanup retry',flush=True)
    return engine


def main():
    global ROOT
    ROOT=Path('/mnt/source')
    print('TWM_REAL_BOOT '+Path('/etc/os-release').read_text().split('VERSION_ID=')[1].splitlines()[0]+
          ' PID1='+Path('/proc/1/comm').read_text().strip(),flush=True)
    if not PHASE.exists():
        engine=setup()
        old=engine.local_receipt(allow_legacy=True)
        private=Path('/root/baseline-isolation'); private.mkdir(0o700)
        probe=engine.isolation.prepare(private/'root',layout.binary)
        engine.isolation.run(probe,'3.5.12')
        print('TWM_BASELINE_ISOLATION_OK official 3.5.12, private UID/CAP_NET_ADMIN/WEB/strict parser/quota/shutdown',flush=True)
        sys.path.insert(0,str(ROOT/'tests'))
        import update_isolation_guest
        update_isolation_guest.run(s,engine,ROOT)
        import update_filesystem_guest
        update_filesystem_guest.run(s,engine)
        engine.releases=RecordedReleases()
        before=engine.immutable()
        with s.update_exclusive_lock(layout,inherit=False): engine.update()
        assert_running('3.5.13'); assert engine.immutable()==before|{
            'gate':s.update_hash(layout.dropin)['sha256'],'recovery-unit':s.update_hash(layout.recovery_unit)['sha256']}
        journal=s.UpdateJournal(layout).read(); assert journal['phase']=='COMMITTED' and journal['normalized']
        assert len(list(layout.stash.iterdir()))==1
        assert s.UpdateTree.validate(s.update_json(s.update_read(layout.backup(journal['transaction_id'])/'stopped-data-index.json',64*s.UPDATE_CHUNK)))
        check=s.update_run(['bash','/opt/telemt-web-manager/telemt-web-manager.sh','--check'],timeout=240)
        assert b'Check result: OK' in check and b'tg://' not in check
        assert len(list(layout.stash.iterdir()))==1,'read-only compatibility scratch survived Check'
        print('TWM_REAL_OFFLINE_CHECK_OK receipted 3.5.13, no GitHub/NIC, real private parser, scratch reaped',flush=True)
        print('TWM_REAL_UPDATE_OK 3.5.12 -> 3.5.13; unchanged TOML/unit/Nginx/certificate/WEB link; 150s+45s restart; one LKG',flush=True)
        authority=arm_terminal_housekeeping(engine)
        s.update_write_json(PHASE,dict(stage='committed-boot',authority=authority))
        print('TWM_REBOOT_REQUEST committed generation',flush=True)
        s.update_run(['systemctl','reboot']); return
    phase=s.update_json(s.update_read(PHASE)); stage=phase['stage']
    if stage=='committed-boot':
        assert_terminal_housekeeping_boot('3.5.13',phase['authority'],'COMMITTED')
        print('TWM_COMMITTED_BOOT_OK new 3.5.13 authoritative, exact ExecCondition and real recovery unit',flush=True)
        # Return to the exact old retained generation in this DISPOSABLE fixture,
        # then crash a SECOND genuine production Update after candidate startup.
        engine=s.UpdateEngine(); engine.systemd.stop(candidate=True)
        journal=engine.journal.read(); trees=layout.trees(journal['transaction_id']); index=engine.snapshot_index()
        engine.rename(layout.data,trees/'previous-accepted-fixture')
        old=journal['old']['receipt']
        engine.tree.clone(trees/'old',layout.data,index,normalized=True)
        engine.publish_binary(layout.backup(journal['transaction_id'])/'old-binary',old['binary'])
        engine.publish_receipt(old)
        journal.update(phase='ROLLBACK_COMPLETE',intent=None,restored=True,lkg=journal['transaction_id'])
        engine.journal.publish(); engine.systemd.start()
        class PowerLoss(s.UpdateEngine):
            def accept(self,receipt,first=150,second=None):
                if receipt['installed_version']=='3.5.13':
                    deadline=time.monotonic()+90
                    while True:
                        try: self.systemd.identity(receipt); self.systemd.path_health(); break
                        except (ValueError,s.UpdateCommandFailed):
                            assert time.monotonic()<deadline; time.sleep(.2)
                    path=layout.data/'state/crash-candidate-only'
                    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                    try: os.write(fd,b'must disappear on full old recovery'); os.fchown(fd,self.tree.uid,self.tree.gid); os.fsync(fd)
                    finally: os.close(fd)
                    s.update_fsync(path.parent)
                    s.update_write_json(PHASE,dict(stage='pending-boot',old=old))
                    print('TWM_HARD_POWERLOSS_READY actual production Update: nonterminal candidate active; durable journal + sealed original FULL DATA',flush=True)
                    while True: time.sleep(1)
                return super().accept(receipt,first,second)
        crash=PowerLoss(releases=RecordedReleases())
        with s.update_exclusive_lock(layout,inherit=False): crash.update()
        raise AssertionError('power-loss fixture was not reached')
    if stage=='pending-boot':
        deadline=time.monotonic()+180
        previous=None
        while True:
            current=s.UpdateJournal(layout).read()
            status=(current['phase'],current['intent'])
            if status!=previous: print('TWM_BOOT_RECOVERY_STAGE '+repr(status),flush=True); previous=status
            assert current['phase']!='CRITICAL','real boot recovery failed closed'
            if current['phase'] in s.UPDATE_TERMINAL: break
            assert time.monotonic()<deadline; time.sleep(.2)
        assert_running('3.5.12')
        journal=s.UpdateJournal(layout).read(); assert journal['phase']=='ROLLBACK_COMPLETE'
        assert s.UpdateReceipt.read(layout.receipt)==phase['old']
        assert not (layout.data/'state/crash-candidate-only').exists()
        assert s.update_quota_read(layout.data/'state/telemt.limit.json',pwd.getpwnam('telemt').pw_uid)['users']['web-user']['used_bytes']>=8192
        print('TWM_NONTERMINAL_BOOT_OK old 3.5.12 binary + FULL DATA + receipt restored; no candidate-only file; real old health; gate opens only after supervised restore',flush=True)
        engine=s.UpdateEngine(); authority=arm_terminal_housekeeping(engine)
        s.update_write_json(PHASE,dict(stage='rollback-terminal-boot',authority=authority))
        print('TWM_REBOOT_REQUEST rollback terminal with pending housekeeping',flush=True)
        s.update_run(['systemctl','reboot']); return
    if stage=='rollback-terminal-boot':
        assert_terminal_housekeeping_boot('3.5.12',phase['authority'],'ROLLBACK_COMPLETE')
        print('TWM_BOOT_ALL_PASS',flush=True)
        s.update_run(['systemctl','poweroff']); return
    raise ValueError('unexpected boot fixture phase')


try: main()
except BaseException:
    if layout.journal.exists():
        try:
            value=s.UpdateJournal(layout).read()
            print('TWM_FAILURE_JOURNAL '+repr((value['phase'],value['intent'],value['error'])),flush=True)
            evidence=layout.backup(value['transaction_id'])/'recovery-failure.json'
            if evidence.exists(): print('TWM_FAILURE_RECOVERY_EVIDENCE '+s.update_read(evidence,4096).decode().strip(),flush=True)
            raw=s.update_run(['systemctl','show','telemt-web-manager-recovery.service','-pActiveState','-pSubState','-pResult','-pExecMainStatus']).decode()
            print('TWM_FAILURE_RECOVERY_STATUS '+repr(raw),flush=True)
        except (ValueError,OSError): pass
    for frame in traceback.extract_tb(sys.exc_info()[2]):
        print('TWM_FAILURE_SITE '+Path(frame.filename).name+':'+str(frame.lineno)+':'+frame.name,flush=True)
    print('TWM_BOOT_FAIL '+type(sys.exc_info()[1]).__name__,flush=True)
    subprocess.run(['systemctl','poweroff'],check=False)
    raise SystemExit(1)
