"""Stopped-generation streaming and unsupported-object regression tests."""
import importlib.util
import errno
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('snapshot_safety', ROOT / 'lib/safety.py')
s = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = s
spec.loader.exec_module(s)


class UpdateSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.data = self.base / 'data'; self.data.mkdir()
        (self.data / 'state').mkdir(); (self.data / 'public').mkdir()
        (self.data / 'public/index.html').write_bytes(b'original decoy')
        (self.data / 'state/quota.json').write_bytes(b'nonzero original counter')
        self.tree = s.UpdateTree(os.geteuid(), os.getegid())

    def test_complete_clone_preserves_bytes_metadata_and_source(self):
        os.utime(self.data / 'state/quota.json', ns=(1234567890,1234567890))
        index = self.tree.inventory(self.data)
        destination = self.base / 'candidate'
        self.tree.clone(self.data, destination, index)
        self.assertEqual(self.tree.inventory(destination), index)
        (destination / 'state/quota.json').write_bytes(b'mutated candidate counter')
        self.assertEqual(self.tree.inventory(self.data), index)

    def test_large_file_uses_bounded_reads(self):
        path = self.data / 'state/large'
        with path.open('wb') as stream:
            for _ in range(65): stream.write(b'x' * 1024 * 1024)
        real_read = os.read
        def read(fd, amount):
            self.assertLessEqual(amount, 1024 * 1024)
            return real_read(fd, amount)
        with patch.object(os, 'read', read):
            index = self.tree.inventory(self.data)
            self.tree.clone(self.data, self.base / 'large-clone', index)
        self.assertGreaterEqual(index['logical_bytes'], 64 * 1024 * 1024)

    def test_directory_enumeration_stops_at_bound_before_materializing_all_names(self):
        consumed=[]
        class Entries:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def __iter__(self):
                for index in range(1000000):
                    consumed.append(index)
                    yield SimpleNamespace(name='entry-'+str(index))
        with patch.object(os,'scandir',return_value=Entries()):
            with self.assertRaises(ValueError): s.update_names(123,3)
        self.assertEqual(consumed,[0,1,2,3])

    def test_symlink_hardlink_fifo_setid_xattr_refused(self):
        bad = self.data / 'state/bad'
        builders = [lambda: bad.symlink_to(self.data / 'public/index.html'),
                    lambda: os.link(self.data / 'public/index.html', bad),
                    lambda: os.mkfifo(bad),
                    lambda: (bad.write_bytes(b'a'), bad.chmod(0o4755)),
                    lambda: (bad.write_bytes(b'a'), os.setxattr(bad,'user.extra',b'value'))]
        for build in builders:
            build()
            with self.assertRaises(ValueError): self.tree.inventory(self.data)
            bad.unlink()

    def test_nested_mount_and_space_shortage_refused(self):
        with patch.object(s, 'no_managed_mounts', side_effect=ValueError('mount')):
            with self.assertRaises(ValueError): self.tree.inventory(self.data)
        class Space: f_bavail=0; f_frsize=4096; f_favail=0
        with patch.object(os,'statvfs',return_value=Space()):
            with self.assertRaises(ValueError): self.tree.budget(self.data)

    def test_changed_sealed_source_refuses_clone(self):
        index = self.tree.inventory(self.data)
        (self.data / 'public/index.html').write_bytes(b'changed')
        with self.assertRaises(ValueError): self.tree.clone(self.data,self.base/'clone',index)
        self.assertFalse((self.base/'clone').exists())

    def test_short_writes_are_completed_and_zero_write_fails(self):
        index = self.tree.inventory(self.data); real_write=os.write
        with patch.object(os,'write',side_effect=lambda fd,data:real_write(fd,data[:2])):
            self.tree.clone(self.data,self.base/'short',index)
        self.assertEqual(self.tree.inventory(self.base/'short'),index)
        with patch.object(os,'write',return_value=0):
            with self.assertRaises(ValueError): self.tree.clone(self.data,self.base/'zero',index)

    def test_inventory_path_traversal_and_unknown_schema_fail(self):
        index = self.tree.inventory(self.data)
        index['entries'][1]['path'] = '../outside'
        with self.assertRaises(ValueError): self.tree.validate(index)

    def test_empty_directories_and_70_mib_sparse_file_copy_with_short_reads(self):
        (self.data/'state/empty').mkdir()
        sparse=self.data/'state/sparse'
        with sparse.open('wb') as output: output.seek(70*1024*1024-1); output.write(b'z')
        index=self.tree.inventory(self.data); read=os.read
        # A successful short read is not EOF and must preserve the whole file.
        with patch.object(os,'read',side_effect=lambda fd,size:read(fd,min(size,65536))):
            self.tree.clone(self.data,self.base/'sparse-copy',index)
        self.assertEqual(self.tree.inventory(self.base/'sparse-copy'),index)
        self.assertTrue((self.base/'sparse-copy/state/empty').is_dir())

    def test_grow_shrink_rename_replace_and_directory_change_never_seal(self):
        for mutation in ('grow','shrink','rename','replace','membership'):
            with self.subTest(mutation=mutation):
                path=self.data/'state/changing'; path.write_bytes(b'old bytes')
                original=os.read; changed=[False]; inode=path.stat().st_ino
                def read(fd,size):
                    raw=original(fd,size)
                    if os.fstat(fd).st_ino==inode and not changed[0]:
                        changed[0]=True
                        if mutation=='grow':
                            with path.open('ab') as output: output.write(b'new bytes')
                        elif mutation=='shrink': path.write_bytes(b'x')
                        elif mutation=='rename': path.rename(self.data/'state/moved')
                        elif mutation=='replace':
                            replacement=self.data/'state/replacement'; replacement.write_bytes(b'new file'); replacement.replace(path)
                        else: (self.data/'state/late-member').write_bytes(b'concurrent membership')
                    return raw
                with patch.object(os,'read',side_effect=read):
                    with self.assertRaises((ValueError,OSError)): self.tree.inventory(self.data)
                for extra in ('changing','moved','late-member','replacement'):
                    if (self.data/'state'/extra).exists(): (self.data/'state'/extra).unlink()

    def test_actual_unix_socket_and_mocked_device_owner_acl_capability_refuse(self):
        bad=self.data/'state/bad'
        with socket.socket(socket.AF_UNIX) as channel:
            channel.bind(str(bad))
            with self.assertRaises(ValueError): self.tree.inventory(self.data)
        bad.unlink(); bad.write_bytes(b'ordinary')
        for attributes in ({'st_mode':stat.S_IFCHR|0o600},{'st_mode':stat.S_IFBLK|0o600},
                           {'st_uid':os.geteuid()+10000},{'st_gid':os.getegid()+10000}):
            real=os.stat
            def info(path,*args,**kwargs):
                value=real(path,*args,**kwargs)
                if str(path)=='bad':
                    return SimpleNamespace(**{name:getattr(value,name) for name in dir(value) if name.startswith('st_')}|attributes)
                return value
            with patch.object(os,'stat',side_effect=info):
                with self.assertRaises(ValueError): self.tree.inventory(self.data)
        for name in ('system.posix_acl_access','security.capability'):
            with patch.object(os,'listxattr',return_value=[name]):
                with self.assertRaises(ValueError): self.tree.inventory(self.data)

    def test_fsync_eio_and_interruption_leave_only_unsealed_partial_clone(self):
        index=self.tree.inventory(self.data)
        for error in (OSError(errno.EIO,'fixture fsync failure'),InterruptedError('fixture interrupted copy')):
            destination=self.base/('partial-'+type(error).__name__)
            with patch.object(os,'fsync',side_effect=error):
                with self.assertRaises(type(error)): self.tree.clone(self.data,destination,index)
            self.assertEqual(self.tree.inventory(self.data),index)
            self.assertNotEqual(self.tree.inventory(destination),index)

    def test_clone_replacement_after_inventory_never_returns_complete_snapshot(self):
        path=self.data/'state/quota.json'; index=self.tree.inventory(self.data)
        inventory=self.tree.inventory; before=[False]
        def scanned(root,seal=True):
            result=inventory(root,seal)
            if Path(root)==self.data and not before[0]:
                before[0]=True; path.write_bytes(b'changed after sealed inventory')
            return result
        with patch.object(self.tree,'inventory',side_effect=scanned):
            with self.assertRaises(ValueError): self.tree.clone(self.data,self.base/'changed-clone',index)
        index['schema']=2
        with self.assertRaises(ValueError): self.tree.validate(index)


if __name__ == '__main__': unittest.main()
