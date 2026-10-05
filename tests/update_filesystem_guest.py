#!/usr/bin/env python3
"""Actual same-device bind mounts, devices, ACL/capability xattrs in a local VM."""
import os
from pathlib import Path
import socket
import stat
import struct


def run(s,engine):
    root=Path('/root/stopped-filesystem-negative'); root.mkdir(0o700)
    data=root/'data'; data.mkdir(0o750); path=data/'unsafe'; source=root/'bind-source'; source.mkdir()
    cases=0
    def reject():
        nonlocal cases
        try: engine.tree.inventory(data)
        except ValueError: cases+=1
        else: raise AssertionError('unsupported actual DATA object was accepted')
    path.symlink_to('/etc/passwd'); reject(); path.unlink()
    path.write_bytes(b'ordinary'); os.link(path,data/'alias'); reject(); (data/'alias').unlink(); path.unlink()
    os.mkfifo(path); reject(); path.unlink()
    with socket.socket(socket.AF_UNIX) as channel: channel.bind(str(path)); reject()
    path.unlink()
    for kind in (stat.S_IFCHR,stat.S_IFBLK):
        os.mknod(path,kind|0o600,os.makedev(1,3)); reject(); path.unlink()
    path.mkdir(); s.update_run(['mount','--bind',str(source),str(path)])
    try: reject()
    finally: s.update_run(['umount',str(path)]); path.rmdir()
    path.write_bytes(b'ordinary'); path.chmod(0o4755); reject(); path.chmod(0o600)
    os.chown(path,99999,99999); reject(); os.chown(path,0,0)
    # Linux POSIX ACL v2 with a named UID and explicit mask.
    acl=struct.pack('<I',2)+b''.join(struct.pack('<HHI',tag,perm,uid) for tag,perm,uid in
        ((1,6,0xffffffff),(2,4,engine.tree.uid),(4,4,0xffffffff),(16,4,0xffffffff),(32,0,0xffffffff)))
    os.setxattr(path,'system.posix_acl_access',acl); reject(); os.removexattr(path,'system.posix_acl_access')
    os.setxattr(path,'security.capability',struct.pack('<IIIII',0x02000001,0x1000,0,0,0))
    reject(); os.removexattr(path,'security.capability'); path.unlink()
    assert engine.tree.inventory(data)['logical_bytes']==0
    data.rmdir(); source.rmdir(); root.rmdir()
    print(f'TWM_FILESYSTEM_REAL_PASS {cases} actual refusals: link/hardlink/FIFO/socket/char/block/bind/setid/owner/ACL/capability; no skips',flush=True)
