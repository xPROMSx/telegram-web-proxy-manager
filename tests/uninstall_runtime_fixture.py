#!/usr/bin/env python3
"""Deterministic private DATA churn and independent rollback evidence, no ACME."""
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import sys


def tree(root):
    root = Path(root)
    result = {}
    def visit(path):
        info = path.lstat()
        value = dict(uid=info.st_uid, gid=info.st_gid, mode=stat.S_IMODE(info.st_mode),
                     kind=stat.S_IFMT(info.st_mode))
        if stat.S_ISREG(info.st_mode): value['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        if stat.S_ISLNK(info.st_mode): value['target'] = os.readlink(path)
        value['xattrs'] = {name: os.getxattr(path, name, follow_symlinks=False).hex()
                          for name in os.listxattr(path, follow_symlinks=False)}
        result[str(path.relative_to(root))] = value
        if stat.S_ISDIR(info.st_mode):
            for child in sorted(path.iterdir()): visit(child)
    visit(root)
    return result


def owned(path, root, directory=False):
    identity = (Path(root) / 'state').stat()
    os.chown(path, identity.st_uid, identity.st_gid)
    path.chmod(0o750 if directory else 0o640)


def seed(root):
    root = Path(root)
    for name in ('mutable', 'replace', 'temporary'):
        path = root / 'state' / name
        path.write_text('before stop: ' + name); owned(path, root)
    # Names/layout are fixture evidence only, never a production allowlist.
    (root / 'cache').mkdir(); owned(root / 'cache', root, True)
    (root / 'public/runtime-note').write_text('ordinary extra public file')


def churn(root, plan, active, marker):
    root = Path(root)
    value = json.loads(Path(plan).read_text())
    assert value['phase'] == 'pre-stop' and Path(active).exists()
    assert {r['path'] for r in value['objects'] if Path(r['path']).is_relative_to(root)} == {
        str(root), str(root / 'public'), str(root / 'public/index.html')}
    # This already-running child verifies the completed ownership plan and active
    # service before touching DATA. Its synchronous completion is the barrier.
    Path(marker).write_text('ownership validated; service active\n')
    (root / 'state/mutable').write_text('rewritten while active')
    (root / 'state/new').write_text('created while active'); owned(root / 'state/new', root)
    replacement = root / 'state/replacement'
    replacement.write_text('atomically replaced while active'); owned(replacement, root)
    os.replace(replacement, root / 'state/replace')
    for path in (root / 'db', root / 'db/nested'):
        path.mkdir(); owned(path, root, True)
    (root / 'db/nested/item').write_text('nested runtime data'); owned(root / 'db/nested/item', root)
    (root / 'state/temporary').unlink()
    (root / 'transient-directory').mkdir(); (root / 'transient-directory').rmdir()
    assert Path(active).exists()
    Path(marker).write_text('churn complete before stop\n')


def finalize(root):
    path = Path(root) / 'state/final-stop'
    path.write_text('final service shutdown write'); owned(path, root)


def unsafe(root, kind):
    root = Path(root); path = root / 'state/offender'
    if kind == 'symlink': path.symlink_to(root.parent / 'outside')
    elif kind == 'hardlink': os.link(root / 'state/mutable', path)
    elif kind == 'fifo': os.mkfifo(path, 0o600)
    elif kind == 'socket':
        with socket.socket(socket.AF_UNIX) as sock: sock.bind(str(path))
    elif kind in ('char', 'block'):
        os.mknod(path, (stat.S_IFCHR if kind == 'char' else stat.S_IFBLK) | 0o600, os.makedev(1, 3))
    else:
        path.write_text('must remain untouched after refusal'); owned(path, root)
        if kind == 'owner': os.chown(path, (root / 'state').stat().st_uid + 1, -1)
        elif kind == 'mode': path.chmod(0o666)
        elif kind == 'xattr': os.setxattr(path, 'user.uninstall-fixture', b'unsafe')
        else: raise AssertionError(kind)


def check_backup(root, backup, expected):
    root, backup = Path(root), Path(backup)
    value = json.loads((backup / 'uninstall.json').read_text())
    assert value['phase'] == 'stopped' and value['object_directory'] == 'objects-stopped'
    actual = {}
    for index, record in enumerate(value['objects']):
        path = Path(record['path'])
        if not path.is_relative_to(root): continue
        item = dict(uid=record['uid'], gid=record['gid'], mode=record['mode'], xattrs={},
                    kind=stat.S_IFDIR if record['directory'] else stat.S_IFREG)
        if not record['directory']:
            item['sha256'] = hashlib.sha256((backup / 'objects-stopped' / str(index)).read_bytes()).hexdigest()
            assert item['sha256'] == record['sha256']
        actual[str(path.relative_to(root))] = item
    assert actual == json.loads(Path(expected).read_text())
    assert actual == tree(root)


def check_pre_backup(root, backup):
    root, backup = Path(root), Path(backup)
    value = json.loads((backup / 'uninstall.json').read_text())
    assert value['phase'] == 'pre-stop' and value['service'] == dict(active='active', enabled='enabled')
    assert (backup / 'initial-uninstall.json').read_bytes() == (backup / 'uninstall.json').read_bytes()
    assert (backup / 'service-state').read_text() == 'enabled\nactive\n'
    assert json.loads((backup / 'certificate-ownership.json').read_text()) == value['certificate']
    assert (backup / 'nginx-plan.json').is_file() and (backup / 'nginx-snapshot').is_dir()
    assert {r['path'] for r in value['objects'] if Path(r['path']).is_relative_to(root)} == {
        str(root), str(root / 'public'), str(root / 'public/index.html')}
    for index, record in enumerate(value['objects']):
        if not record['directory']:
            assert hashlib.sha256((backup / 'objects' / str(index)).read_bytes()).hexdigest() == record['sha256']


if __name__ == '__main__':
    action, *args = sys.argv[1:]
    if action == 'seed': seed(*args)
    elif action == 'churn': churn(*args)
    elif action == 'finalize': finalize(*args)
    elif action == 'unsafe': unsafe(*args)
    elif action == 'save': Path(args[1]).write_text(json.dumps(tree(args[0]), sort_keys=True))
    elif action == 'check': assert tree(args[0]) == json.loads(Path(args[1]).read_text())
    elif action == 'check-backup': check_backup(*args)
    elif action == 'check-pre-backup': check_pre_backup(*args)
    else: raise AssertionError(action)
