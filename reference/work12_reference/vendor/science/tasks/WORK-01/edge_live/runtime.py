"""Stateful EDGE_REFERENCE_LIVE candidate; frozen assets are read-only."""
from __future__ import annotations
import ast
import hashlib
import json
import math
from pathlib import Path
import sys
import types
import numpy as np
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from work_utils import TASKS,sha,read_json

def load_reference():
    # The original geometry validator writes a historic report at import time.
    # Compile its original imports/functions only; do not execute its test driver.
    gp=TASKS/'BODY-0A2D'/'validate_body_0a2d.py'
    gt=ast.parse(gp.read_text(encoding='utf-8'),filename=str(gp))
    safe=ast.Module(body=[n for n in gt.body if isinstance(n,(ast.Import,ast.ImportFrom,ast.FunctionDef))],type_ignores=[])
    geom=types.ModuleType('work01_geometry_functions')
    exec(compile(safe,str(gp),'exec'),geom.__dict__)
    p=TASKS/'DEMO-1-IMPLEMENTATION'/'closed_loop_execute.py'
    tree=ast.parse(p.read_text(encoding='utf-8'),filename=str(p))
    tree.body=[n for n in tree.body if not (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='BG' for t in n.targets))]
    module=types.ModuleType('work01_frozen_causal_reference')
    module.__file__=str(p);module.BG=geom
    exec(compile(tree,str(p),'exec'),module.__dict__)
    module.geometry_source_sha256=sha(gp)
    return module

C=load_reference()

class RequestError(ValueError):
    pass

def target_valid(value):
    if not isinstance(value,list) or len(value)!=3 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in value):
        raise RequestError('target must be three finite numeric coordinates')
    return tuple(float(x) for x in value)

class LiveRuntime:
    backend_id='EDGE_REFERENCE_LIVE'
    def __init__(self,target=None):
        self.generation=0
        self.art=C.SH.FrozenArtifacts()
        self.target=target_valid(list(target or C.MF['scenarios']['LEFT']['target_position_world_m']))
        self.reset()

    def reset(self):
        self.generation+=1;self.frame_id=0;self.next_request_seq=0;self.last_request=None;self.last_response=None
        self.pending_target=None;self.applied_update_seq=None;self.latched_error=None;self.latest=None
        self.sim=C.IM.CandidateBInteger(C.preloc,C.postloc,C.weights,C.IM.FORMATS['RECOMMENDED'])
        self.rng=np.random.default_rng(C.SEED)
        self.pre=C.SH.FrozenPreprocessorV1_0(self.art)
        self.mapper=C.SH.FinalDNMotorMapperV1_0(self.art)
        self.bodyrt=self.art.bodyrt.BodyRuntime(self.art.body_config)
        self.body=self.art.bodyrt.BodyState.zero();self.pending_q=[0]*311
        self.sim_initial_identity=id(self.sim);self.bodyrt_initial_identity=id(self.bodyrt)

    def update(self,request):
        if not isinstance(request,dict) or set(request)!={'generation','request_seq','position_xyz_world_m'}:
            raise RequestError('exact fields: generation, request_seq, position_xyz_world_m')
        for key in ('generation','request_seq'):
            if isinstance(request[key],bool) or not isinstance(request[key],int):raise RequestError(key+' must be integer')
        pos=target_valid(request['position_xyz_world_m'])
        if request['generation']!=self.generation:raise RequestError('stale reset generation')
        normalized={**request,'position_xyz_world_m':list(pos)}
        if normalized==self.last_request:return {**self.last_response,'cached':True}
        if request['request_seq']!=self.next_request_seq:raise RequestError('duplicate/conflicting/stale/gap request sequence')
        if self.pending_target is not None:raise RequestError('BUSY: one pending target update')
        response={'generation':self.generation,'request_seq':request['request_seq'],'effective_frame':self.frame_id,
                  'encoded_at_frame':self.frame_id,'earliest_neural_input_frame':self.frame_id+1,'cached':False}
        self.pending_target=(pos,request['request_seq']);self.next_request_seq+=1
        self.last_request=normalized;self.last_response=response
        return response

    def step(self):
        if self.latched_error is not None:raise RuntimeError('latched ERROR; reset required')
        k=self.frame_id
        if self.pending_target is not None:
            self.target,self.applied_update_seq=self.pending_target;self.pending_target=None
        body_before=C.body_dict(self.body)
        world=C.world_frame(k,self.target)
        fb=C.feedback_frame(k,self.body,world)
        enc=C.SE.encode_feedback_frame(fb)
        q_next=[int(x) for x in enc['drive_q_by_input_ordinal']]
        q_apply=list(self.pending_q)
        C.apply_qvec(self.sim,q_apply)
        full_noise=self.rng.random(166700)<C.NOISE_P
        noise_local=np.flatnonzero(full_noise[C.nodes]).astype(np.int32)
        nh=hashlib.sha256(np.packbits(np.asarray(full_noise[C.nodes],dtype=np.uint8),bitorder='little').tobytes()).hexdigest()
        fired=self.sim.step(noise_local)
        dn=C.dn_frame(k,fired,'LIVE')
        pp=self.pre.step(dn)
        drive,vals=self.mapper.map(dn,pp,k)
        body_next,_,_=self.bodyrt.step(drive,self.body)
        bnext=C.body_dict(body_next)
        if not bnext['valid'] or not all(math.isfinite(x) for name in ('position_xyz','orientation_wxyz','linear_velocity_xyz','angular_velocity_xyz') for x in bnext[name]):
            self.latched_error='INVALID_BODY';raise RuntimeError(self.latched_error)
        rec={'tick':k,'model_time_s':k*C.DT,'body_state_k':body_before,'world_state_k':world,'feedback_frame_k':fb,
             'source_drive_k':{'target_neural_timestep_id':k,'q_vector_sha256':C.canonical_hash(q_apply),
                 'active_count':sum(q!=0 for q in q_apply),'active_ordinals':[i for i,q in enumerate(q_apply) if q]},
             'source_drive_k_plus_1':{'target_neural_timestep_id':k+1,'q_vector_sha256':C.canonical_hash(q_next),
                 'active_group':enc['active_group'],'active_count':sum(q!=0 for q in q_next),
                 'active_ordinals':[i for i,q in enumerate(q_next) if q]},
             'external_noise':{'local_event_count':len(noise_local),'mask471_sha256':nh},
             'dn_frame_k':{'slots':list(dn.slots),'slots_sha256':C.canonical_hash(list(dn.slots)),'fired_local_count':len(fired)},
             'preprocessor':{name:float(pp[name]) for name in ('a12','a22','a23','y12','y22','y23')},
             'mapping':{name:float(vals[name]) for name in ('h_p03','p03_contribution','p06R_contribution','yaw_pre')},
             'motor_drive_k':C.drive_dict(drive),'body_state_k_plus_1':bnext}
        rec['candidate']={'backend_id':self.backend_id,'generation':self.generation,'applied_target_request_seq':self.applied_update_seq,
                          'neural_steps':int(self.sim.steps),'neural_state_sha256':hashlib.sha256(np.asarray(self.sim.state,dtype='<i8').tobytes()).hexdigest(),
                          'persistent_neural_instance':id(self.sim)==self.sim_initial_identity,
                          'persistent_body_runtime_instance':id(self.bodyrt)==self.bodyrt_initial_identity}
        self.pending_q=q_next;self.body=body_next;self.frame_id+=1;self.latest=rec
        return rec

class UnavailableFpgaBackend:
    def __init__(self):
        raise RuntimeError('EDGE_FPGA_LIVE unavailable: true-board gates and transport not accepted; no software fallback')

class MockFpgaContract:
    """Protocol-only test double. Never presented as a neural or hardware result."""
    backend_id='MOCK_FPGA_CONTRACT'
    def __init__(self):self.generation=1;self.frame=0
    def transact(self,generation,frame,q,noise_sha):
        if generation!=self.generation or frame!=self.frame:raise RequestError('mock stale/gap')
        if len(q)!=311 or any(type(x)is not int or x not in (0,2458) for x in q):raise RequestError('mock invalid input')
        if not isinstance(noise_sha,str) or len(noise_sha)!=64:raise RequestError('mock missing deterministic noise identity')
        self.frame+=1
        return {'backend_id':self.backend_id,'generation':generation,'frame_id':frame,'slots':[0]*32,
                'scientific_validity':'NONE: contract only, not simulation of FPGA'}
