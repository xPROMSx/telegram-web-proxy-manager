#!/usr/bin/env python3
"""Bounded test-owned QEMU power cut: READY marker guarantees durable state."""
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import uuid

family,work,source,artifacts=sys.argv[1:]
work=Path(work); combined=[]
for attempt in range(4):
    name='twm-boot-'+uuid.uuid4().hex
    log=work/f'boot-{family}-{attempt}.log'
    command=['docker','run','--rm','--name',name,'--network=none','--cap-drop=ALL','--cap-add=DAC_OVERRIDE',
        '--security-opt=no-new-privileges','-v',str(work)+':/work','-v',source+':/src:ro',
        '-v',artifacts+':/evidence:ro','twm-boot:'+family,'qemu-system-x86_64','-accel','tcg','-cpu','max',
        '-m','1536','-smp','2','-nographic','-no-reboot','-nic','none',
        '-kernel',f'/work/boot-{family}/vmlinuz','-initrd',f'/work/boot-{family}/initrd.img',
        '-drive',f'file=/work/boot-{family}/disk.img,format=raw,if=virtio',
        '-virtfs','local,path=/src,mount_tag=source,security_model=none,readonly=on',
        '-virtfs','local,path=/evidence,mount_tag=evidence,security_model=none,readonly=on',
        '-object','rng-random,id=rng0,filename=/dev/urandom','-device','virtio-rng-pci,rng=rng0',
        '-append','root=/dev/vda rw console=ttyS0 init=/sbin/init systemd.mask=systemd-networkd-wait-online.service']
    cut=False; deadline=time.monotonic()+1200; offset=0; buffer=b''
    with log.open('wb') as output:
        process=subprocess.Popen(command,stdout=output,stderr=subprocess.STDOUT)
        try:
            while process.poll() is None:
                assert time.monotonic()<deadline,'real boot deadline exceeded'
                with log.open('rb') as incoming:
                    incoming.seek(offset); block=incoming.read(65536); offset+=len(block); buffer+=block
                while b'\n' in buffer:
                    line,buffer=buffer.split(b'\n',1)
                    if b'TWM_' in line or b'Acceptance sample' in line:
                        text=line.decode(errors='replace'); print(text,flush=True); combined.append(text)
                    counts=re.search(rb'logs: errors=([0-9]+), warnings=([0-9]+)',line)
                    if counts:
                        print('Actual invocation journal counts: errors='+counts[1].decode()+', warnings='+counts[2].decode(),flush=True)
                    if b'TWM_BOOT_FAIL' in line: raise AssertionError('guest assertion failed; inspect private boot log')
                    if b'TWM_HARD_POWERLOSS_READY' in line:
                        subprocess.run(['docker','kill','--signal=KILL',name],check=True,stdout=subprocess.DEVNULL)
                        cut=True; break
                time.sleep(.1)
            code=process.wait(timeout=10)
            assert code==0 or cut,'QEMU boot process failed'
        finally:
            if process.poll() is None:
                subprocess.run(['docker','kill','--signal=KILL',name],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                process.wait(timeout=20)
    if any('TWM_BOOT_ALL_PASS' in line for line in combined): break
else: raise AssertionError('four actual boots did not complete committed/nonterminal recovery and terminal housekeeping regressions')
assert all(any(marker in line for line in combined) for marker in
    ('TWM_BASELINE_ISOLATION_OK','TWM_HOSTILE_ISOLATION_ALL_PASS','TWM_FILESYSTEM_REAL_PASS',
     'TWM_REAL_UPDATE_OK','TWM_REAL_OFFLINE_CHECK_OK','TWM_COMMITTED_BOOT_OK','TWM_HARD_POWERLOSS_READY','TWM_NONTERMINAL_BOOT_OK',
     'TWM_TERMINAL_HOUSEKEEPING_BOOT_OK COMMITTED','TWM_TERMINAL_HOUSEKEEPING_BOOT_OK ROLLBACK_COMPLETE'))
print(f'REAL Ubuntu {family} boot/systemd/official Update/hard-power-loss recovery: PASS; no skips or fallback',flush=True)
