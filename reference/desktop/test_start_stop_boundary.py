"""Device-free regression of readiness consumption and stop/start ordering."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import app
import suite


class FakeWorker:
    def __init__(self, **kwargs): self.started=False
    def start(self): self.started=True
    def is_alive(self): return False


class StartStopBoundary(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.c=app.Controller(Path(self.temp.name)/'runs')
        self.c.confirmed_suite=True
        self.c.required_config={}
        self.c.arm_preview()
        self.identity=patch('app.version_hash',return_value='OFFLINE_BOUNDARY_FIXTURE')
        self.threads=patch('app.threading.Thread',FakeWorker)
        self.identity.start();self.threads.start()

    def tearDown(self):
        self.threads.stop();self.identity.stop()
        if self.c.journal:self.c.journal.close()
        self.temp.cleanup()

    def test_ready_then_stop_cannot_start(self):
        self.c.confirm_preview();self.c.stop()
        with self.assertRaises(PermissionError):self.c.start({})
        self.assertIsNone(self.c.worker)
        self.assertTrue(self.c.cancel.is_set())

    def test_stop_after_wait_return_cannot_start(self):
        self.c.confirm_preview()
        auth=dict(suite_id='OFFLINE_ONLY',mvp_scope={'suite_started_monotonic_ns':time.monotonic_ns()})
        suite.wait_for_operator(self.c,auth,Path(self.temp.name))
        self.c.stop()
        with self.assertRaises(PermissionError):self.c.start({})
        self.assertIsNone(self.c.worker)

    def test_ready_is_consumed_once(self):
        self.c.confirm_preview();self.c.start({})
        with self.assertRaises(PermissionError):self.c.start({})
        with self.assertRaises(PermissionError):self.c.confirm_preview()

    def test_expired_between_wait_and_start_is_rejected(self):
        self.c.confirm_preview()
        self.c.preview_start_deadline=time.monotonic()-1
        with self.assertRaises(TimeoutError):self.c.start({})
        self.assertIsNone(self.c.worker)

    def test_stop_during_validation_cancels_the_started_generation(self):
        self.c.confirm_preview()
        entered=threading.Event();release=threading.Event();failures=[]
        original=app.validate_config
        def validate(config):
            entered.set()
            if not release.wait(2):raise TimeoutError('fixture synchronization')
            return original(config)
        def run_start():
            try:self.c.start({})
            except BaseException as exc:failures.append(exc)
        # Capture real Thread before the app-level fake is installed.
        with patch('app.validate_config',validate):
            starter=REAL_THREAD(target=run_start);starter.start()
            self.assertTrue(entered.wait(2))
            stopped=threading.Event()
            def run_stop():
                self.c.stop();stopped.set()
            stopper=REAL_THREAD(target=run_stop);stopper.start()
            time.sleep(.03);release.set()
            starter.join(2);stopper.join(2)
        self.assertFalse(starter.is_alive());self.assertFalse(stopper.is_alive())
        self.assertFalse(failures);self.assertTrue(stopped.is_set())
        self.assertTrue(self.c.cancel.is_set(),'stop must cancel the new run, not an abandoned Event')

    def test_confirmed_fault_recovery_remains_explicit_and_bounded(self):
        self.c.confirm_preview();self.c.start({})
        self.c.journal.close()
        self.c.phase='FAULT';self.c.cancel.set();self.c.recovery_session=123
        self.c.recover()
        self.assertEqual(self.c.explicit_recoveries,1)
        self.assertTrue(self.c.worker.started)

    def test_unconfirmed_start_is_rejected(self):
        with self.assertRaises(PermissionError):self.c.start({})
        self.assertIsNone(self.c.worker)

    def test_deadline_expiring_during_validation_is_rejected(self):
        self.c.confirm_preview();self.c.preview_start_deadline=time.monotonic()+60
        original=app.validate_config
        def validate(config):
            self.c.preview_start_deadline=time.monotonic()-1
            return original(config)
        with patch('app.validate_config',validate):
            with self.assertRaises(TimeoutError):self.c.start({})
        self.assertIsNone(self.c.worker)


REAL_THREAD=threading.Thread

if __name__=='__main__':unittest.main(verbosity=2)
