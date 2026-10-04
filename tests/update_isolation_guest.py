#!/usr/bin/env python3
"""Actual hostile ELF version execution under the production VM namespaces."""
import os
from pathlib import Path
import sys
import time


def run(s,engine,source):
    private=engine.layout.backups/'isolation-adversarial'; private.mkdir(0o700)
    canaries=[Path('/root/update-host-canary'),Path('/root/telemt-backups/host-canary'),
              engine.layout.data/'state/host-only-canary']
    for path in canaries:
        # DATA/state is deliberately Telemt-owned; the root-only fixture adds
        # its canary through a no-follow fd, not the root-ancestor helper.
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try: os.write(fd,b'host object must stay inaccessible and unchanged'); os.fsync(fd)
        finally: os.close(fd)
        s.update_fsync(path.parent)
    originals={path:s.update_hash(path) for path in canaries}
    old_binary=s.update_hash(engine.layout.binary); old_config=s.update_hash(engine.layout.config)
    os.environ['UPDATER_TEST_CANARY']='must-not-be-inherited'
    try:
        for attack in (0,1,2,3):
            binary=private/('hostile-'+str(attack))
            s.update_run(['gcc','-O2','-Wall','-Wextra','-Werror','-DATTACK='+str(attack),
                          str(source/'tests/update_hostile.c'),'-o',str(binary)],timeout=60)
            root=engine.isolation.prepare(private/('root-'+str(attack)),binary)
            started=time.monotonic()
            try: engine.isolation.run(root,'4.0.0',parse_only=True)
            except (ValueError,OSError): pass
            else: raise AssertionError('hostile non-Telemt candidate unexpectedly passed strict parser')
            assert time.monotonic()-started<45,'private hostile version deadline was not enforced'
            ready=root/'var/lib/telemt/state/isolation-child-ready'
            assert ready.is_file(),'host access/capability/environment isolation checks did not run'
            assert ready.stat().st_uid==engine.tree.uid
            unit=engine.isolation.unit(root)+'.service'
            raw=s.update_run(['systemctl','show',unit,'-pActiveState','-pControlGroup'],accepted=(0,1)).decode()
            state=dict(line.split('=',1) for line in raw.splitlines())
            assert state['ActiveState'] in ('inactive','failed')
            if state['ControlGroup']:
                cgroup=Path('/sys/fs/cgroup')/state['ControlGroup'].lstrip('/')
                assert not cgroup.exists() or not (cgroup/'cgroup.procs').read_text().strip(),'detached hostile child survives'
            assert {path:s.update_hash(path) for path in canaries}==originals
            assert s.update_hash(engine.layout.binary)==old_binary and s.update_hash(engine.layout.config)==old_config
            print('TWM_ISOLATION_ATTACK_OK '+('filesystem/environment/CAP/PID/net denial + parser refusal','hung version + detached child reaped','bounded log flood + full cgroup reaped','fake stable 4.0.0 no-op parser rejected by unknown-key contract')[attack],flush=True)
    finally:
        os.environ.pop('UPDATER_TEST_CANARY',None)
        for path in canaries: path.unlink(); s.update_fsync(path.parent)
        engine.discard_private(private)
    print('TWM_HOSTILE_ISOLATION_ALL_PASS host DATA/config/certificate/systemd/network untouched',flush=True)


if __name__=='__main__': raise SystemExit('Invoked only by update_boot_guest.py inside the disposable VM')
