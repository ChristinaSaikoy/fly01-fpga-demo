from __future__ import annotations
import csv, hashlib, importlib.util, json, math, sys
from pathlib import Path
import numpy as np

ROOT=Path(r"D:\FPGA-AUTO")
TASK=ROOT/"tasks"/"DEMO-1-IMPLEMENTATION"
MANIFEST_PATH=TASK/"DEMO-1_EXECUTION_MANIFEST_v1_0.json"
MANIFEST_RECEIPT=TASK/"DEMO-1_EXECUTION_MANIFEST_v1_0_SHA256.txt"
ENC_DIR=ROOT/"tasks"/"DEMO-1-SENSORY-ENCODER-0"
GRAPH=ROOT/"tasks"/"S5-FPGA-0"/"golden"/"s4_candidate_graphs.npz"
BRAIN=ROOT/"tasks"/"S5-FPGA-0"/"golden"/"brain.npz"
MODEL=ROOT/"tasks"/"S5-FPGA-0"/"golden"/"s4_scope1_integer_model.py"
DEMO0=ROOT/"tasks"/"DEMO-0"

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def jload(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def canonical_hash(obj): return hashlib.sha256(json.dumps(obj,separators=(",",":"),sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod

# Verify execution manifest before any run.
expected=MANIFEST_RECEIPT.read_text(encoding="utf-8").split()[0]
if sha(MANIFEST_PATH)!=expected: raise RuntimeError("execution manifest hash mismatch")
MF=jload(MANIFEST_PATH)
for item in MF["frozen_identities"].values():
    if sha(item["path"])!=item["sha256"]: raise RuntimeError("frozen identity mismatch "+item["path"])

IM=load_module("demo1_integer_model",MODEL)
SH=load_module("demo0_scientific_host",DEMO0/"scientific_host.py")
SE=load_module("demo1_sensory_encoder",ENC_DIR/"sensory_encoder_v1_0.py")
BG=load_module("demo1_body_geometry_ref",ROOT/"tasks"/"BODY-0A2D"/"validate_body_0a2d.py")

z=np.load(GRAPH,allow_pickle=False)
brain=np.load(BRAIN,allow_pickle=False)
PFX="B_visual_relay128_top32_"
nodes=np.asarray(z[PFX+"nodes"],dtype=np.int64)
inputs=np.asarray(z[PFX+"inputs"],dtype=np.int64)
outputs=np.asarray(z[PFX+"outputs"],dtype=np.int64)
preloc=np.asarray(z[PFX+"pre_local"],dtype=np.int32)
postloc=np.asarray(z[PFX+"post_local"],dtype=np.int32)
weights=np.asarray(z[PFX+"weights"],dtype=np.float64)
g2l={int(g):i for i,g in enumerate(nodes.tolist())}
out_local=np.asarray([g2l[int(g)] for g in outputs],dtype=np.int32)
input_local=np.asarray([g2l[int(g)] for g in inputs],dtype=np.int32)
assert (len(nodes),len(inputs),len(outputs),len(preloc))==(471,311,32,44236)
assert [int(x["candidate_local_index"]) for x in SE.ROSTER]==input_local.tolist()

DT=float(MF["timebase"]["dt_s"])
TICKS=int(MF["timebase"]["tick_count"])
SEED=int(MF["external_noise"]["common_seed"])
NOISE_P=float(MF["external_noise"]["probability_per_global_neuron_per_step"])

def body_dict(s):
    return {"frame_id":int(s.frame_id),"simulation_time":float(s.simulation_time),
      "position_xyz":[float(x) for x in s.position_xyz],
      "orientation_wxyz":[float(x) for x in s.orientation],
      "linear_velocity_xyz":[float(x) for x in s.linear_velocity_xyz],
      "angular_velocity_xyz":[float(x) for x in s.angular_velocity_xyz],
      "valid":bool(s.valid),"body_mode":s.body_mode,"schema_version":s.schema_version}

def drive_dict(d):
    return {"frame_id":int(d.frame_id),"timestamp":float(d.timestamp),"dt":float(d.dt),
      "v_forward_ref":float(d.v_forward_ref),"v_lateral_ref":float(d.v_lateral_ref),
      "v_vertical_ref":float(d.v_vertical_ref),"roll_rate_ref":float(d.roll_rate_ref),
      "pitch_rate_ref":float(d.pitch_rate_ref),"yaw_rate_ref":float(d.yaw_rate_ref),
      "schema_version":d.schema_version}

def world_frame(k,target):
    return {"schema_version":"0.1","frame_id":k,"timestamp_s":k*DT,"dt_s":DT,
      "objects":[{"object_id":"threat_0","position_xyz_world_m":[float(x) for x in target],
                  "linear_velocity_xyz_world_mps":[0.0,0.0,0.0],"radius_m":1.0,"visibility":True}]}

def feedback_frame(k,body,world):
    objs=[]
    for o in world["objects"]:
        bd={"pos":list(body.position_xyz),"q":list(body.orientation),"vel":list(body.linear_velocity_xyz)}
        ob={"pos":o["position_xyz_world_m"],"vel":o["linear_velocity_xyz_world_mps"],"radius":o["radius_m"]}
        g=BG.geometry(bd,ob)
        if not g["valid"]:
            objs.append({"object_id":o["object_id"],"geometry_status":"INVALID_OVERLAP",
              "environment_visible":bool(o["visibility"])})
        else:
            rw=[o["position_xyz_world_m"][i]-body.position_xyz[i] for i in range(3)]
            rb=BG.world_to_body(list(body.orientation),rw)
            objs.append({
              "object_id":o["object_id"],"geometry_status":"VALID",
              "environment_visible":bool(o["visibility"]),
              "relative_position_body":[float(x) for x in rb],
              "distance_m":float(g["distance_m"]),"azimuth_rad":float(g["azimuth_rad"]),
              "elevation_rad":float(g["elevation_rad"]),"angular_size_rad":float(g["angular_size_rad"]),
              "range_rate_mps":float(g["range_rate_mps"]),"closing_speed_mps":float(g["closing_speed_mps"]),
              "angular_expansion_rate_radps":float(g["angular_expansion_rate_radps"]),
              "left_right_relation":g["left_right_relation"],"approach_recession":g["approach_recession"],
              "in_front":bool(g["in_front"])
            })
    return {"schema_version":"0.1","frame_id":k,"timestamp_s":k*DT,"dt_s":DT,
      "source_body_frame_id":int(body.frame_id),"source_environment_frame_id":int(world["frame_id"]),
      "target_neural_timestep_id":k+1,"objects":objs}

def apply_qvec(sim,qvec):
    # Exact frozen source-state increment semantics. qvec is in Candidate-B inputs order.
    for ord_,q in enumerate(qvec):
        if int(q)==0: continue
        li=int(input_local[ord_])
        v,sat=IM.sat_scalar(int(sim.state[li])+int(q),sim.fmt.s_bits)
        sim.state[li]=v
        sim.state_saturation_count += int(sat)

def dn_frame(k,fired,scenario):
    firedset=set(map(int,fired))
    slots=tuple(int(int(li) in firedset) for li in out_local)
    return SH.DNFrame(frame_id=k,timestamp_s=k*DT,dt_s=DT,slots=slots,
       source_id="CandidateBIntegerClosedLoop",replay_id="DEMO1_"+scenario,
       stimulus_state="CLOSED_LOOP",source_timestep=k)

def run_one(name,target):
    sim=IM.CandidateBInteger(preloc,postloc,weights,IM.FORMATS["RECOMMENDED"])
    rng=np.random.default_rng(SEED)
    artifacts=SH.FrozenArtifacts()
    pre=SH.FrozenPreprocessorV1_0(artifacts)
    mapper=SH.FinalDNMotorMapperV1_0(artifacts)
    runtime=artifacts.bodyrt.BodyRuntime(artifacts.body_config)
    body=artifacts.bodyrt.BodyState.zero()
    q_applied=[0]*311
    outdir=TASK/"runs"/name;outdir.mkdir(parents=True,exist_ok=True)
    trace_path=outdir/"causal_trace.jsonl"
    summary=[]
    noise_hashes=[]
    with trace_path.open("w",encoding="utf-8",newline="\n") as f:
      for k in range(TICKS):
        b_k=body_dict(body)
        world=world_frame(k,target)
        fb=feedback_frame(k,body,world)
        encoded=SE.encode_feedback_frame(fb)
        q_next=[int(x) for x in encoded["drive_q_by_input_ordinal"]]
        q_apply=[int(x) for x in q_applied]
        apply_qvec(sim,q_apply)
        full_noise=rng.random(166700)<NOISE_P
        noise_local=np.flatnonzero(full_noise[nodes]).astype(np.int32)
        noise_bytes=np.packbits(np.asarray(full_noise[nodes],dtype=np.uint8),bitorder="little").tobytes()
        nh=hashlib.sha256(noise_bytes).hexdigest();noise_hashes.append(nh)
        fired=sim.step(noise_local)
        dn=dn_frame(k,fired,name)
        pp=pre.step(dn)
        drive,vals=mapper.map(dn,pp,k)
        body_next,_,_=runtime.step(drive,body)
        rec={
          "tick":k,"model_time_s":k*DT,
          "body_state_k":b_k,"world_state_k":world,"feedback_frame_k":fb,
          "source_drive_k":{"target_neural_timestep_id":k,"q_vector_sha256":canonical_hash(q_apply),
                            "active_count":sum(q!=0 for q in q_apply),
                            "active_ordinals":[i for i,q in enumerate(q_apply) if q]},
          "source_drive_k_plus_1":{"target_neural_timestep_id":k+1,"q_vector_sha256":canonical_hash(q_next),
                            "active_group":encoded["active_group"],"active_count":sum(q!=0 for q in q_next),
                            "active_ordinals":[i for i,q in enumerate(q_next) if q]},
          "external_noise":{"local_event_count":int(len(noise_local)),"mask471_sha256":nh},
          "dn_frame_k":{"slots":list(dn.slots),"slots_sha256":canonical_hash(list(dn.slots)),
                        "fired_local_count":int(len(fired))},
          "preprocessor":{"a12":float(pp["a12"]),"a22":float(pp["a22"]),"a23":float(pp["a23"]),
                          "y12":float(pp["y12"]),"y22":float(pp["y22"]),"y23":float(pp["y23"])},
          "mapping":{"h_p03":float(vals["h_p03"]),"p03_contribution":float(vals["p03_contribution"]),
                     "p06R_contribution":float(vals["p06R_contribution"]),"yaw_pre":float(vals["yaw_pre"])},
          "motor_drive_k":drive_dict(drive),
          "body_state_k_plus_1":body_dict(body_next)
        }
        f.write(json.dumps(rec,separators=(",",":"),ensure_ascii=False)+"\n")
        summary.append(rec)
        q_applied=q_next
        body=body_next
    return {"scenario":name,"target":target,"trace_path":str(trace_path),"trace_sha256":sha(trace_path),
      "tick_count":TICKS,"noise_stream_sha256":canonical_hash(noise_hashes),
      "final_neural_state_sha256":hashlib.sha256(np.asarray(sim.state,dtype="<i8").tobytes()).hexdigest(),
      "acc_saturation_count":int(sim.acc_saturation_count),"state_saturation_count":int(sim.state_saturation_count)}

def main():
    # No scenario outcome is interpreted between the two calls.
    generated=[]
    generated.append(run_one("LEFT",MF["scenarios"]["LEFT"]["target_position_world_m"]))
    generated.append(run_one("RIGHT",MF["scenarios"]["RIGHT"]["target_position_world_m"]))
    ev={"task_id":"DEMO-1-IMPLEMENTATION","execution_manifest_sha256":expected,
        "population_generation":"COMPLETE_BEFORE_ADJUDICATION","runs":generated}
    p=TASK/"GENERATED_CLOSED_LOOP_EVIDENCE_MANIFEST.json"
    p.write_text(json.dumps(ev,indent=2)+"\n",encoding="utf-8")
    (TASK/"GENERATED_CLOSED_LOOP_EVIDENCE_MANIFEST_SHA256.txt").write_text(sha(p)+"  "+p.name+"\n",encoding="utf-8")
    print(json.dumps({"GENERATION":"COMPLETE","evidence_manifest":str(p),"evidence_manifest_sha256":sha(p),
      "runs":[{"scenario":x["scenario"],"trace_sha256":x["trace_sha256"],"ticks":x["tick_count"]} for x in generated]},indent=2))
if __name__=="__main__":main()
