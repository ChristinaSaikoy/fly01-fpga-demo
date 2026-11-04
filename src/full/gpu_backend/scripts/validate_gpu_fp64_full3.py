from pathlib import Path
import hashlib,json,sys
import numpy as np
ROOT=Path(r"D:\FPGA-AUTO\tasks\FLY-01-FULL-CNS")
F1=ROOT/"FULL-1"; F3=ROOT/"FULL-3"; F4G=ROOT/"FULL-4G"
sys.path.insert(0,str(F4G)); sys.path.insert(0,str(F3))
import GPU_FP64_REFERENCE_LANE as G
from FULL_INPUT_ADAPTER_V1 import FullInputAdapterV1
from FULL_DN_ADAPTER_V1 import FullDNAdapterV1

def sha_arr(a): return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()

streams=json.loads((F4G/"FULL3_SOURCE_DRIVE_STREAMS.json").read_text(encoding="utf-8"))["streams"]
inp=json.loads((F1/"INPUT_311_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
dm=json.loads((F1/"DN_32_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
inp=sorted(inp,key=lambda x:int(x["input_slot"])); dm=sorted(dm,key=lambda x:int(x["slot_index"]))
input_idx=np.asarray([int(x["runtime_index"]) for x in inp],np.int32)
dn_idx=np.asarray([int(x["runtime_index"]) for x in dm],np.int32)
ia=FullInputAdapterV1(input_idx); da=FullDNAdapterV1(dn_idx)

lane=G.GPUFP64ReferenceLane(event_capacity=400000)
results={}
for scenario in ("NEUTRAL","LEFT","RIGHT","CENTER"):
    ref=json.loads((F3/f"RUN_{scenario}.json").read_text(encoding="utf-8"))
    lane.reset()
    ext_chunks=[]; spike_chunks=[]; dnframes=[]
    perf=[]
    for f in streams[scenario]["frames"]:
        k=int(f["frame_id"]); q=f["q_vector"]
        drive=ia.adapt(q,k,f["source_feedback_frame_id"],k)
        if len(drive.external_events): ext_chunks.append(drive.external_events)
        rr=lane.run_ticks(200,events=[tuple(map(int,x)) for x in drive.external_events],
                          rfc_zero_targets=drive.active_runtime_indices,
                          capture_events=True,start_tick=k*200,reset_event_buffer=True)
        if len(rr["events"]): spike_chunks.append(rr["events"])
        counts=np.asarray(rr["dn_counts"],dtype=np.int64)
        slots=(counts>0).astype(np.int32)
        dnframes.append({
          "frame_id":k,"timestamp_s":k*0.02,"dt_s":0.02,
          "slots":[int(x) for x in slots],
          "source_id":"FullMaleCNSOffline","replay_id":"FULL3_"+scenario,
          "stimulus_state":f["applied_group"],"source_timestep":k,
          "schema_version":"demo.dnframe.v1",
          "telemetry_spike_counts":[int(x) for x in counts],
          "full_tick_start":k*200,"full_tick_end":k*200+199
        })
        perf.append({"frame_id":k,"compute_ms":rr["compute_ms"],"h2d_ms":rr["h2d_ms"],"d2h_ms":rr["d2h_ms"]})
    ext=np.concatenate(ext_chunks) if ext_chunks else np.empty((0,2),np.int32)
    spikes=np.concatenate(spike_chunks) if spike_chunks else np.empty((0,2),np.int32)
    state=lane.state_to_host(); hashes=lane.state_hashes()
    checks={
      "external_event_stream":sha_arr(ext)==ref["external_event_stream_sha256"],
      "full_spike_stream":sha_arr(spikes)==ref["full_spike_stream_sha256"],
      "dnframe_stream":da.canonical_stream_sha256(dnframes)==ref["dnframe_stream_sha256"],
      "final_state":hashes["state_digest"]==ref["final_state_sha256"],
      "final_v":hashes["final_v_sha256"]==ref["final_v_sha256"],
      "final_g":hashes["final_g_sha256"]==ref["final_g_sha256"],
      "last_spike":hashes["last_spike_sha256"]==ref["last_spike_sha256"],
      "delay_ring":hashes["delay_ring_sha256"]==ref["delay_ring_sha256"],
      "spike_count_vector":hashes["spike_count_vector_sha256"]==ref["spike_count_vector_sha256"],
      "external_event_count":len(ext)==ref["total_external_events"],
      "full_spike_count":len(spikes)==ref["total_full_spikes"],
      "active_neurons":int(np.count_nonzero(state["spike_counts"]))==ref["active_full_neurons"],
      "dn32_total_spikes":sum(sum(x["telemetry_spike_counts"]) for x in dnframes)==ref["dn32_total_spikes"],
      "dnframe_binary":all(all(x in (0,1) for x in f["slots"]) for f in dnframes)
    }
    res={
      "scenario":scenario,"checks":checks,"HASH_PARITY":"PASS" if all(checks.values()) else "FAIL",
      "gpu_hashes":{"external_event_stream_sha256":sha_arr(ext),"full_spike_stream_sha256":sha_arr(spikes),
                    "dnframe_stream_sha256":da.canonical_stream_sha256(dnframes),**hashes},
      "counts":{"external_events":len(ext),"full_spikes":len(spikes),
                "active_neurons":int(np.count_nonzero(state["spike_counts"])),
                "dn32_spikes":sum(sum(x["telemetry_spike_counts"]) for x in dnframes)},
      "max_abs_v_delta_mV":0.0 if checks["final_v"] else None,
      "max_abs_g_delta_mV":0.0 if checks["final_g"] else None,
      "parity_instrumented_frame_perf":perf
    }
    if scenario=="CENTER":
        res["frozen_center_hash_check"]={
          "external":res["gpu_hashes"]["external_event_stream_sha256"]=="6a1044e823cbad610622ddbead2172882fd58a7881724cbe156ec10fe5471c84",
          "spikes":res["gpu_hashes"]["full_spike_stream_sha256"]=="1bcf9c8d799324b8b4fef17081402a187b65d34a0b81591223c52575a7188614",
          "dnframe":res["gpu_hashes"]["dnframe_stream_sha256"]=="d69879227ae76f4e88b528940896c7257f00ced30e8673c36fddf9b2e67dd89c",
          "state":res["gpu_hashes"]["state_digest"]=="fb91ad3c7967fac3a0a7cfd046b30514fe5a17ff1fb6a566458c09436bead808"
        }
    results[scenario]=res
report={"backend":lane.backend_id,"precision":"float64","scenarios":results,
        "FULL3_SCENARIO_PARITY":"PASS" if all(x["HASH_PARITY"]=="PASS" for x in results.values()) else "FAIL",
        "DN32_OUTPUT":"PASS" if all(x["checks"]["dnframe_binary"] and x["checks"]["dnframe_stream"] for x in results.values()) else "FAIL",
        "resource":lane.memory_profile()}
(F4G/"FP64_FULL3_PARITY.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
print(json.dumps({s:{"parity":r["HASH_PARITY"],"counts":r["counts"],"checks":r["checks"]} for s,r in results.items()},indent=2))
print("FULL3_SCENARIO_PARITY",report["FULL3_SCENARIO_PARITY"])
raise SystemExit(0 if report["FULL3_SCENARIO_PARITY"]=="PASS" else 1)
