from pathlib import Path
import importlib.util,json,math,statistics,sys,time,subprocess
import numpy as np
ROOT=Path(r"D:\FPGA-AUTO\tasks"); BASE=ROOT/"FLY-01-FULL-CNS"
F1=BASE/"FULL-1"; F3=BASE/"FULL-3"; F4G=BASE/"FULL-4G"
sys.path.insert(0,str(F4G)); sys.path.insert(0,str(F3))
import GPU_FP64_OPTIMIZED_LANE as O
from FULL_INPUT_ADAPTER_V1 import FullInputAdapterV1

def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m; spec.loader.exec_module(m); return m
SE=load_module("bench_encoder",ROOT/"DEMO-1-SENSORY-ENCODER-0/sensory_encoder_v1_0.py")
def fb(k,s):
    base={"schema_version":"0.1","frame_id":k,"timestamp_s":k*.02,"dt_s":.02,
      "source_body_frame_id":k,"source_environment_frame_id":k,"target_neural_timestep_id":k+1}
    if s=="NEUTRAL": return {**base,"objects":[]}
    pos={"LEFT":[10.,2.,0.],"RIGHT":[10.,-2.,0.],"CENTER":[10.,0.,0.]}[s]
    x,y,z=pos; d=math.sqrt(x*x+y*y+z*z); az=math.atan2(y,x); el=math.atan2(z,math.hypot(x,y))
    lr="LEFT" if az>1e-6 else ("RIGHT" if az<-1e-6 else "CENTER")
    ob={"object_id":"full3_fixture","geometry_status":"VALID","environment_visible":True,
      "relative_position_body":pos,"distance_m":d,"azimuth_rad":az,"elevation_rad":el,
      "angular_size_rad":2*math.asin(1/d),"range_rate_mps":0.0,"closing_speed_mps":0.0,
      "angular_expansion_rate_radps":0.0,"left_right_relation":lr,
      "approach_recession":"STATIONARY","in_front":True}
    return {**base,"objects":[ob]}
inp=json.loads((F1/"INPUT_311_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
inp=sorted(inp,key=lambda x:int(x["input_slot"])); idx=np.asarray([int(x["runtime_index"]) for x in inp],np.int32)
ia=FullInputAdapterV1(idx)

def pct(v,p): return float(np.percentile(np.asarray(v,float),p,method="linear"))

gpu=O.GPUFP64OptimizedLane(event_capacity=10000)
# Warm graph and active propagation path, excluded from benchmark.
gpu.run_frame(idx,(33,100,166),capture_events=False,use_graph=True,tick_base=0)
gpu.reset()
cold={"model_load_wall_s":gpu.model_load_wall_s}
results={}
all_compute=[]; all_total=[]
for scenario in ("NEUTRAL","LEFT","RIGHT","CENTER"):
    gpu.reset(); pq=np.zeros(311,np.int64); ps=None
    rows=[]
    for k in range(20):
        enc=SE.encode_feedback_frame(fb(k,scenario)); qn=np.asarray(enc["drive_q_by_input_ordinal"],np.int64)
        t0=time.perf_counter(); drive=ia.adapt(pq,k,ps,k); adapter_ms=(time.perf_counter()-t0)*1000
        active=np.asarray(drive.active_runtime_indices,np.int32)
        out=gpu.run_frame(active,(33,100,166) if len(active) else (),capture_events=False,use_graph=True,tick_base=k*200)
        total=adapter_ms+out["h2d_ms"]+out["compute_ms"]+out["d2h_ms"]
        rows.append({"frame":k,"compute_ms":out["compute_ms"],"adapter_ms":adapter_ms,
                     "h2d_ms":out["h2d_ms"],"d2h_ms":out["d2h_ms"],"backend_total_ms":total,
                     "dn32_spikes":int(out["dn_counts"].sum())})
        pq=qn; ps=k
    c=[x["compute_ms"] for x in rows]; tot=[x["backend_total_ms"] for x in rows]
    all_compute+=c; all_total+=tot
    results[scenario]={"frames":rows,
      "compute":{"mean":statistics.mean(c),"p50":pct(c,50),"p95":pct(c,95),"p99":pct(c,99),"max":max(c)},
      "adapter_mean_ms":statistics.mean(x["adapter_ms"] for x in rows),
      "h2d_mean_ms":statistics.mean(x["h2d_ms"] for x in rows),
      "d2h_mean_ms":statistics.mean(x["d2h_ms"] for x in rows),
      "total":{"mean":statistics.mean(tot),"p50":pct(tot,50),"p95":pct(tot,95),"p99":pct(tot,99),"max":max(tot)}}

mem=gpu.memory_profile()
try:
    smi=subprocess.check_output(["nvidia-smi","--query-gpu=utilization.gpu,memory.used,memory.total",
                                 "--format=csv,noheader,nounits"],text=True).strip()
except Exception as e: smi=repr(e)
worst_p99=max(results[s]["compute"]["p99"] for s in results)
report={"backend":gpu.backend_id,"precision":"float64","warmup_excluded":True,"cold":cold,
 "scenarios":results,"overall_compute":{"mean":statistics.mean(all_compute),"p50":pct(all_compute,50),
 "p95":pct(all_compute,95),"p99":pct(all_compute,99),"max":max(all_compute)},
 "overall_total":{"mean":statistics.mean(all_total),"p50":pct(all_total,50),
 "p95":pct(all_total,95),"p99":pct(all_total,99),"max":max(all_total)},
 "worst_scenario_compute_p99_ms":worst_p99,
 "20MS_NEURAL_GATE":"PASS" if worst_p99<20.0 else "FAIL",
 "15MS_HEADROOM_TARGET":"PASS" if worst_p99<=15.0 else "FAIL",
 "gpu_memory":mem,"nvidia_smi_post_benchmark":smi}
(F4G/"FP64_OPTIMIZED_BENCHMARK.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
print(json.dumps({k:report[k] for k in ("backend","precision","overall_compute","overall_total",
 "worst_scenario_compute_p99_ms","20MS_NEURAL_GATE","15MS_HEADROOM_TARGET","gpu_memory","nvidia_smi_post_benchmark")},indent=2))
print(json.dumps({s:results[s]["compute"] for s in results},indent=2))
