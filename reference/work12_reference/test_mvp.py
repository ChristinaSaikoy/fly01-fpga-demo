"""Software injection only. No actual camera/serial/JTAG/motor access."""
import copy,json,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from app import Controller,Latest,validate_config
from neural import C,NeuralRuntime
from pixel import PixelDirectionMVP
from actuator import DryRunActuator
from mvp_link import *
from test_host import MockPort,snapshot
from packed10 import make_packet
from mvp_authority import claim_scope
from fly01_vision.pipeline import VisionPipeline
from fly01_vision.settings import load_settings

def observation(label,frame=0,now=None,mirror=False):
    now=time.monotonic_ns() if now is None else now
    rgb=np.zeros((61,101,3),np.uint8)
    for x in dict(LEFT=[20],RIGHT=[80],CENTER=[50],NO_TARGET=[],AMBIGUOUS=[20,80])[label]:rgb[26:35,x-4:x+5,0]=230
    settings=load_settings();settings['input']['sensor_mirror_x']=mirror
    p=VisionPipeline(settings,'fixture-session','HOST_MONOTONIC')
    return p.process_rgb(rgb,frame_id=frame,source={'kind':'SOFTWARE_INJECTION','capture_time_ns':None,'capture_time_verified':False},received_ns=now,processed_ns=now)[0]

class InjectionPort(MockPort):
    def __init__(self,action=None,opcode=FRAME):super().__init__();self.action=action;self.opcode=opcode;self.saved=None;self.connected=True
    def reply(self,request,words,generation=None):
        before=len(self.responses);super().reply(request,words,generation)
        if request.opcode!=self.opcode:return
        wire=bytes(self.responses[before:]);action=self.action;self.action=None
        if action=='drop':del self.responses[before:]
        elif action=='corrupt_then_good':self.responses[before:]=wire[:9]+bytes([wire[9]^1])+wire[10:]+wire
        elif action=='middle16_then_good':self.responses[before:]=wire[:65]+wire[81:]+wire
        elif action=='tail42_then_good':self.responses[before:]=wire[:-42]+wire
        elif action=='duplicate':self.responses.extend(wire)
        elif action=='stale_then_good':
            msg=Message(request.opcode|0x80,request.view,request.session+1,request.generation,request.frame,words_payload([0]+words))
            self.responses[before:]=encode(msg)+wire
        elif action=='late_same_retry':del self.responses[before:];self.saved=wire
        elif self.saved:self.responses[before:]=self.saved+wire;self.saved=None
    def read(self,deadline):
        if not self.connected:raise LinkFault('injected disconnect')
        # Return full batch: tests duplicate/late-buffer handling, not serial timing.
        if not self.responses:raise TimeoutError('injected deadline')
        data=bytes(self.responses);self.responses.clear();return data

def client(port):
    c=MVPClient(port,123);c.claim();c.reset();return c

class PixelTests(unittest.TestCase):
    def test_direction_roster_strength_and_latency(self):
        for label,count,group in [('LEFT',165,'LEFT'),('RIGHT',146,'RIGHT'),('CENTER',311,'BILATERAL')]:
            p=PixelDirectionMVP(C.SE.ROSTER,C.SE.Q);now=time.monotonic_ns()
            self.assertTrue(p.submit(observation(label,now=now)))
            self.assertEqual(sum(p.sample(0,now)['applied']['q']),0)
            s=p.sample(1,now+20_000_000)['applied']
            self.assertEqual(s['group'],group);self.assertEqual(s['q'].count(2458),count)
            self.assertFalse(s['geometry_verified']);self.assertFalse(s['motion_eligible'])
    def test_mirror_and_no_fake_geometry(self):
        p=PixelDirectionMVP(C.SE.ROSTER,C.SE.Q);now=time.monotonic_ns();o=observation('LEFT',now=now,mirror=True)
        self.assertIsNone(o['geometry']['azimuth_rad']);p.submit(o);p.sample(0,now)
        self.assertEqual(p.sample(1,now+1)['applied']['group'],'RIGHT')
    def test_no_target_and_multiple_clear_pending(self):
        for label in ['NO_TARGET','AMBIGUOUS']:
            p=PixelDirectionMVP(C.SE.ROSTER,C.SE.Q);now=time.monotonic_ns();p.submit(observation('LEFT',0,now));p.sample(0,now)
            p.submit(observation(label,1,now+1));self.assertEqual(p.sample(1,now+2)['applied']['group'],'NONE')
    def test_expired_backward_duplicate_and_no_skip(self):
        p=PixelDirectionMVP(C.SE.ROSTER,C.SE.Q);now=time.monotonic_ns();o=observation('LEFT',0,now);p.submit(o);p.sample(0,now)
        self.assertEqual(p.sample(1,now+250_000_000)['applied']['group'],'NONE')
        self.assertFalse(p.submit(o))
        with self.assertRaises(ValueError):p.sample(3,now)
    def test_latest_replacement_only_unadopted(self):
        m=Latest();m.put(1);m.put(2);self.assertEqual((m.take(),m.replaced),(2,1));self.assertIsNone(m.take())

class LinkTests(unittest.TestCase):
    def test_bad_wire_segments_resync_strictly(self):
        for action in ['corrupt_then_good','middle16_then_good','tail42_then_good']:
            p=InjectionPort(action);c=client(p);r=c.frame(make_packet(c.generation,0,[1,513]),0);c.ack()
            self.assertEqual((p.commits,c.next_frame,len(r['states'])),(1,1,471));self.assertGreater(c.stats['bad_segments'],0)
    def test_exact_retry_frame_and_ack_does_not_recommit(self):
        p=InjectionPort('drop');c=client(p);packet=make_packet(c.generation,0,[1,513]);c.frame(packet,0)
        p.action='drop';p.opcode=ACK;c.ack()
        requests=[r for r in p.evidence.records if r[0]=='REQUEST' and r[2]['opcode'] in (FRAME,ACK)]
        self.assertEqual(requests[0][1],requests[1][1]);self.assertEqual(requests[2][1],requests[3][1])
        self.assertEqual((p.commits,p.acks,c.next_frame,c.stats['retries']),(1,1,1,2))
    def test_duplicate_and_stale_have_no_extra_step(self):
        for action in ['duplicate','stale_then_good','late_same_retry']:
            p=InjectionPort(action);c=client(p);c.frame(make_packet(c.generation,0,[1]),0);c.ack()
            self.assertEqual((p.commits,c.next_frame),(1,1))
            self.assertGreater(c.stats['duplicate_responses']+c.stats['stale_responses'],0)
    def test_prior_frame_late_response_discarded(self):
        p=InjectionPort();c=client(p);packet=make_packet(c.generation,0,[1]);r=c.frame(packet,0);c.ack()
        p.responses.extend(encode(Message(FRAME|0x80,0,c.session,c.generation,0,words_payload([0]+r['words']))))
        c.frame(make_packet(c.generation,1,[2]),0);c.ack()
        self.assertEqual((p.commits,c.next_frame),(2,2));self.assertGreater(c.stats['stale_responses'],0)
    def test_ack_uncertain_latches_and_explicit_session_recovery(self):
        p=InjectionPort();c=client(p);c.frame(make_packet(c.generation,0,[1]),0)
        original=p.reply
        p.reply=lambda request,words,generation=None:None if request.opcode==ACK else original(request,words,generation)
        with self.assertRaises(TimeoutError):c.ack()
        self.assertEqual(c.next_frame,0)
        with self.assertRaises(LinkFault):c.frame(make_packet(c.generation,1,[2]),0)
        self.assertEqual(p.commits,1)
        p.reply=original;c.reset();c.release();fresh=MVPClient(p,456);fresh.claim();fresh.reset()
        self.assertEqual((fresh.next_frame,fresh.pending,fresh.fault),(0,None,None))
    def test_disconnect_and_reconnect_requires_new_session(self):
        p=InjectionPort();c=client(p);p.connected=False
        with self.assertRaises(LinkFault):c.frame(make_packet(c.generation,0,[1]),0)
        p.connected=True
        with self.assertRaises(LinkFault):c.frame(make_packet(c.generation,0,[1]),0)
        c.reset();c.release();fresh=MVPClient(p,456);fresh.claim();fresh.reset()
        fresh.frame(make_packet(fresh.generation,0,[1]),0);fresh.ack();self.assertEqual(fresh.next_frame,1)
    def test_crc_valid_bad_snapshot_is_rejected(self):
        p=InjectionPort();c=client(p);original=p.reply
        def bad(request,words,generation=None):
            if request.opcode==FRAME:words[0]=131072
            return original(request,words,generation)
        p.reply=bad
        with self.assertRaises(LinkFault):c.frame(make_packet(c.generation,0,[1]),0)
        self.assertIsNone(c.pending)
    def test_reset_lost_is_not_retried(self):
        p=InjectionPort();c=client(p);p.action='drop';p.opcode=RESET
        resets=p.resets
        with self.assertRaises(TimeoutError):c.reset()
        self.assertEqual(p.resets,resets+1)
    def test_invalid_escape_and_bounded_buffer(self):
        p=ResyncParser();good=encode(Message(HELLO));self.assertEqual(p.feed(b'\x7e\x7d\x01\x7e'+good),[Message(HELLO)])
        self.assertGreater(p.errors,0);p.feed(b'\x7e'+b'a'*10000);self.assertLessEqual(len(p.buffer),MAX_RAW)
    def test_budget_not_silently_shortened(self):
        with self.assertRaises(ValueError):MVPClient(InjectionPort(),123,timeout=.02)
    def test_expired_scope_never_writes(self):
        p=InjectionPort();c=MVPClient(p,123,scope_deadline_ns=time.monotonic_ns()-1)
        with self.assertRaises(LinkFault):c.claim()
        self.assertFalse(p.evidence.records);self.assertEqual(p.owner,0)

class SafetyTests(unittest.TestCase):
    def test_new_mvp_scope_cannot_reuse_old_or_other_process_permission(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'FAKE_AUTH_NEVER_REAL.json';now=100000000000
            auth=dict(status='APPROVED_EXACT_ARTIFACT',suite_id='FAKE_FIXTURE_ONLY',candidate_sha256='a'*64,
                mvp_scope=dict(name='MVP-DEMO-V1_NON_MOTION',restart_policy='EXPLICIT_SAME_PROCESS_WITHIN_WINDOW',suite_started_monotonic_ns=now))
            p.write_text(json.dumps(auth));store=Path(folder)/'uses'
            claim_scope(p,'a'*64,now_ns=now,store=store,owner='fixture-owner')
            claim_scope(p,'a'*64,now_ns=now+1,store=store,owner='fixture-owner')
            with self.assertRaises(PermissionError):claim_scope(p,'a'*64,now_ns=now,store=store,owner='different-owner')
            with self.assertRaises(PermissionError):claim_scope(p,'b'*64,now_ns=now,store=store)
            with self.assertRaises(PermissionError):claim_scope(p,'a'*64,now_ns=now+1800_000_000_000,store=store)
            del auth['mvp_scope'];p.write_text(json.dumps(auth))
            with self.assertRaises(PermissionError):claim_scope(p,'a'*64,now_ns=now,store=store)
    def test_no_actual_camera_or_port_without_scope(self):
        with self.assertRaises(PermissionError):validate_config({'source':'camera'})
        with self.assertRaises(PermissionError):validate_config({'backend':'fpga'})
    def test_dry_default_latch_limits_and_reenable(self):
        rows=[];a=DryRunActuator(rows.append);self.assertFalse(a.enabled);a.enable();now=time.monotonic_ns()
        r=dict(validated_ns=now,sampling={'applied':{'observation_id':'x'}},model_step=1,
               motor_drive_simulated={'v_forward_ref':2.,'yaw_rate_ref':4.})
        self.assertEqual((a.update(r,now)['v'],a.update(r,now)['yaw']),(.1,.5))
        a.poll(now+251_000_000);self.assertFalse(a.enabled);self.assertIsNone(a.update(r,now))
        a.enable();r['sampling']['applied']['observation_id']=None;a.update(r,now);self.assertFalse(a.enabled)
        self.assertTrue(all(not row['physical_output'] for row in rows))
    def test_status_nonblocking_during_neural_wait_and_stale_clear(self):
        with tempfile.TemporaryDirectory() as folder:
            c=Controller(folder);runtime=NeuralRuntime.reference();normal=runtime.step
            entered=threading.Event();release=threading.Event()
            def blocked(*args,**kw):entered.set();release.wait(1);return normal(*args,**kw)
            runtime.step=blocked
            with patch('app.NeuralRuntime.reference',return_value=runtime):
                c.start({});self.assertTrue(entered.wait(2));t=time.monotonic();s=c.status();self.assertLess(time.monotonic()-t,.1)
                self.assertFalse(s['output_valid']);self.assertIsNone(s['dn_slots']);c.stop();release.set();c.worker.join(3)
                self.assertFalse(c.worker.is_alive());self.assertFalse(c.status()['output_valid'])

if __name__=='__main__':unittest.main(verbosity=2)
