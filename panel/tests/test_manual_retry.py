"""Manual retry lifecycle with injected serial; never opens hardware."""
import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from control_worker import Controller
from test_control_worker import FakeSerial

class RetryTest(unittest.TestCase):
    def setUp(self):
        self.t=10.;self.serial=FakeSerial();self.tmp=tempfile.TemporaryDirectory()
        self.c=Controller(lambda _:None,lambda:self.t,lambda:('FAKE',self.serial),Path(self.tmp.name))
        self.c.command('connect',True)
        self.c.latest=dict(received=self.t,reserved_valid=True,zero_ack=True,last_acks=10,
            fault=True,fault_code=2,flags=35,session=23,model_step=100,source_seq=10,
            yaw_q20=1048576,result_age_cycles=0,adopted_age_cycles=0,
            acked_left=0,acked_right=0,frames=100,busy=False,manual_retry_supported=True,retry_epoch=0)
    def tearDown(self):
        self.c.disconnect();self.tmp.cleanup()
    def feed(self,**changes):
        self.c.latest.update(received=self.t,**changes)
        self.c.control.update(self.c.latest)
        self.c.update_retry(self.c.latest)
    def begin(self):
        self.c.command('retry',True);self.feed()
        self.assertEqual(self.serial.writes,[b'S',b'S',b'R'])
    def test_retry_requires_confirmation_and_fresh_fault(self):
        with self.assertRaises(ValueError):self.c.command('retry',False)
        self.t+=.31
        with self.assertRaises(ValueError):self.c.command('retry',True)
        self.c.latest.update(received=self.t,fault=False,fault_code=0)
        with self.assertRaises(ValueError):self.c.command('retry',True)
        self.assertEqual(self.serial.writes,[b'S'])
    def test_reset_and_two_distinct_zero_transactions_required_no_auto_enable(self):
        self.begin()
        with self.assertRaises(ValueError):self.c.command('arm',True)
        self.feed(fault=False,fault_code=0,frames=0,zero_ack=False,last_acks=0,retry_epoch=1)
        self.feed(frames=1,zero_ack=True,last_acks=10)
        self.assertTrue(self.c.snapshot()['retrying'])
        self.feed(frames=1)
        self.assertTrue(self.c.snapshot()['retrying'])
        self.feed(frames=2)
        self.assertFalse(self.c.snapshot()['retrying'])
        self.assertTrue(self.c.snapshot()['can_arm'])
        self.assertFalse(self.c.snapshot()['enabled'])
        self.assertNotIn(b'E',self.serial.writes)
    def test_waits_for_disarmed_status_before_sending_retry(self):
        self.c.latest['flags']=39;self.c.command('retry',True)
        self.feed();self.assertNotIn(b'R',self.serial.writes)
        self.feed(flags=35);self.assertEqual(self.serial.writes[-1],b'R')
    def test_fault_after_reset_remains_locked(self):
        self.begin();self.feed(frames=1,fault=True,fault_code=1,retry_epoch=1)
        self.assertFalse(self.c.snapshot()['retrying'])
        self.assertTrue(self.c.snapshot()['i2c_fault'])
        self.assertFalse(self.c.snapshot()['can_arm'])
        self.assertEqual(self.serial.writes[-1],b'S')
    def test_old_firmware_cannot_be_declared_recovered(self):
        self.begin();self.feed(frames=101,fault=False,fault_code=0)
        self.assertTrue(self.c.snapshot()['retrying'])
        self.t+=3.1;self.c.command('heartbeat');self.c.step()
        self.assertIsNone(self.c.retry)
        self.assertIn('重试超时',self.c.control.message)
        self.assertNotIn(b'E',self.serial.writes)
    def test_first_frame_fault_recovery_uses_epoch_not_counter_wrap(self):
        self.c.latest['frames']=1
        self.begin()
        self.feed(frames=1,fault=False,fault_code=0,retry_epoch=1)
        self.assertTrue(self.c.snapshot()['retrying'])
        self.feed(frames=2)
        self.assertFalse(self.c.snapshot()['retrying'])
        self.assertNotIn(b'E',self.serial.writes)
    def test_old_firmware_is_rejected_without_retry_write(self):
        self.c.latest['manual_retry_supported']=False
        with self.assertRaises(ValueError):self.c.command('retry',True)
        self.assertNotIn(b'R',self.serial.writes)
    def test_manual_stop_cancels_pending_retry(self):
        self.c.command('retry',True);self.c.command('stop');self.feed()
        self.assertIsNone(self.c.retry);self.assertNotIn(b'R',self.serial.writes)
    def test_page_loss_cancels_pending_retry(self):
        self.c.command('retry',True);self.t+=1.6;self.c.step()
        self.assertIsNone(self.c.retry);self.assertNotIn(b'R',self.serial.writes)
    def test_disconnect_cancels_pending_retry(self):
        self.c.command('retry',True);self.c.disconnect()
        self.assertIsNone(self.c.retry);self.assertTrue(self.serial.closed)
        self.assertNotIn(b'R',self.serial.writes)

if __name__=='__main__':unittest.main()
