from pathlib import Path
import csv,json,hashlib,re

BASE=Path(r"D:\FPGA-AUTO\tasks")
F1=BASE/"FLY-01-FULL-CNS/FULL-1"
F3=BASE/"FLY-01-FULL-CNS/FULL-3"
ENC=BASE/"DEMO-1-SENSORY-ENCODER-0"
DEMO1=BASE/"DEMO-1-IMPLEMENTATION"
DEMO0=BASE/"DEMO-0"

def sha(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()

source=(DEMO1/"closed_loop_execute.py").read_text(encoding="utf-8")
encoder=(ENC/"sensory_encoder_v1_0.py").read_text(encoding="utf-8")
schema=json.loads((DEMO0/"schemas/DNFrame.schema.json").read_text(encoding="utf-8"))
manifest=json.loads((DEMO1/"DEMO-1_EXECUTION_MANIFEST_v1_0.json").read_text(encoding="utf-8"))
contract=json.loads((ENC/"DEMO-1_SENSORY_ENCODER_V1_0.json").read_text(encoding="utf-8"))

roster=list(csv.DictReader((ENC/"SENSORY_INPUT_POPULATION_311.csv").open(encoding="utf-8")))
inp=json.loads((F1/"INPUT_311_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
dn=json.loads((F1/"DN_32_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
frozen_dn=json.loads((BASE/"S4-S5-DN-ID-0/FROZEN_32_DN_IDENTITY_AND_SLOT_ORDER.json").read_text(encoding="utf-8"))

assert len(roster)==len(inp)==311
input_matches=[]
for r,m in zip(roster,sorted(inp,key=lambda x:int(x["input_slot"]))):
    ok=int(r["input_ordinal"])==int(m["input_slot"]) and int(r["root_id"])==int(m["body_id"])
    input_matches.append(ok)
assert all(input_matches)

assert len(dn)==32 and len(frozen_dn["slots"])==32
dn_matches=[]
for a,b in zip(sorted(dn,key=lambda x:int(x["slot_index"])),frozen_dn["slots"]):
    dn_matches.append(int(a["slot_index"])==int(b["slot_index"]) and
                      int(a["source_neuron_identity"])==int(b["source_neuron_identity"]))
assert all(dn_matches)

required_source_facts={
 "dn_frame_function_binary_membership":
   'slots=tuple(int(int(li) in firedset) for li in out_local)' in source,
 "dn_frame_id_k":'frame_id=k' in source,
 "dn_timestamp_k_dt":'timestamp_s=k*DT' in source,
 "dn_dt_is_DT":'dt_s=DT' in source,
 "dn_source_timestep_k":'source_timestep=k' in source,
 "feedback_targets_k_plus_1":'"target_neural_timestep_id":k+1' in source,
 "q_next_from_encoder":'q_next=[int(x) for x in encoded["drive_q_by_input_ordinal"]]' in source,
 "q_apply_from_pending":'q_apply=[int(x) for x in q_applied]' in source,
 "apply_pending_before_step":'apply_qvec(sim,q_apply)' in source,
 "candidate_step_after_drive":'fired=sim.step(noise_local)' in source,
}
assert all(required_source_facts.values())

audit={
 "task":"FULL-3 frozen SourceDrive / DNFrame interface audit",
 "source_files":{
   "closed_loop_execute.py":{"path":str(DEMO1/"closed_loop_execute.py"),"sha256":sha(DEMO1/"closed_loop_execute.py")},
   "encoder_code":{"path":str(ENC/"sensory_encoder_v1_0.py"),"sha256":sha(ENC/"sensory_encoder_v1_0.py")},
   "encoder_contract":{"path":str(ENC/"DEMO-1_SENSORY_ENCODER_V1_0.json"),"sha256":sha(ENC/"DEMO-1_SENSORY_ENCODER_V1_0.json")},
   "encoder_roster":{"path":str(ENC/"SENSORY_INPUT_POPULATION_311.csv"),"sha256":sha(ENC/"SENSORY_INPUT_POPULATION_311.csv")},
   "dn_schema":{"path":str(DEMO0/"schemas/DNFrame.schema.json"),"sha256":sha(DEMO0/"schemas/DNFrame.schema.json")},
   "demo1_manifest":{"path":str(DEMO1/"DEMO-1_EXECUTION_MANIFEST_v1_0.json"),"sha256":sha(DEMO1/"DEMO-1_EXECUTION_MANIFEST_v1_0.json")}
 },
 "candidate_b_source_drive":{
   "canonical_vector":"drive_q_by_input_ordinal[311]",
   "allowed_q_values":contract["output"]["allowed_q_values"],
   "q_nominal":contract["drive_intensity"]["nominal_q"],
   "q_semantic":contract["drive_intensity"]["semantic"],
   "activation_for_full_adapter":"q == 0 inactive; q != 0 active",
   "full_adapter_forbidden_interpretations":["MaleCNS membrane voltage","Poisson rate","synaptic contact count"],
   "causal_contract":contract["temporal"]["causal_contract"],
   "source_drive_initial":"all-zero 311 vector",
 },
 "candidate_b_dnframe":{
   "slot_count":32,
   "slot_semantics":"binary; slot=1 iff frozen Candidate-B output local index is a member of fired set at neural step k",
   "slot_type":"integer values generated as 0 or 1 by frozen DEMO-1 source code",
   "schema_note":"JSON schema only constrains integer>=0; binary semantics are established by frozen producer source, not inferred from schema",
   "frame_id":"k",
   "timestamp_s":"k * 0.02",
   "dt_s":0.02,
   "source_timestep":"k",
   "schema_version":"demo.dnframe.v1"
 },
 "timebase":{
   "candidate_b_dt_s":manifest["timebase"]["dt_s"],
   "feedback_to_source_delay_frames":1,
   "ordering":manifest["causal_contract"]
 },
 "binding":{
   "input_311_exact":sum(input_matches),
   "input_roster_body_id_field":"root_id",
   "input_full_map_body_id_field":"body_id",
   "warning":"encoder roster global_index is legacy brain.npz index and MUST NOT be used as Full runtime_index",
   "dn_32_exact":sum(dn_matches),
 },
 "source_code_fact_checks":required_source_facts,
 "PASS":all(required_source_facts.values()) and sum(input_matches)==311 and sum(dn_matches)==32
}
(F3/"DNFRAME_FROZEN_INTERFACE_AUDIT.json").write_text(json.dumps(audit,indent=2),encoding="utf-8")
print(json.dumps({"PASS":audit["PASS"],"input_311":sum(input_matches),"dn_32":sum(dn_matches),
                  "source_facts":required_source_facts},indent=2))
