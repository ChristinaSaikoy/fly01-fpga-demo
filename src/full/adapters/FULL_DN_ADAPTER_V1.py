"""FULL_DN_ADAPTER_V1

Engineering adapter from Full MaleCNS spike events to the frozen DEMO DNFrame[32]
binary interface. A slot is 1 iff its frozen DN body/runtime index emits at least
one spike within the exact 200-tick Full-LIF window for that FLY frame.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
import hashlib,json
import numpy as np

FULL_TICKS_PER_FLY_FRAME=200
FLY_DT_S=0.02

class FullDNAdapterV1:
    adapter_id="FULL_DN_ADAPTER_V1"
    aggregation="20-ms window OR"
    output_contract="32 binary integer slots in frozen slot order"

    def __init__(self,dn_runtime_indices):
        x=np.asarray(dn_runtime_indices,dtype=np.int32)
        if x.shape!=(32,) or np.unique(x).size!=32:
            raise ValueError("dn_runtime_indices must be 32 unique indices")
        self.dn_runtime_indices=x.copy()
        self._lookup={int(g):i for i,g in enumerate(x)}

    def aggregate_window(self,events,fly_frame_id:int,source_id="FullMaleCNSOffline",
                         replay_id=None,stimulus_state="OFFLINE"):
        ev=np.asarray(events,dtype=np.int32)
        if ev.size==0:
            ev=np.empty((0,2),dtype=np.int32)
        if ev.ndim!=2 or ev.shape[1]!=2:
            raise ValueError("events must be [tick,runtime_index] pairs")
        start=int(fly_frame_id)*FULL_TICKS_PER_FLY_FRAME
        end=start+FULL_TICKS_PER_FLY_FRAME-1
        if len(ev):
            mask=(ev[:,0]>=start)&(ev[:,0]<=end)
            w=ev[mask]
        else:
            w=ev
        counts=np.zeros(32,dtype=np.int64)
        for idx in w[:,1] if len(w) else ():
            slot=self._lookup.get(int(idx))
            if slot is not None:
                counts[slot]+=1
        slots=(counts>0).astype(np.int32)
        frame={
          "frame_id":int(fly_frame_id),
          "timestamp_s":float(fly_frame_id)*FLY_DT_S,
          "dt_s":FLY_DT_S,
          "slots":[int(x) for x in slots],
          "source_id":source_id,
          "replay_id":replay_id,
          "stimulus_state":stimulus_state,
          "source_timestep":int(fly_frame_id),
          "schema_version":"demo.dnframe.v1",
          "telemetry_spike_counts":[int(x) for x in counts],
          "full_tick_start":start,
          "full_tick_end":end,
        }
        if any(x not in (0,1) for x in frame["slots"]) or len(frame["slots"])!=32:
            raise AssertionError("DNFrame binary contract violated")
        return frame

    @staticmethod
    def canonical_stream_sha256(frames):
        # Frozen mapper-visible fields only; telemetry is excluded.
        visible=[{k:f[k] for k in ("frame_id","timestamp_s","dt_s","slots","source_id",
                                    "replay_id","stimulus_state","source_timestep","schema_version")}
                 for f in frames]
        raw=json.dumps(visible,separators=(",",":"),sort_keys=True,ensure_ascii=False).encode()
        return hashlib.sha256(raw).hexdigest()
