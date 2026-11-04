"""Exercise real frozen prefix fixtures with a simulated adapter; no serial port."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
import targeted


class FixtureAdapter:
    def __init__(self, fault=None):
        self.generation=0;self.transport=self;self.rows=[];self.calls=0;self.fault=fault
        inputs=targeted.FORMAL_ROOT/'formal_inputs'
        for name in ('single','sequence20'):
            with (inputs/(name+'_expected.csv')).open(encoding='utf-8') as stream:
                self.rows.extend(list(csv.reader(stream)))
    def reset(self):self.generation+=1
    def formal(self,generation,frame,events,enable,full):
        if not full:raise AssertionError('Minimal snapshots must never be selected')
        r=self.rows[self.calls];self.calls+=1
        got=dict(completed_id=int(r[4]),acc_sat=int(r[5]),state_sat=int(r[6]),overflow=int(r[7]),drop=int(r[8]),
                 cycles=int(r[9])+17,states=[int(x,16) for x in r[10:481]],counts=[int(x,16) for x in r[481:]])
        if self.calls==3 and self.fault=='state':got['states'][0]^=1
        if self.calls==3 and self.fault=='length':got['counts'].pop()
        return got


class TargetedChecks(unittest.TestCase):
    def test_all_21_full_snapshots_and_historical_full_not_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter=FixtureAdapter()
            r=targeted.run_short(adapter,tmp,origin='SOFTWARE_FIXTURE_NOT_HARDWARE')
            self.assertEqual(adapter.calls,21);self.assertEqual(r['prefix_steps'],21)
            self.assertEqual(r['formal_steps'],0);self.assertEqual(r['formal_regression'],'NOT_RUN_THIS_SUITE')
            self.assertEqual(r['origin'],'SOFTWARE_FIXTURE_NOT_HARDWARE')
            self.assertEqual(len((Path(tmp)/'formal_capture.jsonl').read_text().splitlines()),21)

    def test_state_mismatch_stops_at_first_divergence(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter=FixtureAdapter('state')
            with self.assertRaisesRegex(RuntimeError,'FIRST_DIVERGENCE'):
                targeted.run_short(adapter,tmp,origin='SOFTWARE_FIXTURE_NOT_HARDWARE')
            self.assertEqual(adapter.calls,3)
            self.assertFalse((Path(tmp)/'FORMAL_RESULT.json').exists())

    def test_incomplete_snapshot_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError,'complete read count'):
                targeted.run_short(FixtureAdapter('length'),tmp,origin='SOFTWARE_FIXTURE_NOT_HARDWARE')


if __name__=='__main__':unittest.main(verbosity=2)
