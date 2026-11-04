"""FULL_INPUT_ADAPTER_V1

Engineering adapter from frozen Candidate-B SourceDrive q-vector semantics to
deterministic external events for the FULL_REFERENCE_RUNTIME_V1.

No Candidate-B q magnitude is interpreted as voltage, rate, or synaptic weight.
Only q==0 vs q!=0 is used.

Deterministic 150 Hz equivalent:
  20 ms FLY frame = 200 Full-LIF ticks at 0.1 ms
  150 Hz * 0.020 s = 3 events per active input per frame
  event ticks are centered uniform thirds: floor((j+0.5)*200/3)
  => local ticks [33, 100, 166].
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import numpy as np

FLY_DT_S=0.02
FULL_DT_MS=0.1
FULL_TICKS_PER_FLY_FRAME=200
EVENTS_PER_ACTIVE_INPUT_PER_FRAME=3
LOCAL_EVENT_TICKS=tuple(int(np.floor((j+0.5)*FULL_TICKS_PER_FLY_FRAME/
                                     EVENTS_PER_ACTIVE_INPUT_PER_FRAME))
                        for j in range(EVENTS_PER_ACTIVE_INPUT_PER_FRAME))
assert LOCAL_EVENT_TICKS==(33,100,166)

@dataclass(frozen=True)
class FullInputDriveFrame:
    fly_frame_id:int
    source_feedback_frame_id:int|None
    target_neural_frame_id:int
    full_tick_start:int
    full_tick_end:int
    active_ordinals:tuple[int,...]
    active_runtime_indices:tuple[int,...]
    local_event_ticks:tuple[int,...]
    external_events:np.ndarray

class FullInputAdapterV1:
    adapter_id="FULL_INPUT_ADAPTER_V1"
    identity="ENGINEERING_ADAPTER"
    active_policy="q == 0 inactive; q != 0 active"
    external_drive_policy="150 Hz deterministic equivalent; 3 centered-uniform events per active input per 20 ms frame"
    input_refractory_policy="active input runtime indices use rfc=0 ms for that Full window; inactive input targets use normal 2.2 ms"

    def __init__(self,input_runtime_indices):
        x=np.asarray(input_runtime_indices,dtype=np.int32)
        if x.shape!=(311,) or np.unique(x).size!=311:
            raise ValueError("input_runtime_indices must be 311 unique indices")
        self.input_runtime_indices=x.copy()

    def adapt(self,qvec,fly_frame_id:int,source_feedback_frame_id:int|None,
              target_neural_frame_id:int|None=None):
        q=np.asarray(qvec,dtype=np.int64)
        if q.shape!=(311,):
            raise ValueError("qvec must contain exactly 311 entries")
        if target_neural_frame_id is None:
            target_neural_frame_id=int(fly_frame_id)
        if int(target_neural_frame_id)!=int(fly_frame_id):
            raise ValueError("offline Full window target must equal current neural frame id")
        active=np.flatnonzero(q!=0).astype(np.int32)
        targets=self.input_runtime_indices[active]
        start=int(fly_frame_id)*FULL_TICKS_PER_FLY_FRAME
        end=start+FULL_TICKS_PER_FLY_FRAME-1
        if len(targets):
            ticks=np.repeat(np.asarray(LOCAL_EVENT_TICKS,dtype=np.int32),len(targets))+start
            neurons=np.tile(targets,len(LOCAL_EVENT_TICKS))
            events=np.column_stack((ticks,neurons)).astype(np.int32,copy=False)
        else:
            events=np.empty((0,2),dtype=np.int32)
        return FullInputDriveFrame(
            fly_frame_id=int(fly_frame_id),
            source_feedback_frame_id=None if source_feedback_frame_id is None else int(source_feedback_frame_id),
            target_neural_frame_id=int(target_neural_frame_id),
            full_tick_start=start,full_tick_end=end,
            active_ordinals=tuple(int(x) for x in active),
            active_runtime_indices=tuple(int(x) for x in targets),
            local_event_ticks=LOCAL_EVENT_TICKS,
            external_events=events)

    def refractory_ticks_for_frame(self,active_runtime_indices,n_neurons:int,
                                   normal_refractory_ticks:int=22):
        r=np.full(int(n_neurons),int(normal_refractory_ticks),dtype=np.int32)
        active=np.asarray(active_runtime_indices,dtype=np.int32)
        if len(active):
            r[active]=0
        return r

    @staticmethod
    def event_stream_sha256(events):
        a=np.asarray(events,dtype=np.int32)
        return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()
