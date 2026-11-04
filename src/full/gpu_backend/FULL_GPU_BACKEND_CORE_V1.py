"""FLY01_FULL_BACKEND_PROTOCOL_V1 compatible GPU core.

Same request/order/reset/retry contract as FULL-4 CPU core.
Backend computation is GPU_FP64_CUPY_2KERNEL_CUDAGRAPH_V1.
Default STEP reads back only DN32 counts/slots plus state digest telemetry;
it does not read back a dense spike raster.
"""
from __future__ import annotations
from pathlib import Path
import copy,hashlib,json,sys,time
import numpy as np

BASE=Path(r"D:\FPGA-AUTO\tasks\FLY-01-FULL-CNS")
F1=BASE/"FULL-1"; F3=BASE/"FULL-3"; F4=BASE/"FULL-4"; F4G=BASE/"FULL-4G"
sys.path.insert(0,str(F4)); sys.path.insert(0,str(F3)); sys.path.insert(0,str(F4G))
import FULL_BACKEND_CORE_V1 as B
from FULL_INPUT_ADAPTER_V1 import FullInputAdapterV1
from FULL_DN_ADAPTER_V1 import FullDNAdapterV1
from GPU_FP64_OPTIMIZED_LANE import GPUFP64OptimizedLane

GPU_BACKEND_ID="GPU_FP64_CUPY_2KERNEL_CUDAGRAPH_V1"

class FullGPUBackendCoreV1(B.FullBackendCoreV1):
    def _load_frozen_runtime(self):
        im=json.loads((F1/"INPUT_311_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
        dm=json.loads((F1/"DN_32_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
        im=sorted(im,key=lambda x:int(x["input_slot"])); dm=sorted(dm,key=lambda x:int(x["slot_index"]))
        self.input_runtime_indices=np.asarray([int(x["runtime_index"]) for x in im],np.int32)
        self.dn_runtime_indices=np.asarray([int(x["runtime_index"]) for x in dm],np.int32)
        self.input_adapter=FullInputAdapterV1(self.input_runtime_indices)
        self.dn_adapter=FullDNAdapterV1(self.dn_runtime_indices)
        self.gpu=GPUFP64OptimizedLane(event_capacity=10000)
        self.gpu._ensure_graph(False)
        self.gpu.reset()
        self.pack=True

    def _reset_state_only(self):
        self.gpu.reset()
        self.current_tick=0
        self.expected_frame_id=0
        self._cache={}
        self._dnframes=[]
        self._external_hasher=hashlib.sha256()
        self._total_external_events=0

    def state_digest(self):
        return self.gpu.state_hashes()["state_digest"]

    def state_hashes(self):
        return self.gpu.state_hashes()

    def warmup(self):
        # Graph already compiled in _load_frozen_runtime.
        return

    def status(self):
        out=super().status()
        out["backend_id"]=GPU_BACKEND_ID
        out["gpu_backend"]=True
        out["precision"]="float64"
        return out

    def _execute_window(self,req):
        frame=int(req["frame_id"])
        t0=time.perf_counter()
        ta=time.perf_counter()
        drive=self.input_adapter.adapt(req["q_vector"],frame,req.get("source_feedback_frame_id"),frame)
        adapter_pre_ms=(time.perf_counter()-ta)*1000.0
        active=np.asarray(drive.active_runtime_indices,np.int32)
        ext_ticks=(33,100,166) if len(active) else ()
        gout=self.gpu.run_frame(active,ext_ticks,capture_events=False,use_graph=True,tick_base=frame*200)
        self.current_tick=self.gpu.current_tick

        td=time.perf_counter()
        counts=np.asarray(gout["dn_counts"],dtype=np.int64)
        slots=(counts>0).astype(np.int32)
        dnf={
          "frame_id":frame,"timestamp_s":frame*0.02,"dt_s":0.02,
          "slots":[int(x) for x in slots],
          "source_id":req.get("dnframe_source_id","FullMaleCNSOnline"),
          "replay_id":req.get("dnframe_replay_id"),
          "stimulus_state":req.get("dnframe_stimulus_state","ONLINE"),
          "source_timestep":frame,"schema_version":"demo.dnframe.v1",
          "telemetry_spike_counts":[int(x) for x in counts],
          "full_tick_start":frame*200,"full_tick_end":frame*200+199
        }
        self._dnframes.append(dnf)
        adapter_post_ms=(time.perf_counter()-td)*1000.0

        ext_raw=np.ascontiguousarray(drive.external_events,dtype=np.int32).tobytes()
        self._external_hasher.update(ext_raw)
        self._total_external_events += len(drive.external_events)
        hs=self.state_hashes()
        compute_wall_ms=(time.perf_counter()-t0)*1000.0
        return {
          "protocol_version":B.PROTOCOL_VERSION,
          "session_id":B.SESSION_ID,
          "reset_generation":self.reset_generation,
          "frame_id":frame,
          "full_tick_start":frame*200,
          "full_tick_end":frame*200+199,
          "dn_slots":dnf["slots"],
          "dn_spike_counts":dnf["telemetry_spike_counts"],
          "dnframe_sha256":self.dn_adapter.canonical_stream_sha256([dnf]),
          "dnframe_stream_sha256_cumulative":self.dn_adapter.canonical_stream_sha256(self._dnframes),
          "state_digest":hs["state_digest"],
          "compute_wall_ms":compute_wall_ms,
          "runtime_wall_ms":float(gout["compute_ms"]),
          "adapter_wall_ms":adapter_pre_ms+adapter_post_ms,
          "h2d_ms":float(gout["h2d_ms"]),
          "d2h_ms":float(gout["d2h_ms"]),
          "status":"PASS","error_code":"NONE","replayed_response":"NO",
          "external_event_count":int(len(drive.external_events)),
          "cumulative_external_event_count":int(self._total_external_events),
          "external_event_stream_sha256_cumulative":self._external_hasher.hexdigest(),
          **hs
        }
