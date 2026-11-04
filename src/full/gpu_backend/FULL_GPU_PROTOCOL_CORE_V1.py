"""Protocol-compatible core for the exact FP64 GPU lane.
Implements the frozen FLY01_FULL_BACKEND_PROTOCOL_V1 JSON contract.
Correctness/compatibility wrapper; benchmark results are measured on the neural lane
without full-state hash readback each frame.
"""
from pathlib import Path
import copy,hashlib,json,sys,time
import numpy as np

ROOT=Path(r"D:\FPGA-AUTO\tasks")
BASE=ROOT/"FLY-01-FULL-CNS"
F1=BASE/"FULL-1"; F3=BASE/"FULL-3"; F4=BASE/"FULL-4"; F4G=BASE/"FULL-4G"
sys.path.insert(0,str(F3)); sys.path.insert(0,str(F4G))
from FULL_INPUT_ADAPTER_V1 import FullInputAdapterV1
from FULL_DN_ADAPTER_V1 import FullDNAdapterV1
from GPU_FP64_OPTIMIZED_LANE import GPUFP64OptimizedLane

PROTOCOL_VERSION="FLY01_FULL_BACKEND_PROTOCOL_V1"
SESSION_ID="full4-reference-session"

def q_vector_sha256(q):
    raw=json.dumps([int(x) for x in q],separators=(",",":"),ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()

class FullGPUProtocolCoreV1:
    def __init__(self):
        im=json.loads((F1/"INPUT_311_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
        dm=json.loads((F1/"DN_32_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
        im=sorted(im,key=lambda x:int(x["input_slot"])); dm=sorted(dm,key=lambda x:int(x["slot_index"]))
        self.input_idx=np.asarray([int(x["runtime_index"]) for x in im],np.int32)
        self.dn_idx=np.asarray([int(x["runtime_index"]) for x in dm],np.int32)
        self.ia=FullInputAdapterV1(self.input_idx)
        self.da=FullDNAdapterV1(self.dn_idx)
        self.gpu=GPUFP64OptimizedLane(event_capacity=10000)
        self.gpu._ensure_graph(False)
        self.gpu.reset()
        self.reset_generation=0
        self.expected_frame_id=0
        self._cache={}
        self._dnframes=[]

    def status(self):
        return {
          "protocol_version":PROTOCOL_VERSION,
          "service_ready":True,
          "backend_id":self.gpu.backend_id,
          "pack_sha256":"b9a9168a653a90fd0c4405a78473a5f562ce55116361ca4f3e8781bef038e4a7",
          "runtime_version":"FULL_REFERENCE_RUNTIME_V1-compatible GPU FP64",
          "input_adapter_version":"FULL_INPUT_ADAPTER_V1",
          "dn_adapter_version":"FULL_DN_ADAPTER_V1",
          "current_session":SESSION_ID,
          "reset_generation":self.reset_generation,
          "expected_frame_id":self.expected_frame_id,
          "full_tick_counter":self.gpu.current_tick,
          "busy":False,
          "last_error":None
        }

    def reset(self,req):
        if req.get("protocol_version")!=PROTOCOL_VERSION or req.get("session_id")!=SESSION_ID:
            return {"status":"ERROR","error_code":"BAD_RESET_REQUEST"}
        self.reset_generation+=1
        self.expected_frame_id=0
        self._cache={}
        self._dnframes=[]
        self.gpu.reset()
        return {"protocol_version":PROTOCOL_VERSION,"session_id":SESSION_ID,
                "reset_generation":self.reset_generation,"frame_expected":0,
                "full_tick_counter":0,"state_digest":self.gpu.state_hashes()["state_digest"],
                "status":"PASS","error_code":"NONE"}

    def step(self,req):
        frame=req.get("frame_id")
        if req.get("protocol_version")!=PROTOCOL_VERSION: return {"status":"ERROR","error_code":"WRONG_PROTOCOL_VERSION"}
        if req.get("session_id")!=SESSION_ID: return {"status":"ERROR","error_code":"WRONG_SESSION"}
        if req.get("reset_generation")!=self.reset_generation: return {"status":"ERROR","error_code":"STALE_GENERATION"}
        if frame!=self.expected_frame_id: return {"status":"ERROR","error_code":"FRAME_ORDER"}
        if req.get("target_neural_timestep_id")!=frame: return {"status":"ERROR","error_code":"BAD_TARGET_NEURAL_TIMESTEP"}
        if req.get("source_feedback_frame_id")!=(None if frame==0 else frame-1): return {"status":"ERROR","error_code":"BAD_SOURCE_FRAME"}
        q=req.get("q_vector")
        if not isinstance(q,list) or len(q)!=311 or any(type(x) is not int for x in q): return {"status":"ERROR","error_code":"BAD_Q"}
        if req.get("q_vector_sha256")!=q_vector_sha256(q): return {"status":"ERROR","error_code":"PAYLOAD_HASH_MISMATCH"}

        t0=time.perf_counter()
        drive=self.ia.adapt(q,frame,req.get("source_feedback_frame_id"),frame)
        active=np.asarray(drive.active_runtime_indices,np.int32)
        out=self.gpu.run_frame(active,drive.local_event_ticks if len(active) else (),
                               capture_events=False,use_graph=True,tick_base=frame*200)
        counts=np.asarray(out["dn_counts"],np.int64)
        dnf={
          "frame_id":frame,"timestamp_s":frame*0.02,"dt_s":0.02,
          "slots":[int(x) for x in (counts>0).astype(np.int32)],
          "source_id":req.get("dnframe_source_id","FullMaleCNSOnline"),
          "replay_id":req.get("dnframe_replay_id"),
          "stimulus_state":req.get("dnframe_stimulus_state","ONLINE"),
          "source_timestep":frame,"schema_version":"demo.dnframe.v1",
          "telemetry_spike_counts":[int(x) for x in counts],
          "full_tick_start":frame*200,"full_tick_end":frame*200+199
        }
        self._dnframes.append(dnf)
        hs=self.gpu.state_hashes()
        resp={
          "protocol_version":PROTOCOL_VERSION,"session_id":SESSION_ID,
          "reset_generation":self.reset_generation,"frame_id":frame,
          "full_tick_start":frame*200,"full_tick_end":frame*200+199,
          "dn_slots":dnf["slots"],"dn_spike_counts":dnf["telemetry_spike_counts"],
          "dnframe_sha256":self.da.canonical_stream_sha256([dnf]),
          "dnframe_stream_sha256_cumulative":self.da.canonical_stream_sha256(self._dnframes),
          "state_digest":hs["state_digest"],
          "compute_wall_ms":float(out["compute_ms"]),
          "runtime_wall_ms":float(out["compute_ms"]),
          "adapter_wall_ms":float(out["h2d_ms"]+out["d2h_ms"]),
          "status":"PASS","error_code":"NONE","replayed_response":"NO",
          **hs
        }
        self.expected_frame_id+=1
        return resp
