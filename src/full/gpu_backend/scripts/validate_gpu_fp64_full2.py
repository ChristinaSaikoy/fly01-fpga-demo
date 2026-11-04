from pathlib import Path
import hashlib,json,sys,time
import numpy as np
ROOT=Path(r"D:\FPGA-AUTO\tasks\FLY-01-FULL-CNS")
F1=ROOT/"FULL-1"; F2=ROOT/"FULL-2"; F4G=ROOT/"FULL-4G"
sys.path.insert(0,str(F4G))
import GPU_FP64_REFERENCE_LANE as G

def sha_arr(a): return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()
ref=json.loads((F2/"RUN_311_INPUT_1000T_R1.json").read_text(encoding="utf-8"))
state=np.load(F2/"events/RUN_311_INPUT_1000T_R1_STATE.npz",allow_pickle=False)
inp=json.loads((F1/"INPUT_311_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
inp=sorted(inp,key=lambda x:int(x["input_slot"]))
input_idx=np.asarray([int(x["runtime_index"]) for x in inp],np.int32)
events=[(t,int(j),1) for t in (0,100,200,300,400,500,600,700,800,900) for j in input_idx]

t0=time.perf_counter()
lane=G.GPUFP64ReferenceLane(event_capacity=200000)
cold_s=time.perf_counter()-t0
lane.reset(rfc_zero_targets=input_idx)
out=lane.run_ticks(1000,events=events,rfc_zero_targets=input_idx,capture_events=True)
gpu_state=lane.state_to_host()

checks={
 "event_stream_sha256":sha_arr(out["events"])==ref["event_stream_sha256"],
 "event_count":len(out["events"])==ref["total_spikes"],
 "spike_count_vector":sha_arr(gpu_state["spike_counts"])==ref["spike_count_vector_sha256"],
 "final_v":sha_arr(gpu_state["v"])==ref["final_v_sha256"],
 "final_g":sha_arr(gpu_state["g"])==ref["final_g_sha256"],
 "last_spike":sha_arr(gpu_state["last_spike_tick"])==ref["last_spike_sha256"],
 "delay_ring":sha_arr(gpu_state["delay_ring"])==ref["delay_ring_sha256"],
 "v_bitwise":np.array_equal(gpu_state["v"],state["v"]),
 "g_bitwise":np.array_equal(gpu_state["g"],state["g"]),
 "last_bitwise":np.array_equal(gpu_state["last_spike_tick"],state["last_spike_tick"]),
 "rfc_bitwise":np.array_equal(gpu_state["rfc_ticks"],state["rfc_ticks"]),
 "ring_bitwise":np.array_equal(gpu_state["delay_ring"],state["delay_ring"]),
 "counts_bitwise":np.array_equal(gpu_state["spike_counts"],state["spike_counts"]),
}
cpu_events=np.fromfile(F2/"events/RUN_311_INPUT_1000T_R1_EVENTS.i32.bin",dtype=np.int32).reshape((-1,2))
event_exact=np.array_equal(out["events"],cpu_events)
checks["events_bitwise"]=event_exact
report={
 "backend":lane.backend_id,"precision":"float64","reference":"FULL-2 RUN_311_INPUT_1000T_R1",
 "cold_construct_wall_s":cold_s,"compute_ms":out["compute_ms"],"h2d_ms":out["h2d_ms"],"d2h_ms":out["d2h_ms"],
 "gpu_event_count":len(out["events"]),"cpu_event_count":len(cpu_events),
 "checks":checks,"FULL_NETWORK_PARITY":"PASS" if all(checks.values()) else "FAIL",
 "max_abs_v_delta_mV":float(np.max(np.abs(gpu_state["v"]-state["v"]))),
 "max_abs_g_delta_mV":float(np.max(np.abs(gpu_state["g"]-state["g"]))),
 "resource":lane.memory_profile(),
 "gpu_hashes":{
   "event_stream_sha256":sha_arr(out["events"]),"spike_count_vector_sha256":sha_arr(gpu_state["spike_counts"]),
   "final_v_sha256":sha_arr(gpu_state["v"]),"final_g_sha256":sha_arr(gpu_state["g"]),
   "last_spike_sha256":sha_arr(gpu_state["last_spike_tick"]),"delay_ring_sha256":sha_arr(gpu_state["delay_ring"])
 }
}
if not event_exact:
    a=out["events"]; b=cpu_events; m=min(len(a),len(b))
    first=next((i for i in range(m) if not np.array_equal(a[i],b[i])),m)
    report["first_spike_divergence_index"]=first
    report["gpu_event_at_divergence"]=a[first].tolist() if first<len(a) else None
    report["cpu_event_at_divergence"]=b[first].tolist() if first<len(b) else None
(F4G/"FP64_FULL2_PARITY.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
print(json.dumps(report,indent=2))
raise SystemExit(0 if report["FULL_NETWORK_PARITY"]=="PASS" else 1)
