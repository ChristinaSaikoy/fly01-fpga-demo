"""Reference localhost client for FLY01_FULL_BACKEND_PROTOCOL_V1."""
from __future__ import annotations
import hashlib,json,time,urllib.error,urllib.request

PROTOCOL_VERSION="FLY01_FULL_BACKEND_PROTOCOL_V1"
SESSION_ID="full4-reference-session"
BASE_URL="http://127.0.0.1:18741"

def q_vector_sha256(q):
    raw=json.dumps([int(x) for x in q],separators=(",",":"),ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()

def _request(method,path,obj=None,timeout_s=30.0):
    data=None
    headers={}
    if obj is not None:
        data=json.dumps(obj,separators=(",",":"),ensure_ascii=False).encode("utf-8")
        headers["Content-Type"]="application/json"
    req=urllib.request.Request(BASE_URL+path,data=data,headers=headers,method=method)
    t0=time.perf_counter()
    try:
        with urllib.request.urlopen(req,timeout=timeout_s) as r:
            raw=r.read()
            code=r.status
    except urllib.error.HTTPError as e:
        raw=e.read()
        code=e.code
    elapsed_ms=(time.perf_counter()-t0)*1000.0
    return code,json.loads(raw.decode("utf-8")),elapsed_ms

def status(timeout_s=30.0):
    return _request("GET","/status",timeout_s=timeout_s)

def reset(timeout_s=30.0):
    return _request("POST","/reset",{
      "protocol_version":PROTOCOL_VERSION,
      "session_id":SESSION_ID
    },timeout_s)

def step(reset_generation,frame_id,q_vector,source_feedback_frame_id,
         dnframe_source_id="FullMaleCNSOnline",dnframe_replay_id=None,
         dnframe_stimulus_state="ONLINE",timeout_s=30.0):
    q=[int(x) for x in q_vector]
    req={
      "protocol_version":PROTOCOL_VERSION,
      "session_id":SESSION_ID,
      "reset_generation":int(reset_generation),
      "frame_id":int(frame_id),
      "target_neural_timestep_id":int(frame_id),
      "source_feedback_frame_id":source_feedback_frame_id,
      "q_vector":q,
      "q_vector_sha256":q_vector_sha256(q),
      "dnframe_source_id":dnframe_source_id,
      "dnframe_replay_id":dnframe_replay_id,
      "dnframe_stimulus_state":dnframe_stimulus_state
    }
    return _request("POST","/step",req,timeout_s)

def raw_step(req,timeout_s=30.0):
    return _request("POST","/step",req,timeout_s)

def raw_post(path,obj,timeout_s=30.0):
    return _request("POST",path,obj,timeout_s)
