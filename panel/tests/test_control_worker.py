"""Injected serial only; never enumerates or opens hardware."""
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_worker import Controller


class FakeSerial:
    in_waiting = 0
    def __init__(self):
        self.writes = []
        self.closed = False
    def write(self, data):
        self.writes.append(data)
        return len(data)
    def read(self, size):
        return b''
    def close(self):
        self.closed = True


class ControlTest(unittest.TestCase):
    def setUp(self):
        self.t = 10.0
        self.fake = FakeSerial()
        self.temp = tempfile.TemporaryDirectory(prefix='fly_panel_')
        self.c = Controller(lambda _: None, lambda: self.t,
                            lambda: ('FAKE', self.fake), Path(self.temp.name))
    def tearDown(self):
        self.c.disconnect()
        self.temp.cleanup()
    def ready(self):
        self.c.command('connect', True)
        self.c.latest = dict(received=self.t, reserved_valid=True, zero_ack=True,
            last_acks=10, fault=False, fault_code=0, flags=35, session=15,
            model_step=1, source_seq=1, yaw_q20=1048576,
            result_age_cycles=0, adopted_age_cycles=0, acked_left=0, acked_right=0)
        self.c.control.update(self.c.latest)
    def test_no_connection_or_enable_on_import_or_start(self):
        self.assertFalse(self.c.snapshot()['connected'])
        self.assertEqual(self.fake.writes, [])
        with self.assertRaises(ValueError):
            self.c.command('arm', True)
    def test_connect_requires_raised_and_only_sends_stop(self):
        with self.assertRaises(ValueError):
            self.c.command('connect')
        self.c.command('connect', True)
        self.assertEqual(self.fake.writes, [b'S'])
    def test_connect_accepts_fpga_only_without_driver_usb(self):
        self.c.factory = None
        self.fake.open = Mock()
        fpga = SimpleNamespace(device='COM_FAKE', vid=0x1a86, pid=0x7523)
        with patch('serial.tools.list_ports.comports', return_value=[fpga]), \
                patch('serial.Serial', return_value=self.fake) as serial_ctor:
            self.c.command('connect', True)
        self.assertEqual(self.c.port, 'COM_FAKE')
        self.fake.open.assert_called_once()
        serial_ctor.assert_called_once()
        self.assertEqual(self.fake.writes, [b'S'])
        self.assertFalse(self.c.snapshot()['can_arm'])
    def test_driver_usb_alone_does_not_replace_fpga_uart(self):
        self.c.factory = None
        driver = SimpleNamespace(device='COM_DRIVER_ONLY', vid=0x1a86, pid=0x7522)
        with patch('serial.tools.list_ports.comports', return_value=[driver]), \
                patch('serial.Serial') as serial_ctor:
            with self.assertRaises(RuntimeError):
                self.c.command('connect', True)
        serial_ctor.assert_not_called()
        self.assertFalse(self.c.snapshot()['connected'])
    def test_continuous_arm_survives_eight_seconds_and_stops_only_on_close(self):
        self.ready()
        self.c.command('arm', True)
        self.c.control.tick()
        self.assertEqual(self.fake.writes[-1], b'E')
        for elapsed in [.1, 8.1, 60, 180]:
            self.t = 10 + elapsed
            self.c.command('heartbeat')
            self.c.latest.update(received=self.t, flags=39)
            self.c.control.update(self.c.latest)
            self.assertTrue(self.c.snapshot()['enabled'])
            self.assertEqual(self.fake.writes, [b'S', b'E'])
        self.c.command('stop')
        self.c.control.tick()
        self.assertEqual(self.fake.writes[-1], b'S')
        self.assertIsNone(self.c.control.enable_at)
        self.assertFalse(self.c.snapshot()['enabled'])
        self.c.command('heartbeat')
        self.c.control.update(self.c.latest)
        self.assertEqual(self.fake.writes.count(b'E'), 1)
    def test_wait_for_neural_activity_does_not_expire_after_five_seconds(self):
        self.ready()
        self.c.latest['yaw_q20'] = 0
        self.c.command('arm', True)
        for elapsed in [1, 6, 60]:
            self.t = 10 + elapsed
            self.c.command('heartbeat')
            self.c.latest['received'] = self.t
            self.c.control.update(self.c.latest)
            self.assertTrue(self.c.snapshot()['pending'])
            self.assertNotIn(b'E', self.fake.writes)
        self.c.latest['yaw_q20'] = 1048576
        self.c.control.update(self.c.latest)
        self.assertEqual(self.fake.writes[-1], b'E')
    def test_continuous_arm_still_stops_on_stale_telemetry(self):
        self.ready()
        self.c.command('arm', True)
        self.c.control.tick()
        self.t += .31
        self.c.command('heartbeat')
        self.c.control.tick()
        self.assertEqual(self.fake.writes[-1], b'S')
        self.assertFalse(self.c.snapshot()['enabled'])
    def test_stale_status_cancels_waiting_and_fresh_status_cannot_reopen(self):
        self.ready()
        self.c.latest['yaw_q20'] = 0
        self.c.command('arm', True)
        self.t += .31
        self.c.command('heartbeat')
        self.c.control.tick()
        self.assertFalse(self.c.snapshot()['enabled'])
        self.c.latest.update(received=self.t, yaw_q20=1048576)
        self.c.control.update(self.c.latest)
        self.assertNotIn(b'E', self.fake.writes)
    def test_stale_or_faulted_status_cannot_arm(self):
        self.ready()
        self.t += .31
        with self.assertRaises(ValueError):
            self.c.command('arm', True)
        self.c.latest['received'] = self.t
        self.c.latest['fault'] = True
        with self.assertRaises(ValueError):
            self.c.command('arm', True)
        self.assertNotIn(b'E', self.fake.writes)
    def test_page_loss_stops_and_does_not_rearm_on_heartbeat(self):
        self.ready()
        self.c.command('arm', True)
        self.c.control.tick()
        self.t += 1.6
        self.c.step()
        self.assertEqual(self.fake.writes[-1], b'S')
        n = self.fake.writes.count(b'E')
        self.c.command('heartbeat')
        self.c.step()
        self.assertEqual(self.fake.writes.count(b'E'), n)
        self.assertIsNone(self.c.control.pending_until)
    def test_stop_cancels_pending_and_disconnect_stops(self):
        self.ready()
        self.c.command('arm', True)
        self.c.command('stop')
        self.c.control.tick()
        self.assertNotIn(b'E', self.fake.writes)
        self.c.command('disconnect')
        self.assertEqual(self.fake.writes[-1], b'S')
        self.assertTrue(self.fake.closed)
    def test_no_arbitrary_serial_command_or_bench(self):
        for cmd in ['B', 'bench', 'pwm', 'flash']:
            with self.assertRaises(ValueError):
                self.c.command(cmd, True)
        self.assertEqual(self.fake.writes, [])

    def test_bus_fault_remains_visible_after_manual_stop_and_lease_loss(self):
        self.ready()
        self.c.latest.update(fault=True, fault_code=3)
        self.c.command('stop')
        for lease in (self.t, None):
            self.c.lease = lease
            status = self.c.snapshot()
            self.assertTrue(status['i2c_fault'])
            self.assertIn('I2C_NACK', status['message'])
            self.assertFalse(status['zero_confirmed'])
            self.assertFalse(status['can_arm'])

    def test_later_zero_ack_does_not_hide_latched_bus_fault(self):
        self.ready()
        self.c.latest.update(fault=True, fault_code=2, last_acks=10,
                             acked_left=0, acked_right=0)
        status = self.c.snapshot()
        self.assertTrue(status['i2c_fault'])
        self.assertIn('SCL_TIMEOUT', status['message'])
        self.assertFalse(status['zero_confirmed'])

    def test_normal_zero_status_and_disconnect_are_not_bus_faults(self):
        self.ready()
        self.assertTrue(self.c.snapshot()['zero_confirmed'])
        self.assertFalse(self.c.snapshot()['i2c_fault'])
        self.c.disconnect()
        self.assertFalse(self.c.snapshot()['i2c_fault'])


if __name__ == '__main__':
    unittest.main()
