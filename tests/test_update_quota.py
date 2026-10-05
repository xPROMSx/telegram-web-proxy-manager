"""Persisted quota semantics shared by rehearsal and restart acceptance."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('quota_safety',ROOT/'lib/safety.py')
s=importlib.util.module_from_spec(spec); sys.modules[spec.name]=s; spec.loader.exec_module(s)


def state(top=0,used=8192,reset=1700000000):
    return dict(last_reset_epoch_secs=top,users={'web-user':dict(used_bytes=used,last_reset_epoch_secs=reset)})


class QuotaPreservationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'telemt.limit.json'; self.uid=os.getuid()

    def write(self,value):
        self.path.write_text(json.dumps(value)); self.path.chmod(0o600)

    def test_empty_live_or_missing_old_state_allows_empty_canonicalization(self):
        for old in (None,dict(last_reset_epoch_secs=0,users={})):
            s.update_quota_preserve(old,self.path,self.uid)
            self.write(dict(last_reset_epoch_secs=1700000000,users={}))
            s.update_quota_preserve(old,self.path,self.uid)
            self.path.unlink()

    def test_noncanonical_top_level_is_derived_and_user_semantics_survive(self):
        old=state(); self.write(state(top=1700000000,used=8193))
        s.update_quota_preserve(old,self.path,self.uid)

    def test_user_decrease_disappearance_and_actual_reset_change_fail(self):
        for new in (state(used=8191),dict(last_reset_epoch_secs=1700000000,users={}),state(reset=1700000001)):
            self.write(new)
            with self.subTest(new=new),self.assertRaises(ValueError):
                s.update_quota_preserve(state(),self.path,self.uid)

    def test_relied_upon_quota_missing_malformed_or_unsafe_fails_closed(self):
        with self.assertRaises(FileNotFoundError): s.update_quota_preserve(state(),self.path,self.uid)
        for value in ({},state(top='bad'),state(used=-1),state(reset=True)):
            self.write(value)
            with self.assertRaises(ValueError): s.update_quota_preserve(state(),self.path,self.uid)
        self.write(state()); self.path.chmod(0o666)
        with self.assertRaises(ValueError): s.update_quota_preserve(state(),self.path,self.uid)
        self.path.unlink(); self.path.symlink_to(Path(self.temp.name)/'missing')
        with self.assertRaises(OSError): s.update_quota_read(self.path,self.uid)

    def test_existing_malformed_old_state_is_not_treated_as_empty(self):
        self.path.write_bytes(b'not JSON'); self.path.chmod(0o600)
        with self.assertRaises(ValueError): s.update_quota_read(self.path,self.uid)


if __name__=='__main__': unittest.main()
