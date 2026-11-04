"""All device interactions below are test doubles. No real camera/UART/JTAG."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import numpy as np
import app
import camera
from calibration import marker, CONVENTION
from identity import ROOT, verify
from neural import ClosingTransport
from test_mvp import observation, InjectionPort, client
from packed10 import make_packet

DEVICE=dict(name='HD Webcam',index=4,backend='DSHOW',symbolic_link=r'\\?\usb#vid_04f2&pid_b7dd&mi_00#TEST_FIXTURE_ONLY')

def camera_auth(path):
    value=dict(status='APPROVED_CAMERA_PREVIEW',execution_host=__import__('socket').gethostname(),
        camera_index=4,scope='LOCAL_PREVIEW_NO_RAW_RECORDING',work13_confirmed=True,
        user_confirmation_source='SOFTWARE_TEST_FIXTURE_ONLY_NOT_USER_PERMISSION',
        device_name=DEVICE['name'],symbolic_link=DEVICE['symbolic_link'])
    path.write_text(json.dumps(value),encoding='utf-8')
    return dict(source='camera',camera_index=4,camera_approval=str(path),backend='reference')

class FakeCapture:
    def __init__(self,*args):self.args=args;self.active=True;self.reads=0
    def isOpened(self):return self.active
    def getBackendName(self):return 'DSHOW'
    def set(self,*args):return True
    def read(self):self.reads+=1;return True,np.zeros((48,64,3),np.uint8)
    def release(self):self.active=False

class Work13Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):(ROOT/'test_temp').mkdir(exist_ok=True)
    def test_candidate_and_old_bit_offline(self):self.assertTrue(verify()['requires_new_combined_confirmation'])
    def test_exact_camera_binding_not_old_index_or_ir(self):
        selected=camera.bind([dict(DEVICE,index=9)],name=DEVICE['name'],symbolic_link=DEVICE['symbolic_link'])
        self.assertEqual(selected['index'],9)
        for devices in ([],[DEVICE,DEVICE],[dict(DEVICE,name='IR Camera')]):
            with self.assertRaises(PermissionError):camera.bind(devices,name=DEVICE['name'],symbolic_link=DEVICE['symbolic_link'])
    def test_camera_open_uses_exact_backend_and_releases(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'test_temp') as folder:
            config=camera_auth(Path(folder)/'FAKE_AUTH.json');cap=FakeCapture();cancel=threading.Event()
            with patch('cv2.videoio_registry.hasBackend',return_value=True):
                gen=camera.frames(config,cancel,enumerate_fn=lambda:[DEVICE],capture_factory=lambda *a:cap)
                rgb,source,stamp=next(gen);cancel.set();self.assertEqual(list(gen),[])
            self.assertFalse(cap.active);self.assertEqual(source['backend'],'DSHOW');self.assertIsNone(source['capture_time_ns'])
            self.assertEqual(rgb.shape,(48,64,3))
    def test_mapping_changed_and_old_permission_never_open(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'test_temp') as folder:
            path=Path(folder)/'FAKE_AUTH.json';config=camera_auth(path)
            factory=__import__('unittest.mock',fromlist=['Mock']).Mock()
            with self.assertRaises(PermissionError):next(camera.frames(config,threading.Event(),enumerate_fn=lambda:[dict(DEVICE,index=3)],capture_factory=factory))
            factory.assert_not_called()
            auth=json.loads(path.read_text());del auth['work13_confirmed'];path.write_text(json.dumps(auth))
            with self.assertRaises(PermissionError):app.validate_config(config)
    def test_stage_directions_loss_and_mismatch_are_distinct(self):
        now=time.monotonic_ns()
        for label,phase in [('LEFT','LEFT'),('RIGHT','RIGHT'),('CENTER','CENTER'),('NO_TARGET','REMOVED')]:
            status=dict(phase='RUNNING',observation=observation(label,now=now),model_step=3)
            row=marker(status,phase,'TEST_OPERATOR',True,False,now)
            self.assertEqual(row['input_check'],'INPUT_MATCH');self.assertEqual(row['coordinate_convention'],CONVENTION)
            self.assertFalse(row['neural_output_turning_validated'])
        status['observation']=observation('AMBIGUOUS',now=now)
        self.assertEqual(marker(status,'REMOVED','TEST',True,False,now)['input_check'],'INPUT_MISMATCH')
    def test_stage_mirror_stale_and_confirmation(self):
        now=time.monotonic_ns();status=dict(phase='RUNNING',observation=observation('LEFT',now=now,mirror=True))
        self.assertEqual(marker(status,'LEFT','TEST',True,True,now)['input_check'],'INPUT_MISMATCH')
        self.assertEqual(marker(status,'RIGHT','TEST',True,True,now)['input_check'],'INPUT_MATCH')
        self.assertEqual(marker(status,'RIGHT','TEST',True,True,now+250_000_000)['input_check'],'UNVERIFIED')
        with self.assertRaises(ValueError):marker(status,'LEFT','TEST',False,False,now)
    def test_normal_close_releases_owner_and_uncertain_close_does_not(self):
        p=InjectionPort();c=client(p);p.close=lambda:setattr(p,'closed',True)
        ClosingTransport(c).close();self.assertEqual(p.owner,0);self.assertTrue(p.closed)
        p=InjectionPort();c=client(p);p.close=lambda:setattr(p,'closed',True)
        c.frame(make_packet(c.generation,0,[1]),0)
        ClosingTransport(c).close();self.assertNotEqual(p.owner,0);self.assertTrue(p.closed)
    def test_locked_suite_cannot_silently_select_reference_or_flip(self):
        c=app.Controller();c.required_config=dict(source='camera',backend='fpga',sensor_mirror_x=False)
        with self.assertRaises(PermissionError):c.start(dict(source='camera',backend='reference',sensor_mirror_x=False))
        with self.assertRaises(PermissionError):c.start(dict(source='camera',backend='fpga',sensor_mirror_x=True))
        with self.assertRaises(PermissionError):c.recover()
    def test_suite_default_and_old_permission_cannot_open_devices(self):
        import suite
        with tempfile.TemporaryDirectory(dir=ROOT/'test_temp') as folder:
            path=Path(folder)/'FAKE_OLD_AUTH.json';path.write_text(json.dumps(dict(status='APPROVED_EXACT_ARTIFACT')))
            with patch('uart_windows.WindowsPort.open_approved') as op:
                with self.assertRaises(PermissionError):suite.approval(path)
                op.assert_not_called()
    def test_software_camera_to_neural_integration_with_stage_log(self):
        import replay
        with tempfile.TemporaryDirectory(dir=ROOT/'test_temp') as folder:
            folder=Path(folder);config=camera_auth(folder/'FAKE_AUTH.json')
            def synthetic_frames(c,cancel):
                k=0
                while not cancel.is_set():
                    now=time.monotonic_ns();rgb=np.zeros((61,101,3),np.uint8);rgb[26:35,16:25,0]=230
                    yield rgb,dict(kind='SOFTWARE_INJECTION_NOT_REAL_CAMERA',capture_time_ns=None,capture_time_verified=False),now
                    k+=1
                    if cancel.wait(.04):return
            c=app.Controller(folder/'runs')
            with patch('app.frames',synthetic_frames):
                c.start(config)
                deadline=time.monotonic()+4
                while c.stats['valid_target_feedback']<3 and time.monotonic()<deadline:time.sleep(.03)
                self.assertGreaterEqual(c.stats['valid_target_feedback'],3)
                result=c.mark(dict(phase='LEFT',operator='SOFTWARE_FIXTURE',confirmed=True))
                self.assertEqual(result['input_check'],'INPUT_MATCH')
                c.stop();c.worker.join(5)
            self.assertFalse(c.capture.is_alive());self.assertIsNone(c.jpeg)
            self.assertEqual(c.status()['phase'],'STOPPED');self.assertIsNone(c.status()['dn_slots'])
            r=replay.replay(c.folder);self.assertEqual(r['status'],'EXACT_MATCH')
    def test_owned_process_job_kills_only_waiting_test_child(self):
        import os,subprocess,sys
        if os.name!='nt':self.skipTest('Windows-only job object')
        from windows_job import OwnedJob
        job=OwnedJob();child=None
        try:
            child=subprocess.Popen([sys.executable,'-B','-c','import sys,time; sys.stdin.readline(); time.sleep(30)'],stdin=subprocess.PIPE,
                                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
            job.assign_waiting_child(child);child.stdin.write(b'FIXTURE\n');child.stdin.flush();child.stdin.close()
            self.assertGreaterEqual(job.active(),1);job.terminate();child.wait(5);self.assertEqual(job.active(),0)
        finally:
            job.close()
            if child and child.poll() is None:child.terminate();child.wait(5)
    def test_faulted_unresolved_input_is_kept_not_discarded(self):
        import replay
        from neural import NeuralRuntime
        from uart_host import LinkFault
        with tempfile.TemporaryDirectory(dir=ROOT/'test_temp') as folder:
            c=app.Controller(folder);runtime=NeuralRuntime.reference();normal=runtime.adapter.transact;calls=[]
            def fail_third(*args,**kwargs):
                calls.append(1)
                if len(calls)==3:raise LinkFault('SOFTWARE_INJECTED_UNCERTAIN_ACK')
                return normal(*args,**kwargs)
            runtime.adapter.transact=fail_third
            with patch('app.NeuralRuntime.reference',return_value=runtime):
                c.start({});c.worker.join(5)
            self.assertEqual(c.phase,'FAULT');self.assertIsNone(c.status()['dn_slots'])
            with self.assertRaises(AssertionError):replay.replay(c.folder)
            review=replay.replay(c.folder,allow_unresolved=True)
            self.assertEqual(review['unresolved_steps'],[2]);self.assertEqual(review['model_steps'],2)
            self.assertEqual(review['status'],'PARTIAL_EXACT_COMPLETED_WITH_UNCERTAIN')
    def test_ui_metadata_controls_and_host_guard(self):
        import urllib.request,urllib.error
        c=app.Controller();http=app.server(c);t=threading.Thread(target=http.serve_forever);t.start()
        url=f'http://127.0.0.1:{http.server_port}'
        try:
            with urllib.request.urlopen(url) as response:html=response.read().decode('utf-8')
            for label in ('data-phase="LEFT"','data-phase="RIGHT"','data-phase="CENTER"','data-phase="REMOVED"','explicitrecover'):
                self.assertIn(label,html)
            with urllib.request.urlopen(url+'/status') as response:s=json.load(response)
            self.assertFalse(s['physical_output']);self.assertEqual(s['model_dt_s'],.02)
            request=urllib.request.Request(url+'/status',headers={'Host':'example.invalid'})
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
            self.assertEqual(error.exception.code,403)
        finally:http.shutdown();http.server_close();t.join(3)
    def test_whole_worker_order_with_no_hardware_test_doubles(self):
        import io,os,suite
        with tempfile.TemporaryDirectory(dir=ROOT/'test_temp') as folder:
            folder=Path(folder);order=[];now=time.monotonic_ns()
            auth=dict(suite_id='FIXTURE_ONLY',uart_identity={'device':'FAKE_NEVER_OPEN'},mvp_scope={'suite_started_monotonic_ns':now})
            args=__import__('argparse').Namespace(approval=folder/'FAKE_AUTH.json',output=folder)
            def step(name,value):
                def call(*a,**k):order.append(name);return value
                return call
            def interact(*a):
                order.append('interaction');suite.dump(folder/'INTERACTION_EXIT.json',dict(camera_stream_window_s=180,
                    explicit_recoveries=0,status={'phase':'STOPPED'}))
            fake_review=[dict(run='FAKE_RUN',replay={'origin':'FPGA_UART','unresolved_steps':[]},camera_adopted_steps=10,physical_direction_check='PENDING_OPERATOR_STAGES')]
            with (patch.dict(os.environ,WORK13_OWNED_COOKIE='TEST_COOKIE'),patch('sys.stdin',io.StringIO('TEST_COOKIE\n')),
                patch('suite.approval',return_value=auth),patch('uart_windows.select_device',side_effect=step('identity',{})),
                patch('suite.program',side_effect=step('program','FAKE_RECEIPT')),patch('suite.regress',side_effect=step('regress',{'status':'SIMULATED_ONLY'})),
                patch('suite.interaction',side_effect=interact),patch('suite.review',side_effect=step('review',fake_review))):
                self.assertEqual(suite.worker(args),0)
            self.assertEqual(order,['identity','program','regress','interaction','review'])
    def test_failed_regression_never_opens_camera(self):
        import io,os,suite
        with tempfile.TemporaryDirectory(dir=ROOT/'test_temp') as folder:
            folder=Path(folder)
            auth=dict(suite_id='FIXTURE_ONLY',uart_identity={},mvp_scope={'suite_started_monotonic_ns':time.monotonic_ns()})
            args=__import__('argparse').Namespace(approval=folder/'FAKE_AUTH.json',output=folder)
            with (patch.dict(os.environ,WORK13_OWNED_COOKIE='TEST_COOKIE'),patch('sys.stdin',io.StringIO('TEST_COOKIE\n')),
                patch('suite.approval',return_value=auth),patch('uart_windows.select_device',return_value={}),
                patch('suite.program',return_value='FAKE_RECEIPT'),patch('suite.regress',side_effect=RuntimeError('INJECTED_FAIL')),
                patch('suite.interaction') as cam):
                self.assertEqual(suite.worker(args),1);cam.assert_not_called()

class TestOperatorReadyGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):(ROOT/'test_temp').mkdir(exist_ok=True)
    def armed(self):
        c=app.Controller();c.confirmed_suite=True
        c.required_config=dict(source='camera',backend='fpga')
        c.arm_preview()
        return c
    def test_gate_requires_confirmed_suite(self):
        c=app.Controller()
        with self.assertRaises(PermissionError):c.arm_preview()
        with self.assertRaises(PermissionError):c.confirm_preview()
    def test_waiting_does_not_start_devices_or_allow_direct_start(self):
        c=self.armed()
        self.assertEqual(c.status()['health'],'WAITING_FOR_OPERATOR')
        self.assertEqual(c.status()['source'],'REAL_CAMERA_PENDING_OPERATOR')
        self.assertTrue(c.status()['awaiting_operator'])
        with patch('app.hardware_runtime') as hardware,patch('app.frames') as frames:
            with self.assertRaises(PermissionError):c.start(c.required_config)
            hardware.assert_not_called();frames.assert_not_called()
        self.assertIsNone(c.worker);self.assertIsNone(c.capture);self.assertIsNone(c.config)
    def test_readiness_is_single_use_and_does_not_open_devices(self):
        c=self.armed();result=c.confirm_preview()
        self.assertEqual(result,dict(operator_ready=True,devices_opened=False))
        self.assertTrue(c.preview_gate.is_set());self.assertIsNone(c.worker)
        with self.assertRaises(PermissionError):c.confirm_preview()
        c=self.armed();c.stop()
        self.assertEqual(c.phase,'STOPPED')
        with self.assertRaises(PermissionError):c.confirm_preview()
    def test_wait_respects_original_suite_deadline_even_if_ready(self):
        import suite
        c=self.armed();c.confirm_preview()
        auth=dict(suite_id='OFFLINE_FIXTURE',mvp_scope={'suite_started_monotonic_ns':0})
        with patch('suite.time.monotonic',return_value=1371):
            with self.assertRaises(TimeoutError):suite.wait_for_operator(c,auth,ROOT/'test_temp')
        self.assertIsNone(c.worker)
    def test_wait_cancellation_does_not_start(self):
        import suite
        c=self.armed();c.stop()
        auth=dict(suite_id='OFFLINE_FIXTURE',mvp_scope={'suite_started_monotonic_ns':time.monotonic_ns()})
        with self.assertRaises(RuntimeError):suite.wait_for_operator(c,auth,ROOT/'test_temp')
        self.assertIsNone(c.worker)
    def test_loopback_button_signals_gate_without_opening_camera(self):
        import re,urllib.request,urllib.error,suite
        c=self.armed();http=app.server(c);thread=threading.Thread(target=http.serve_forever);thread.start()
        url=f'http://127.0.0.1:{http.server_port}'
        try:
            with urllib.request.urlopen(url) as response:html=response.read().decode('utf-8')
            self.assertIn('id="operatorready"',html)
            token=re.search("const token='([^']+)'",html).group(1)
            request=urllib.request.Request(url+'/ready',data=b'{}',headers={'Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
            self.assertEqual(error.exception.code,403);self.assertFalse(c.preview_gate.is_set())
            request=urllib.request.Request(url+'/ready',data=b'{}',headers={'Content-Type':'application/json','X-MVP-Token':token})
            with urllib.request.urlopen(request) as response:self.assertTrue(json.load(response)['operator_ready'])
            with tempfile.TemporaryDirectory(dir=ROOT/'test_temp') as folder:
                start=time.monotonic_ns()
                auth=dict(suite_id='OFFLINE_FIXTURE',mvp_scope={'suite_started_monotonic_ns':start})
                suite.wait_for_operator(c,auth,Path(folder))
                row=json.loads((Path(folder)/'OPERATOR_READY.json').read_text())
                self.assertEqual(row['suite_id'],'OFFLINE_FIXTURE')
                self.assertEqual(auth['mvp_scope']['suite_started_monotonic_ns'],start)
            self.assertIsNone(c.worker);self.assertIsNone(c.capture)
        finally:c.stop();http.shutdown();http.server_close();thread.join(3)

if __name__=='__main__':
    (ROOT/'test_temp').mkdir(exist_ok=True)
    unittest.main(verbosity=2)
