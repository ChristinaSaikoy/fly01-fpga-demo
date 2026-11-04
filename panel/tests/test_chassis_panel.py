import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_control_worker import ControlTest
from control_worker import process_commands


class ChassisTest(ControlTest):
    def test_inspection_parks_without_nonzero_or_enable(self):
        self.ready()
        self.c.driver_inspect = Mock(return_value=dict(ok=True, battery_v=5.8, motor_type=4))
        self.c.command('inspect_chassis', True)
        self.assertEqual(self.c.chassis_check['battery_v'], 5.8)
        self.assertEqual(self.fake.writes, [b'S', b'S'])
        self.assertFalse(self.c.snapshot()['enabled'])

    def test_fixed_pulse_is_explicit_bounded_and_neural_exclusive(self):
        self.ready()
        self.c.latest['motion_build'] = True
        for level in (1200, 1600, 1800):
            self.c.command('chassis_test', True, level=level)
            self.assertEqual(self.fake.writes[-1], {1200:b'1B',1600:b'2B',1800:b'3B'}[level])
            self.assertFalse(self.c.snapshot()['can_arm'])
            with self.assertRaises(ValueError):
                self.c.command('arm', True)
            self.t += 1.01
            self.c.command('heartbeat')
            self.c.control.tick()
            self.assertEqual(self.fake.writes[-1], b'S')
            self.assertIsNone(self.c.control.bench_at)
            self.c.latest['received'] = self.t
        self.assertNotIn(b'E', self.fake.writes)

    def test_pulse_rejects_no_confirmation_bad_levels_and_zero_only_firmware(self):
        self.ready()
        for level in (0, 2000, True, '1800'):
            with self.assertRaises(ValueError):
                self.c.command('chassis_test', True, level=level)
        self.c.latest['motion_build'] = True
        with self.assertRaises(ValueError):
            self.c.command('chassis_test', False, level=1800)
        self.c.latest['motion_build'] = False
        with self.assertRaises(ValueError):
            self.c.command('chassis_test', True, level=1800)
        self.assertEqual(self.fake.writes, [b'S'])

    def test_stop_wins_same_command_batch(self):
        self.ready()
        self.c.latest['motion_build'] = True
        replies=[]
        process_commands(self.c,[dict(cmd='chassis_test',raised=True,level=1800),dict(cmd='stop')],replies.append)
        self.assertEqual(self.fake.writes,[b'S',b'S'])
        self.assertTrue(any(not r['ok'] for r in replies))

    def test_subinteger_neural_output_can_open_r13(self):
        self.ready()
        self.c.latest['yaw_q20'] = -1
        self.c.control.update(self.c.latest)
        self.c.command('arm', True)
        self.c.control.tick()
        self.assertEqual(self.fake.writes[-1], b'E')


if __name__ == '__main__':
    unittest.main()
