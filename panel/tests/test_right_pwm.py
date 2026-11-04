"""Right PWM readback and cancellation without hardware access."""
import sys,struct,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from control_worker import Controller,process_commands
from test_control_worker import FakeSerial
from i2c_console import decode_status

class PwmTest(unittest.TestCase):
    def setUp(self):
        self.t=10.;self.serial=FakeSerial();self.tmp=tempfile.TemporaryDirectory()
        self.c=Controller(lambda _:None,lambda:self.t,lambda:('FAKE',self.serial),Path(self.tmp.name))
        self.c.command('connect',True)
        self.c.latest=dict(received=self.t,reserved_valid=True,zero_ack=True,last_acks=10,
            fault=False,fault_code=0,flags=35,session=23,model_step=100,source_seq=10,
            yaw_q20=1048576,result_age_cycles=0,adopted_age_cycles=0,
            acked_left=0,acked_right=0,frames=100,busy=False,pwm_adjust_supported=True,
            manual_retry_supported=True,retry_epoch=0,right_trim=400,right_cap=1800)
    def tearDown(self):
        self.c.disconnect();self.tmp.cleanup()
    def feed(self,**changes):
        self.c.latest.update(received=self.t,**changes)
        self.c.control.update(self.c.latest);self.c.update_pwm_request(self.c.latest)
    def configure(self):
        self.c.command('configure_pwm',True,trim=500,cap=1900)
    def test_invalid_values_are_rejected_before_any_config_write(self):
        for trim,cap in [(True,1800),(400,False),(-1,1800),(801,1800),(400,1199),(400,2001),(400.0,1800),('400',1800)]:
            with self.assertRaises(ValueError):self.c.command('configure_pwm',True,trim=trim,cap=cap)
        self.assertEqual(self.serial.writes,[b'S'])
    def test_confirmation_freshness_and_firmware_support_required(self):
        with self.assertRaises(ValueError):self.c.command('configure_pwm',False,trim=400,cap=1800)
        self.c.latest['pwm_adjust_supported']=False
        with self.assertRaises(ValueError):self.configure()
        self.c.latest['pwm_adjust_supported']=True;self.t+=.31
        with self.assertRaises(ValueError):self.configure()
    def test_config_stops_first_and_waits_for_zero_before_transmission(self):
        self.c.latest.update(flags=39,acked_left=-1500,acked_right=1800)
        self.configure();self.feed()
        self.assertEqual(self.serial.writes,[b'S',b'S'])
        self.feed(flags=35,acked_left=0,acked_right=0)
        self.assertEqual(self.serial.writes,[b'S',b'S',b'T0500,1900\n'])
        self.assertTrue(self.c.snapshot()['configuring_pwm'])
        with self.assertRaises(ValueError):self.c.command('arm',True)
        self.feed(right_trim=500,right_cap=1800)
        self.assertTrue(self.c.snapshot()['configuring_pwm'])
        self.feed(right_cap=1900)
        self.assertFalse(self.c.snapshot()['configuring_pwm'])
        self.assertFalse(self.c.snapshot()['enabled']);self.assertNotIn(b'E',self.serial.writes)
    def test_config_range_endpoints_are_transmitted_as_four_digits(self):
        self.c.command('configure_pwm',True,trim=0,cap=1200);self.feed()
        self.assertEqual(self.serial.writes[-1],b'T0000,1200\n')
        self.feed(right_trim=0,right_cap=1200)
        self.c.command('configure_pwm',True,trim=800,cap=2000);self.feed()
        self.assertEqual(self.serial.writes[-1],b'T0800,2000\n')
    def test_fault_during_config_fails_closed(self):
        self.configure();self.feed();self.feed(fault=True,fault_code=2)
        self.assertFalse(self.c.snapshot()['configuring_pwm']);self.assertFalse(self.c.snapshot()['can_arm'])
        self.assertNotIn(b'E',self.serial.writes)
    def test_config_timeout_never_claims_readback_success(self):
        self.configure();self.feed();self.t+=3.1;self.c.command('heartbeat');self.c.step()
        self.assertIsNone(self.c.pwm_request);self.assertIn('确认超时',self.c.control.message)
        self.assertNotIn(b'E',self.serial.writes)
    def test_stop_and_disconnect_cancel_config_before_transmission(self):
        self.configure();self.c.command('stop');self.feed();self.assertIsNone(self.c.pwm_request)
        self.configure();self.c.command('disconnect');self.assertIsNone(self.c.pwm_request)
        self.assertFalse(any(x.startswith(b'T') for x in self.serial.writes))
    def test_lease_loss_cancels_config(self):
        self.configure();self.t+=1.6;self.c.step();self.assertIsNone(self.c.pwm_request)
        self.assertFalse(any(x.startswith(b'T') for x in self.serial.writes))
    def test_stop_batch_prevents_retry_and_parameter_application(self):
        events=[]
        batch=[dict(id=1,cmd='configure_pwm',raised=True,trim=500,cap=1800),dict(id=2,cmd='retry',raised=True),dict(id=3,cmd='stop')]
        process_commands(self.c,batch,events.append)
        self.assertEqual([(e['id'],e['ok']) for e in events],[(3,True),(1,False),(2,False)])
        self.assertIsNone(self.c.pwm_request);self.assertIsNone(self.c.retry)
        self.assertEqual(self.serial.writes,[b'S',b'S'])

class DecoderTest(unittest.TestCase):
    def payload(self,config):
        p=bytearray(64);p[44:48]=b'I2C5';p[48]=10;p[49]=10
        p[52:54]=(1800).to_bytes(2,'little');p[61:64]=config.to_bytes(3,'little');return bytes(p)
    def test_version_and_fields_including_epoch(self):
        d=decode_status(self.payload((1<<22)|(1<<21)|(1900<<10)|500))
        self.assertTrue(d['reserved_valid']);self.assertTrue(d['pwm_adjust_supported'])
        self.assertEqual((d['right_trim'],d['right_cap'],d['retry_epoch']),(500,1900,1))
    def test_legacy_is_valid_but_does_not_claim_parameters_or_capability(self):
        d=decode_status(self.payload(0));self.assertTrue(d['reserved_valid'])
        self.assertFalse(d['manual_retry_supported']);self.assertIsNone(d['right_trim'])
    def test_invalid_version_and_ranges_are_rejected(self):
        for word in [1,(2<<22)|(1800<<10)|400,(1<<22)|(1800<<10)|801,(1<<22)|(1199<<10)|400]:
            self.assertFalse(decode_status(self.payload(word))['reserved_valid'])

if __name__=='__main__':unittest.main()
