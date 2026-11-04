"""FULL_BACKEND_CORE_V1

Stateful lockstep wrapper around the frozen FULL_REFERENCE_RUNTIME_V1 and
FULL-3 adapters. Backend boundary is SourceDrive q_vector[311] -> DNFrame[32].
No visual encoder, motor mapper, BodyRuntime, renderer, GPU, or WAN behavior.
"""
from __future__ import annotations
from pathlib import Path
import copy, hashlib, json, sys, threading, time
import numpy as np

BASE=Path(r"D:\FPGA-AUTO\tasks\FLY-01-FULL-CNS")
F1=BASE/"FULL-1"
F2=BASE/"FULL-2"
F3=BASE/"FULL-3"
PACK=F1/"canonical_pack_v1"

sys.path.insert(0,str(F2))
sys.path.insert(0,str(F3))
import FULL_REFERENCE_RUNTIME_V1 as rt
from FULL_INPUT_ADAPTER_V1 import FullInputAdapterV1
from FULL_DN_ADAPTER_V1 import FullDNAdapterV1

PROTOCOL_VERSION="FLY01_FULL_BACKEND_PROTOCOL_V1"
BACKEND_ID="FULL_BACKEND_CORE_V1"
SESSION_ID="full4-reference-session"
EXPECTED_PACK_SHA="b9a9168a653a90fd0c4405a78473a5f562ce55116361ca4f3e8781bef038e4a7"
EXPECTED_RUNTIME_SHA="942b1b06214c8de6ff6bad833e26bdd71ea0d2bcc6abe016fb3836eb238c2c8d"
EXPECTED_INPUT_ADAPTER_SHA="2abe9d79d6fb56a616d9e928cd9189ed7387f31ad60c3d057a142413c18a25da"
EXPECTED_DN_ADAPTER_SHA="1c880328df7febd816b6d23ec513faba042272e28420e9b6bb2760134fed9bbb"

def sha_file(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(1<<20),b""):
            h.update(b)
    return h.hexdigest()

def pack_sha():
    rows=[]
    for p in sorted(x for x in PACK.iterdir() if x.is_file()):
        rows.append(f"{p.name}\t{p.stat().st_size}\t{sha_file(p)}\n")
    return hashlib.sha256("".join(rows).encode()).hexdigest()

def q_vector_sha256(q):
    raw=json.dumps([int(x) for x in q],separators=(",",":"),ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()

def array_sha(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()

def payload_fingerprint(req):
    payload={
      "frame_id":req.get("frame_id"),
      "target_neural_timestep_id":req.get("target_neural_timestep_id"),
      "source_feedback_frame_id":req.get("source_feedback_frame_id"),
      "q_vector_sha256":req.get("q_vector_sha256"),
      "dnframe_source_id":req.get("dnframe_source_id","FullMaleCNSOnline"),
      "dnframe_replay_id":req.get("dnframe_replay_id"),
      "dnframe_stimulus_state":req.get("dnframe_stimulus_state","ONLINE")
    }
    raw=json.dumps(payload,separators=(",",":"),sort_keys=True,ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()
class FullBackendCoreV1:
    def __init__(self):
        self._lock=threading.Lock()
        self.last_error=None
        self.reset_generation=0
        self.expected_frame_id=0
        self.current_tick=0
        self._cache={}
        self._dnframes=[]
        self._external_hasher=hashlib.sha256()
        self._spike_hasher=hashlib.sha256()
        self._total_external_events=0
        self._total_spikes=0

        self.integrity=self._startup_integrity()
        self.service_ready=bool(self.integrity["PASS"])
        self.pack=None
        self.input_adapter=None
        self.dn_adapter=None
        if self.service_ready:
            self._load_frozen_runtime()
            self._reset_state_only()

    def _startup_integrity(self):
        input_map=json.loads((F1/"INPUT_311_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
        dn_map=json.loads((F1/"DN_32_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
        checks={
          "pack_sha256":{"expected":EXPECTED_PACK_SHA,"actual":pack_sha()},
          "runtime_sha256":{"expected":EXPECTED_RUNTIME_SHA,"actual":sha_file(F2/"FULL_REFERENCE_RUNTIME_V1.py")},
          "input_adapter_sha256":{"expected":EXPECTED_INPUT_ADAPTER_SHA,"actual":sha_file(F3/"FULL_INPUT_ADAPTER_V1.py")},
          "dn_adapter_sha256":{"expected":EXPECTED_DN_ADAPTER_SHA,"actual":sha_file(F3/"FULL_DN_ADAPTER_V1.py")},
          "input_binding_count":{"expected":311,"actual":len(input_map)},
          "input_binding_unique_runtime":{"expected":311,"actual":len({int(x["runtime_index"]) for x in input_map})},
          "dn_binding_count":{"expected":32,"actual":len(dn_map)},
          "dn_binding_unique_runtime":{"expected":32,"actual":len({int(x["runtime_index"]) for x in dn_map})},
        }
        for x in checks.values():
            x["PASS"]=x["expected"]==x["actual"]
        return {"checks":checks,"PASS":all(x["PASS"] for x in checks.values())}

    def _load_frozen_runtime(self):
        self.pack=rt.load_pack(PACK)
        im=json.loads((F1/"INPUT_311_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
        dm=json.loads((F1/"DN_32_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
        im=sorted(im,key=lambda x:int(x["input_slot"]))
        dm=sorted(dm,key=lambda x:int(x["slot_index"]))
        self.input_runtime_indices=np.asarray([int(x["runtime_index"]) for x in im],dtype=np.int32)
        self.dn_runtime_indices=np.asarray([int(x["runtime_index"]) for x in dm],dtype=np.int32)
        self.input_adapter=FullInputAdapterV1(self.input_runtime_indices)
        self.dn_adapter=FullDNAdapterV1(self.dn_runtime_indices)

    def _reset_state_only(self):
        n=len(self.pack["body_ids"])
        self.v,self.g,self.last_spike,self.rfc_ticks,self.ring,self.counts=rt.initialize_state(n)
        self.not_ref=np.empty(n,dtype=np.uint8)
        self.spike=np.empty(n,dtype=np.uint8)
        self.contrib=np.empty(n,dtype=np.int64)
        self.fired=np.empty(n,dtype=np.int32)
        self.current_tick=0
        self.expected_frame_id=0
        self._cache={}
        self._dnframes=[]
        self._external_hasher=hashlib.sha256()
        self._spike_hasher=hashlib.sha256()
        self._total_external_events=0
        self._total_spikes=0

    def state_digest(self):
        h=hashlib.sha256()
        for a in (self.v,self.g,self.last_spike,self.rfc_ticks,self.ring,self.counts):
            h.update(str(a.dtype).encode())
            h.update(np.asarray(a.shape,dtype=np.int64).tobytes())
            h.update(np.ascontiguousarray(a).tobytes())
        h.update(np.asarray([self.current_tick],dtype=np.int64).tobytes())
        return h.hexdigest()

    def state_hashes(self):
        return {
          "state_digest":self.state_digest(),
          "final_v_sha256":array_sha(self.v),
          "final_g_sha256":array_sha(self.g),
          "last_spike_sha256":array_sha(self.last_spike),
          "delay_ring_sha256":array_sha(self.ring),
          "spike_count_vector_sha256":array_sha(self.counts),
        }
    def _error(self,code,message,frame_id=None):
        self.last_error={"error_code":code,"message":message,"frame_id":frame_id}
        return {
          "protocol_version":PROTOCOL_VERSION,
          "session_id":SESSION_ID,
          "reset_generation":self.reset_generation,
          "frame_id":frame_id,
          "status":"ERROR",
          "error_code":code,
          "message":message,
          "replayed_response":"NO"
        }

    def status(self):
        out={
          "protocol_version":PROTOCOL_VERSION,
          "service_ready":self.service_ready,
          "backend_id":BACKEND_ID,
          "pack_sha256":EXPECTED_PACK_SHA,
          "runtime_version":"FULL_REFERENCE_RUNTIME_V1",
          "input_adapter_version":"FULL_INPUT_ADAPTER_V1",
          "dn_adapter_version":"FULL_DN_ADAPTER_V1",
          "current_session":SESSION_ID if self.service_ready else None,
          "reset_generation":self.reset_generation,
          "expected_frame_id":self.expected_frame_id,
          "full_tick_counter":self.current_tick,
          "busy":self._lock.locked(),
          "last_error":self.last_error,
          "startup_integrity":self.integrity
        }
        if self.service_ready:
            out.update(self.state_hashes())
        return out

    def reset(self,req):
        if not self.service_ready:
            return self._error("SERVICE_NOT_READY","startup integrity failed")
        if not self._lock.acquire(blocking=False):
            return self._error("BUSY","STEP or RESET already in progress")
        try:
            if not isinstance(req,dict):
                return self._error("MALFORMED_PACKET","RESET request must be object")
            if req.get("protocol_version")!=PROTOCOL_VERSION:
                return self._error("WRONG_PROTOCOL_VERSION","protocol version mismatch")
            if req.get("session_id")!=SESSION_ID:
                return self._error("WRONG_SESSION","session mismatch")
            self.reset_generation += 1
            self._reset_state_only()
            self.last_error=None
            return {
              "protocol_version":PROTOCOL_VERSION,
              "session_id":SESSION_ID,
              "reset_generation":self.reset_generation,
              "frame_expected":0,
              "full_tick_counter":0,
              "state_digest":self.state_digest(),
              "status":"PASS",
              "error_code":"NONE"
            }
        finally:
            self._lock.release()

    def _validate_step(self,req):
        if not isinstance(req,dict):
            return "MALFORMED_PACKET","STEP request must be object"
        if req.get("protocol_version")!=PROTOCOL_VERSION:
            return "WRONG_PROTOCOL_VERSION","protocol version mismatch"
        if req.get("session_id")!=SESSION_ID:
            return "WRONG_SESSION","session mismatch"
        if type(req.get("reset_generation")) is not int:
            return "BAD_RESET_GENERATION","reset_generation must be integer"
        if req["reset_generation"]!=self.reset_generation:
            return "STALE_GENERATION","reset_generation does not match current generation"
        if type(req.get("frame_id")) is not int or req["frame_id"]<0:
            return "BAD_FRAME_ID","frame_id must be nonnegative integer"
        if type(req.get("target_neural_timestep_id")) is not int:
            return "BAD_TARGET_NEURAL_TIMESTEP","target_neural_timestep_id must be integer"
        if req["target_neural_timestep_id"]!=req["frame_id"]:
            return "BAD_TARGET_NEURAL_TIMESTEP","target_neural_timestep_id must equal frame_id"
        expected_source=None if req["frame_id"]==0 else req["frame_id"]-1
        if req.get("source_feedback_frame_id")!=expected_source:
            return "BAD_SOURCE_FRAME","source_feedback_frame_id violates one-frame delay contract"
        q=req.get("q_vector")
        if not isinstance(q,list) or len(q)!=311:
            return "BAD_Q_LENGTH","q_vector must have exactly 311 entries"
        if any(type(x) is not int for x in q):
            return "NONINTEGER_Q","all q_vector entries must be JSON integers"
        qh=req.get("q_vector_sha256")
        if not isinstance(qh,str) or len(qh)!=64:
            return "MISSING_Q_HASH","q_vector_sha256 missing or malformed"
        actual=q_vector_sha256(q)
        if qh!=actual:
            return "PAYLOAD_HASH_MISMATCH","q_vector_sha256 does not match canonical q_vector"
        return None
    def warmup(self):
        empty=np.empty(0,dtype=np.int32)
        rt._step(np.array([0],dtype=np.int32),empty,empty,
                 np.empty(0,dtype=np.float64),np.empty(0,dtype=np.float64),
                 np.empty(0,dtype=np.int32),np.empty(0,dtype=np.int32),
                 np.empty((rt.DELAY_TICKS,0),dtype=np.uint8),
                 np.empty(0,dtype=np.int64),np.empty(0,dtype=np.uint8),
                 np.empty(0,dtype=np.uint8),np.empty(0,dtype=np.int64),
                 np.empty(0,dtype=np.int32),0,empty,empty)

    def _execute_window(self,req):
        frame=int(req["frame_id"])
        t_all=time.perf_counter()

        ta=time.perf_counter()
        drive=self.input_adapter.adapt(
            req["q_vector"],frame,req.get("source_feedback_frame_id"),frame)
        self.rfc_ticks[:]=rt.REFRACTORY_TICKS
        if drive.active_runtime_indices:
            self.rfc_ticks[np.asarray(drive.active_runtime_indices,dtype=np.int32)]=0
        adapter_pre_ms=(time.perf_counter()-ta)*1000.0

        ext=drive.external_events
        by={}
        if len(ext):
            for t in np.unique(ext[:,0]):
                by[int(t)]=ext[ext[:,0]==t,1].astype(np.int32,copy=False)
        empty=np.empty(0,dtype=np.int32)
        spike_chunks=[]

        tr=time.perf_counter()
        for tick in range(drive.full_tick_start,drive.full_tick_end+1):
            targets=by.get(tick,empty)
            mult=np.ones(len(targets),dtype=np.int32) if len(targets) else empty
            nf=rt._step(self.pack["row_ptr"],self.pack["dst"],self.pack["signed_counts"],
                        self.v,self.g,self.last_spike,self.rfc_ticks,self.ring,self.counts,
                        self.not_ref,self.spike,self.contrib,self.fired,tick,targets,mult)
            if nf:
                rec=np.empty((nf,2),dtype=np.int32)
                rec[:,0]=tick
                rec[:,1]=self.fired[:nf]
                spike_chunks.append(rec)
        runtime_ms=(time.perf_counter()-tr)*1000.0
        spikes=np.concatenate(spike_chunks) if spike_chunks else np.empty((0,2),dtype=np.int32)
        self.current_tick=drive.full_tick_end+1

        td=time.perf_counter()
        dnf=self.dn_adapter.aggregate_window(
            spikes,frame,
            source_id=req.get("dnframe_source_id","FullMaleCNSOnline"),
            replay_id=req.get("dnframe_replay_id"),
            stimulus_state=req.get("dnframe_stimulus_state","ONLINE"))
        adapter_post_ms=(time.perf_counter()-td)*1000.0

        ext_raw=np.ascontiguousarray(ext,dtype=np.int32).tobytes()
        spike_raw=np.ascontiguousarray(spikes,dtype=np.int32).tobytes()
        self._external_hasher.update(ext_raw)
        self._spike_hasher.update(spike_raw)
        self._total_external_events += len(ext)
        self._total_spikes += len(spikes)
        self._dnframes.append(dnf)

        hashes=self.state_hashes()
        visible_dn_hash=self.dn_adapter.canonical_stream_sha256([dnf])
        cumulative_dn_hash=self.dn_adapter.canonical_stream_sha256(self._dnframes)
        compute_ms=(time.perf_counter()-t_all)*1000.0

        response={
          "protocol_version":PROTOCOL_VERSION,
          "session_id":SESSION_ID,
          "reset_generation":self.reset_generation,
          "frame_id":frame,
          "full_tick_start":drive.full_tick_start,
          "full_tick_end":drive.full_tick_end,
          "dn_slots":dnf["slots"],
          "dn_spike_counts":dnf["telemetry_spike_counts"],
          "dnframe_sha256":visible_dn_hash,
          "dnframe_stream_sha256_cumulative":cumulative_dn_hash,
          "state_digest":hashes["state_digest"],
          "compute_wall_ms":compute_ms,
          "runtime_wall_ms":runtime_ms,
          "adapter_wall_ms":adapter_pre_ms+adapter_post_ms,
          "status":"PASS",
          "error_code":"NONE",
          "replayed_response":"NO",
          "external_event_count":int(len(ext)),
          "full_spike_count":int(len(spikes)),
          "cumulative_external_event_count":int(self._total_external_events),
          "cumulative_full_spike_count":int(self._total_spikes),
          "external_event_stream_sha256_cumulative":self._external_hasher.hexdigest(),
          "full_spike_stream_sha256_cumulative":self._spike_hasher.hexdigest(),
          **hashes
        }
        return response
    def step(self,req):
        if not self.service_ready:
            return self._error("SERVICE_NOT_READY","startup integrity failed",
                               req.get("frame_id") if isinstance(req,dict) else None)
        if not self._lock.acquire(blocking=False):
            return {
              "protocol_version":PROTOCOL_VERSION,
              "session_id":SESSION_ID,
              "reset_generation":self.reset_generation,
              "frame_id":req.get("frame_id") if isinstance(req,dict) else None,
              "status":"ERROR",
              "error_code":"BUSY",
              "message":"one STEP/RESET is already in flight",
              "replayed_response":"NO"
            }
        try:
            bad=self._validate_step(req)
            if bad is not None:
                return self._error(bad[0],bad[1],req.get("frame_id") if isinstance(req,dict) else None)

            frame=req["frame_id"]
            qh=req["q_vector_sha256"]
            fp=payload_fingerprint(req)

            if frame < self.expected_frame_id:
                item=self._cache.get(frame)
                if item is None:
                    return self._error("STALE_FRAME","frame is older than retained successful frame",frame)
                if item["q_vector_sha256"]!=qh or item["payload_fingerprint"]!=fp:
                    return self._error("DUPLICATE_FRAME_CONFLICT",
                                       "successful frame already exists with different payload",frame)
                replay=copy.deepcopy(item["response"])
                replay["replayed_response"]="YES"
                return replay

            if frame > self.expected_frame_id:
                return self._error("FRAME_GAP",
                                   f"expected frame {self.expected_frame_id}, received {frame}",frame)

            if self.current_tick != frame*200:
                self.service_ready=False
                return self._error("BACKEND_STATE_INCONSISTENT",
                                   "Full tick counter is inconsistent with expected frame",frame)

            try:
                response=self._execute_window(req)
            except Exception as exc:
                self.service_ready=False
                return self._error("BACKEND_COMPUTE_FAILURE",repr(exc),frame)

            self._cache={frame:{
              "q_vector_sha256":qh,
              "payload_fingerprint":fp,
              "response":copy.deepcopy(response)
            }}
            self.expected_frame_id += 1
            self.last_error=None
            return response
        finally:
            self._lock.release()

