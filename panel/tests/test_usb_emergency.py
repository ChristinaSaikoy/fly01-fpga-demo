import sys,unittest,tempfile,struct
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from control_worker import Controller
from emergency_usb_stop import stop_driver
from test_control_worker import FakeSerial

class UsbStopTest(unittest.TestCase):
 def make(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.s=FakeSerial();self.usb=Mock(return_value=dict(ok=True,physical_stop_confirmed=False))
  c=Controller(lambda _:None,lambda:10.,lambda:('FAKE',self.s),Path(self.tmp.name),self.usb)
  self.addCleanup(c.disconnect);c.command('connect',True);return c
 def test_manual_stop_uses_usb_even_without_fpga(self):
  c=self.make();c.disconnect();self.usb.reset_mock();c.command('stop');self.usb.assert_called_once()
 def test_uart_write_failure_still_sends_usb_zero(self):
  c=self.make();c.control.write=Mock(side_effect=OSError('UART lost'))
  with self.assertRaises(OSError):c.command('stop')
  self.usb.assert_called_once();c.control.write=self.s.write
 def test_fault_triggers_once_and_never_enables(self):
  c=self.make();payload=bytearray(64);struct.pack_into('<IIi7I',payload,0,1,0,0,0,0,43,0,0,0,0)
  payload[44:48]=b'I2C5';payload[48]=0;payload[49]=11;payload[50]=2
  payload[52:54]=(1800).to_bytes(2,'little')
  payload[61:64]=((1<<22)|(1800<<10)|400).to_bytes(3,'little')
  c.parser=SimpleNamespace(bad=0,feed=lambda _:[(6,24,1,bytes(payload))]);c.step();c.step()
  self.usb.assert_called_once();self.assertNotIn(b'E',self.s.writes)
  self.assertTrue(c.snapshot()['i2c_fault']);self.assertFalse(c.snapshot()['zero_confirmed'])
 def test_stale_telemetry_uses_independent_usb_stop(self):
  c=self.make();c.clock=lambda:10.4;c.lease=10.4
  c.latest=dict(received=10.,reserved_valid=True,zero_ack=True,last_acks=10,fault=False,
     fault_code=0,flags=39,session=24,model_step=1,source_seq=1,yaw_q20=1,
     result_age_cycles=0,adopted_age_cycles=0,acked_left=-1200,acked_right=1600)
  c.control.latest=c.latest;c.control.enable_at=10.;c.control.armed_seen=True
  c.control.clock=lambda:10.4;c.step();self.usb.assert_called_once()
  self.assertFalse(c.snapshot()['enabled'])
 def test_usb_only_sends_zero_without_dtr_reset(self):
  con=Mock();con.write.return_value=13;con.is_open=True
  with patch('serial.tools.list_ports.comports',return_value=[SimpleNamespace(device='FAKE',vid=0x1a86,pid=0x7522)]),patch('serial.Serial',return_value=con):
   result=stop_driver()
  self.assertTrue(result['ok']);self.assertFalse(result['physical_stop_confirmed'])
  self.assertEqual([x.args[0] for x in con.write.call_args_list],[b'$pwm:0,0,0,0#']*3)
  self.assertFalse(con.dtr);self.assertFalse(con.rts);con.close.assert_called_once()
 def test_absent_or_busy_usb_fails_visibly(self):
  with patch('serial.tools.list_ports.comports',return_value=[]):self.assertFalse(stop_driver()['ok'])
  con=Mock();con.open.side_effect=OSError('busy');con.is_open=False
  with patch('serial.tools.list_ports.comports',return_value=[SimpleNamespace(device='FAKE',vid=0x1a86,pid=0x7522)]),patch('serial.Serial',return_value=con):self.assertFalse(stop_driver()['ok'])
if __name__=='__main__':unittest.main()
