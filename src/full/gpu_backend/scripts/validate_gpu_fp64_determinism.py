from pathlib import Path
import hashlib,json,sys
import numpy as np
ROOT=Path(r"D:\FPGA-AUTO\tasks\FLY-01-FULL-CNS")
F1=ROOT/"FULL-1"; F3=ROOT/"FULL-3"; F4G=ROOT/"FULL-4G"
sys.path.insert(0,str(F4G)); sys.path.insert(0,str(F3))
import GPU_FP64_REFERENCE_LANE as G
from FULL_INPUT_ADAPTER_V1 import FullInputAdapterV1
from FULL_DN_ADAPTER_V1 import FullDNAdapterV1

def sha(a): return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()
streams=json.loads((F4G/"FULL3_SOURCE_DRIVE_STREAMS.json").read_text(encoding="utf-8"))["streams"]["CENTER"]["frames"]
inp=json.loads((F1/"INPUT_311_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
dn=json.loads((F1/"DN_32_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
inp=sorted(inp,key=lambda x:int(x["input_slot"])); dn=sorted(dn,key=lambda x:int(x["slot_index"]))
ia=FullInputAdapterV1(np.asarray([int(x["runtime_index"]) for x in inp],np.int32))
da=FullDNAdapterV1(np.asarray([int(x["runtime_index"]) for x in dn],np.int32))
lane=G.GPUFP64ReferenceLane(event_capacity=400000)
runs=[]
for rep in range(3):
    lane.reset()
    extc=[]; spc=[]; dfs=[]
    for f in streams:
        k=f["frame_id"]
        d=ia.adapt(f["q_vector"],k,f["source_feedback_frame_id"],k)
        if len(d.external_events): extc.append(d.external_events)
        rr=lane.run_ticks(200,events=[tuple(map(int,x)) for x in d.external_events],
                          rfc_zero_targets=d.active_runtime_indices,capture_events=True,
                          start_tick=k*200,reset_event_buffer=True)
        if len(rr["events"]): spc.append(rr["events"])
        counts=np.asarray(rr["dn_counts"],np.int64)
        dfs.append({"frame_id":k,"timestamp_s":k*0.02,"dt_s":0.02,
          "slots":[int(x) for x in (counts>0).astype(np.int32)],
          "source_id":"FullMaleCNSOffline","replay_id":"FULL3_CENTER",
          "stimulus_state":f["applied_group"],"source_timestep":k,
          "schema_version":"demo.dnframe.v1",
          "telemetry_spike_counts":[int(x) for x in counts],
          "full_tick_start":k*200,"full_tick_end":k*200+199})
    ext=np.concatenate(extc) if extc else np.empty((0,2),np.int32)
    spikes=np.concatenate(spc) if spc else np.empty((0,2),np.int32)
    h=lane.state_hashes()
    runs.append({"rep":rep+1,"external_event_stream_sha256":sha(ext),
      "full_spike_stream_sha256":sha(spikes),
      "dnframe_stream_sha256":da.canonical_stream_sha256(dfs),
      **h})
fields=["external_event_stream_sha256","full_spike_stream_sha256","dnframe_stream_sha256",
        "state_digest","final_v_sha256","final_g_sha256","last_spike_sha256",
        "delay_ring_sha256","spike_count_vector_sha256"]
same={k:len({r[k] for r in runs})==1 for k in fields}
report={"backend":lane.backend_id,"precision":"float64","scenario":"CENTER",
        "runs":runs,"identical":same,"DETERMINISM":"PASS" if all(same.values()) else "FAIL"}
(F4G/"FP64_DETERMINISM.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
print(json.dumps({"identical":same,"DETERMINISM":report["DETERMINISM"]},indent=2))
raise SystemExit(0 if report["DETERMINISM"]=="PASS" else 1)
