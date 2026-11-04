"""WORK-02 persistent frozen-MMIO adapter; no programming and no fallback."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import struct,zlib
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'codec'))
from packed10 import make_packet

sys.dont_write_bytecode = True
TASKS = Path(r'D:\FPGA-AUTO\tasks')
spec = importlib.util.spec_from_file_location('work02_reference_loader', TASKS/'WORK-01/edge_live/runtime.py')
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)
C = reference.C
READY=Path(__file__).resolve().parent.parent/'BUILD_READY.json'
BIT_SHA=json.loads(READY.read_text(encoding='utf-8'))['bit_sha256'] if READY.exists() else 'UNBUILT_NOT_AUTHORIZED'

class Rejected(ValueError):
    """Invalid caller input, rejected before backend mutation."""

class BackendFault(RuntimeError):
    """Backend failure: no valid output; reset required."""

def integer(value, name):
    if type(value) is not int or value < 0:
        raise Rejected(name+' must be a nonnegative integer, not bool')
    return value

def encode_inputs(q, noise, input_sha, noise_sha):
    if not isinstance(q, list) or len(q) != 311 or any(type(v) is not int or v not in (0, 2458) for v in q):
        raise Rejected('Q outside frozen representable set {0,2458}; no quantization')
    if not isinstance(noise, list) or any(type(v) is not int or not 0 <= v < 471 for v in noise):
        raise Rejected('noise must contain integer local indices 0..470')
    if noise != sorted(set(noise)):
        raise Rejected('noise must be strictly ascending and unique')
    actual_input = C.canonical_hash(q)
    mask = np.zeros(471, dtype=np.uint8)
    mask[noise] = 1
    actual_noise = hashlib.sha256(np.packbits(mask, bitorder='little').tobytes()).hexdigest()
    if actual_input != input_sha or actual_noise != noise_sha:
        raise Rejected('backend input/noise identity mismatch')
    stimulus = sorted(int(C.input_local[i]) for i, value in enumerate(q) if value)
    return stimulus + [512+i for i in noise]

class CounterDifferencer:
    def reset(self, generation):
        self.generation = generation
        self.expected = 0
        self.previous = [0]*32  # Proven core reset, no illegal LOAD reads.
        self.cached = None

    def accept(self, generation, frame, counts):
        if generation != self.generation:
            raise BackendFault('stale counter generation')
        if not isinstance(counts, list) or len(counts) != 32 or any(type(x) is not int or not 0 <= x <= 0xffffffff for x in counts):
            raise BackendFault('invalid cumulative DN vector')
        if self.cached is not None and frame == self.expected-1:
            if counts != self.previous:
                raise BackendFault('conflicting duplicate readback')
            return list(self.cached)
        if frame != self.expected:
            raise BackendFault('stale/gap completed ID; counters not advanced')
        delta = [(b-a) & 0xffffffff for a,b in zip(self.previous, counts)]
        if any(x not in (0,1) for x in delta):
            raise BackendFault('nonbinary DN delta; missing step or reset mismatch')
        self.previous = list(counts)
        self.cached = delta
        self.expected += 1
        return list(delta)

class PersistentLabTransport:
    """One local Vivado process for all frames; one request/response per frame.

    The caller starts/owns loopback hw_server and deploys persistent_mmio.tcl.
    A traceable load receipt is a required gate, never inferred from protocol ID.
    """
    origin = 'FPGA_HARDWARE_CANDIDATE_UNACCEPTED'
    def __init__(self, command, raw_log, timeout=30):
        self.timeout = timeout
        self.queue = queue.Queue()
        self.seq = 0
        self.log = Path(raw_log).open('x', encoding='utf-8')
        from local_tools import child_env
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, bufsize=1,
                                        creationflags=subprocess.CREATE_NO_WINDOW,env=child_env(),
                                        cwd=Path(raw_log).resolve().parent)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            self.handshake = self._receive(0)
        except Exception:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                self.log.write(line)
                self.log.flush()
                if line.startswith('FLY02|'):
                    fields = line.rstrip('\r\n').split('|', 2)
                    self.queue.put((int(fields[1]), json.loads(fields[2])))
        except Exception as exc:
            self.queue.put((-1, {'error': repr(exc)}))
        finally:
            self.queue.put((-1, {'error': 'transport process EOF'}))

    def _receive(self, seq):
        try:
            got, result = self.queue.get(timeout=self.timeout)
        except queue.Empty as exc:
            self.close()
            raise BackendFault('persistent transport timeout: no output is valid') from exc
        if got != seq or not result.get('ok'):
            raise BackendFault('transport response mismatch/failure: '+repr(result))
        return result

    def _call(self, fields):
        self.seq += 1
        # Only validated integers, hashes and fixed operation names are admitted.
        line = ' '.join([str(self.seq), *map(str, fields)])+'\n'
        self.process.stdin.write(line)
        self.process.stdin.flush()
        return self._receive(self.seq)

    def reset(self, generation):
        return self._call(['RESET', generation])

    def step(self, generation, frame, q, noise, events, input_sha, noise_sha, audit):
        return self._call(['STEP', generation, frame, input_sha, noise_sha, int(audit), *events])

    def abort(self):
        from local_tools import stop_tree
        stop_tree(self.process)

    def close(self):
        if self.process.poll() is None:
            try:
                # Never enter _receive recursively during timeout cleanup.
                self.seq += 1
                self.process.stdin.write(str(self.seq)+' CLOSE\n')
                self.process.stdin.flush()
                self.process.wait(timeout=5)
            except Exception:
                self.abort()
        self.reader.join(timeout=5)
        self.log.close()

class MockNeuralTransport:
    """Exact reference-powered test double. NEVER hardware or RTL evidence."""
    origin = 'MOCK_FPGA_TRANSPORT'
    def __init__(self):
        self.transactions = []
    def reset(self, generation):
        self.sim = C.IM.CandidateBInteger(C.preloc,C.postloc,C.weights,C.IM.FORMATS['RECOMMENDED'])
        self.generation = generation
        self.counts = [0]*32
        self.transactions.append(('RESET', generation))
        return {'ok':True, 'generation':generation, 'status':2, 'error_status':0,
                'reset_guard_complete':True, 'completed_id':0xffffffff}
    def step(self, generation, frame, q, noise, events, input_sha, noise_sha, audit):
        self.transactions.append(('STEP', generation, frame, events))
        assert generation == self.generation and frame == self.sim.steps
        C.apply_qvec(self.sim,q)
        fired = self.sim.step(noise)
        slots = C.dn_frame(frame, fired, 'WORK02').slots
        self.counts = [(a+b)&0xffffffff for a,b in zip(self.counts,slots)]
        return {'ok':True, 'generation':generation,'completed_id':frame,'input_sha256':input_sha,
                'noise_sha256':noise_sha, 'status':70,'error_status':0,'overflow':0,'drop':0,
                'acc_sat':int(self.sim.acc_saturation_count),'state_sat':int(self.sim.state_saturation_count),
                'cycles':1,'counts':list(self.counts),'states':self.sim.state.tolist() if audit else [],
                'timings_ms':{}, 'transaction_count':None, 'mock_cycles_not_hardware':True}
    def close(self): pass

class FpgaAdapter:
    def __init__(self, transport, loaded_sha=None, load_receipt=None, a_accepted=False, hardware_verified=False):
        if transport.origin.startswith('FPGA_'):
            if loaded_sha != BIT_SHA or not load_receipt or not Path(load_receipt).is_file():
                raise Rejected('hardware loaded identity requires exact SHA and traceable load receipt; no fallback')
            receipt = json.loads(Path(load_receipt).read_text(encoding='utf-8'))
            if receipt.get('bitstream_sha256') != BIT_SHA or receipt.get('programming_status') != 'PASS':
                raise Rejected('load receipt does not prove approved exact artifact load')
        self.transport = transport
        # Physical evidence does not itself constitute Controller B acceptance.
        self.origin = transport.origin
        self.acceptance = {'correctness':False, 'hardware':hardware_verified, 'realtime':False,
                           'A_controller_accepted':a_accepted}
        self.generation = 0
        self.diff = CounterDifferencer()
        self.reset()

    def reset(self):
        # A reset may already have changed board state before its response fails.
        # Old generation/cached output must stay unusable until a confirmed reset.
        self.fault = 'RESET_INCOMPLETE'
        generation = self.generation+1
        try:
            reply = self.transport.reset(generation)
            if (reply.get('generation') != generation or reply.get('status') & 0x18f != 2 or
                    reply.get('error_status') != 0 or reply.get('completed_id') != 0xffffffff or
                    not reply.get('reset_guard_complete')):
                raise BackendFault('reset guard or LOAD confirmation failed')
        except Exception as exc:
            self.fault = 'RESET_INCOMPLETE: '+repr(exc)
            raise BackendFault(self.fault) from exc
        self.generation = generation
        if self.transport.origin.startswith('FPGA_'):
            physical=reply.get('hardware_generation')
            if type(physical) is not int or not 0<=physical<=0xffffffff:
                self.fault='RESET_HARDWARE_GENERATION_INVALID'
                raise BackendFault(self.fault)
            self.hardware_generation=physical
        self.frame = 0
        self.fault = None
        self.last_request = None
        self.last_response = None
        self.diff.reset(generation)

    def transact(self, generation, frame, q, noise, input_sha, noise_sha, audit=True):
        integer(generation, 'generation'); integer(frame,'frame')
        if frame>0xffffffff: raise Rejected('frame exceeds frozen uint32 timestep ID')
        if type(audit) is not bool: raise Rejected('audit must be boolean')
        if generation != self.generation: raise Rejected('stale generation')
        events = encode_inputs(q, noise, input_sha, noise_sha)
        if self.fault: raise BackendFault('latched backend fault; reset required')
        req = (generation,frame,tuple(q),tuple(noise),input_sha,noise_sha,bool(audit))
        if req == self.last_request:
            return {**self.last_response, 'cached':True}
        if frame != self.frame: raise Rejected('duplicate/conflicting/stale/gap frame')
        try:
            start = time.perf_counter()
            reply = self.transport.step(generation,frame,q,noise,events,input_sha,noise_sha,audit)
            if self.transport.origin.startswith('FPGA_'):
                packet=make_packet(self.hardware_generation,frame,events,1);expected_crc=packet[7]
                if reply.get('hardware_generation')!=self.hardware_generation or reply.get('snapshot_valid')!=1 or reply.get('snapshot_word_count')!=530:
                    raise BackendFault('O7 physical generation/valid/word-count mismatch')
                if (reply.get('interface_version')!='F1070001' or reply.get('accepted_events')!=len(events) or
                    reply.get('request_id')!=frame or reply.get('request_generation')!=self.hardware_generation or
                    type(reply.get('accepted_request_crc32')) is not int or reply['accepted_request_crc32']!=expected_crc or
                    reply.get('packet_words')!=len(packet) or reply.get('hardware_commits')!=frame+1 or
                    type(reply.get('decode_cycles')) is not int or not len(events)<=reply['decode_cycles']<=2*len(events) or
                    type(reply.get('protocol_cycles')) is not int or reply['protocol_cycles']<=reply['decode_cycles']):
                    raise BackendFault('O7 accepted physical request identity/checksum mismatch')
            if (reply.get('generation') != generation or reply.get('completed_id') != frame or
                reply.get('input_sha256') != input_sha or reply.get('noise_sha256') != noise_sha):
                raise BackendFault('snapshot generation/frame/input/noise mismatch')
            if (reply.get('status') & 0x18f != 6 or not reply.get('status') & 64 or
                any(reply.get(k) != 0 for k in ('error_status','overflow','drop'))):
                raise BackendFault('snapshot error/deadline/overflow/drop')
            if type(reply.get('cycles')) is not int or not 0 < reply['cycles'] <= 500000:
                raise BackendFault('invalid cycle counter')
            if any(type(reply.get(key)) is not int or not 0<=reply[key]<=0xffffffff for key in ('acc_sat','state_sat')):
                raise BackendFault('invalid cumulative saturation counters')
            states = reply.get('states')
            if audit and (not isinstance(states,list) or len(states)!=471 or any(type(x)is not int or not -131072<=x<=131071 for x in states)):
                raise BackendFault('invalid signed S18 audit snapshot')
            slots = self.diff.accept(generation,frame,reply['counts'])
            out = {**reply,'origin':self.origin,'acceptance':dict(self.acceptance),'slots':slots,'cached':False,
                   'frame_id':frame,'host_transport_ms':(time.perf_counter()-start)*1000,
                   'neural_state_sha256':hashlib.sha256(np.asarray(states,dtype='<i8').tobytes()).hexdigest() if audit else None}
            self.frame += 1
            self.last_request,self.last_response = req,out
            return out
        except Exception as exc:
            self.fault = repr(exc)
            raise BackendFault('backend fault; frame output INVALID: '+repr(exc)) from exc

class EdgeFpgaRuntime(reference.LiveRuntime):
    """Frozen host chain; neural output is supplied ONLY by selected backend."""
    def __init__(self, adapter, target=None, audit=True):
        self.adapter = adapter
        self.audit = audit
        self.backend_id = adapter.origin
        self.art = C.SH.FrozenArtifacts()
        self.target = reference.target_valid(list(target or C.MF['scenarios']['LEFT']['target_position_world_m']))
        self._reset_host()
    def _reset_host(self):
        self.generation=self.adapter.generation;self.frame_id=0;self.next_request_seq=0
        self.last_request=None;self.last_response=None;self.pending_target=None;self.applied_update_seq=None
        self.latched_error=None;self.latest=None
        self.rng=np.random.default_rng(C.SEED)
        self.pre=C.SH.FrozenPreprocessorV1_0(self.art)
        self.mapper=C.SH.FinalDNMotorMapperV1_0(self.art)
        self.bodyrt=self.art.bodyrt.BodyRuntime(self.art.body_config)
        self.body=self.art.bodyrt.BodyState.zero();self.pending_q=[0]*311
    def reset(self):
        self.adapter.reset();self._reset_host()
    def step(self):
        if self.latched_error: raise BackendFault('runtime fault latched; output invalid')
        start=time.perf_counter(); k=self.frame_id
        if self.pending_target is not None:
            self.target,self.applied_update_seq=self.pending_target;self.pending_target=None
        world=C.world_frame(k,self.target);fb=C.feedback_frame(k,self.body,world)
        enc=C.SE.encode_feedback_frame(fb);q_next=[int(x) for x in enc['drive_q_by_input_ordinal']]
        q_apply=list(self.pending_q)
        full_noise=self.rng.random(166700)<C.NOISE_P
        noise_local=np.flatnonzero(full_noise[C.nodes]).tolist()
        noise_sha=hashlib.sha256(np.packbits(full_noise[C.nodes].astype(np.uint8),bitorder='little').tobytes()).hexdigest()
        encoded=time.perf_counter()
        try:
            result=self.adapter.transact(self.generation,k,q_apply,noise_local,C.canonical_hash(q_apply),noise_sha,self.audit)
            transported=time.perf_counter()
            # Original frozen preprocessor/mapper/body classes and frame/time fields.
            dn=C.SH.DNFrame(frame_id=k,timestamp_s=k*C.DT,dt_s=C.DT,slots=tuple(result['slots']),
                           source_id='CandidateBIntegerClosedLoop',replay_id='DEMO1_LIVE',
                           stimulus_state='CLOSED_LOOP',source_timestep=k)
            pp=self.pre.step(dn);drive,vals=self.mapper.map(dn,pp,k)
            body_next,_,_=self.bodyrt.step(drive,self.body)
            bnext=C.body_dict(body_next)
            if not bnext['valid'] or not all(math.isfinite(x) for name in ('position_xyz','orientation_wxyz','linear_velocity_xyz','angular_velocity_xyz') for x in bnext[name]):
                raise BackendFault('invalid body')
        except Exception as exc:
            self.latched_error=repr(exc);raise
        rec={'tick':k,'model_time_s':k*C.DT,'body_state_k':C.body_dict(self.body),'world_state_k':world,'feedback_frame_k':fb,
             'source_drive_k':{'target_neural_timestep_id':k,'q_vector_sha256':C.canonical_hash(q_apply),
                              'active_count':sum(q!=0 for q in q_apply),'active_ordinals':[i for i,q in enumerate(q_apply) if q]},
             'source_drive_k_plus_1':{'target_neural_timestep_id':k+1,'q_vector_sha256':C.canonical_hash(q_next),
                                   'active_group':enc['active_group'],'active_count':sum(q!=0 for q in q_next),
                                   'active_ordinals':[i for i,q in enumerate(q_next) if q]},
             'external_noise':{'local_event_count':len(noise_local),'mask471_sha256':noise_sha},
             'dn_frame_k':{'slots':result['slots'],'slots_sha256':C.canonical_hash(result['slots']),
                           'fired_local_count':None,'fired_local_count_observability':'NOT_IN_FROZEN_MMIO'},
             'preprocessor':{name:float(pp[name]) for name in ('a12','a22','a23','y12','y22','y23')},
             'mapping':{name:float(vals[name]) for name in ('h_p03','p03_contribution','p06R_contribution','yaw_pre')},
             'motor_drive_k':C.drive_dict(drive),'body_state_k_plus_1':bnext,'backend_snapshot':result,
             'timings_ms':{'encoding_rng':(encoded-start)*1000,'transport':(transported-encoded)*1000,
                           'mapping_body':(time.perf_counter()-transported)*1000}}
        self.pending_q=q_next;self.body=body_next;self.frame_id+=1;self.latest=rec
        return rec
