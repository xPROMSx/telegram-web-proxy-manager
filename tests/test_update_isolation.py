"""Effective leaf-cgroup I/O contract, including partition-backed roots."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('isolation_safety',ROOT/'lib/safety.py')
s=importlib.util.module_from_spec(spec); sys.modules[spec.name]=s; spec.loader.exec_module(s)

GOOD='253:0 rbps=max wbps=4194304 riops=max wiops=max\n'


class IsolationIOTests(unittest.TestCase):
    def test_effective_write_limit_accepts_systemd_backing_device(self):
        for device in ('253:0','8:0','259:17'):
            s.update_isolated_io_contract(GOOD.replace('253:0',device))

    def test_missing_or_wrong_write_limit_refused(self):
        for raw in ('',GOOD.replace('wbps=4194304','wbps=max'),
                    GOOD.replace('wbps=4194304','wbps=4194305'),
                    GOOD.replace(' wbps=4194304','')):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                s.update_isolated_io_contract(raw)

    def test_malformed_ambiguous_or_extra_effective_limits_refused(self):
        for raw in ('malformed\n',GOOD.replace('253:0','invalid'),
                    GOOD.replace('riops=max','wbps=4194304'),
                    GOOD.replace('riops=max','riops=1'),
                    GOOD+'8:0 rbps=max wbps=4194304 riops=max wiops=max\n',
                    GOOD+'\n',GOOD.replace('wiops=max','wiops=max unknown=max')):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                s.update_isolated_io_contract(raw)

    def run_to_io_boundary(self, values):
        class AcceptedIO(Exception): pass
        identity=json.dumps(dict(schema=1,uid=999,gid=999)).encode()
        # Conditional filesystem device is 253:1; consulting st_dev to select
        # an io.max row is forbidden. The effective backing device is 253:0.
        filesystem_device=s.os.makedev(253,1)
        self.assertNotEqual(f'{s.os.major(filesystem_device)}:{s.os.minor(filesystem_device)}',GOOD.split()[0])
        with patch.object(s,'update_private_directory'), patch.object(s,'update_read',return_value=identity), \
             patch.object(s.os,'geteuid',return_value=0), patch.object(s.os,'getpid',return_value=1), \
             patch.object(Path,'read_text',autospec=True,side_effect=lambda path: values[str(path)]), \
             patch.object(Path,'stat',side_effect=AssertionError('must not guess backing device from st_dev')), \
             patch.object(s.os.environ,'clear',side_effect=AcceptedIO):
            with self.assertRaises(AcceptedIO): s.update_isolated_run('/trusted/private/root','3.5.12','parseonly')

    def values(self):
        leaf='/sys/fs/cgroup/system.slice/test.service/'
        return {'/proc/self/cgroup':'0::/system.slice/test.service\n',
                leaf+'memory.max':str(1024**3)+'\n',leaf+'pids.max':'4096\n',
                leaf+'cpu.max':'200000 100000\n',leaf+'io.max':GOOD}

    def test_partition_device_mismatch_passes_actual_isolated_entry(self):
        self.run_to_io_boundary(self.values())

    def test_other_resource_limits_remain_strict(self):
        for resource,bad in (('memory.max','max'),('pids.max','4097'),('cpu.max','100000 100000')):
            values=self.values(); values['/sys/fs/cgroup/system.slice/test.service/'+resource]=bad
            with self.subTest(resource=resource),self.assertRaises(ValueError): self.run_to_io_boundary(values)


if __name__=='__main__': unittest.main()
