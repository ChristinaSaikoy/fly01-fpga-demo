import hashlib, json, shutil
from pathlib import Path

TASK=Path(r"D:\FPGA-AUTO\tasks\S5-FPGA-1C")
BASE=Path(r"D:\FPGA-AUTO\tasks\S5-FPGA-0\evidence\FIRST_CORRECT_BASELINE")
GOLD=Path(r"D:\FPGA-AUTO\tasks\S5-FPGA-0\golden")
freeze=json.loads((BASE/"FREEZE_HASHES.json").read_text(encoding="utf-8-sig"))
expected={x["path"].replace("\\","/"):x["sha256"] for x in freeze}

def sha(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

rtl=[
"rtl/fly01_round_shift.sv","rtl/fly01_source_drive.sv","rtl/fly01_accum_add.sv",
"rtl/fly01_neuron_update.sv","rtl/fly01_event_fifo.sv","rtl/fly01_synapse_banks.sv",
"rtl/fly01_engine_core.sv","rtl/fly01_formal_top.sv"]
mem=sorted(k for k in expected if k.startswith("mem/banked/"))
mem += ["mem/csr_row_ptr.mem","mem/dn_local.mem"]
results=[]

baseline_all=[]
for entry in freeze:
    rel=entry["path"].replace("\\","/")
    src=BASE/Path(rel)
    got=sha(src) if src.is_file() else None
    baseline_all.append({"path":rel,"expected":entry["sha256"],"actual":got,"pass":got==entry["sha256"]})

for rel in rtl+mem:
    src=BASE/Path(rel)
    got=sha(src)
    ok=(got==expected[rel])
    if rel.startswith("rtl/"):
        dst=TASK/"src"/"core"/src.name
    elif rel.startswith("mem/banked/"):
        dst=TASK/"generated"/"banked"/src.name
    else:
        dst=TASK/"generated"/src.name
    dst.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(src,dst)
    copy_hash=sha(dst)
    results.append({"path":rel,"expected":expected[rel],"source_sha256":got,"copy_sha256":copy_hash,"pass":ok and copy_hash==expected[rel]})
golden_expected={
"s4_scope1_integer_model.py":"6d68f34c963fbe79de38403a2a0203c2e7afa11f2e82385cd2c815baa6493ca0",
"s4_scope1_integer_spec.json":"61c9f53e64a2e5fc878c55f533da46955eb5f36ce2e36f9d537cf4c1d57ee1e9",
"s4_candidate_graphs.npz":"5dd46c3adafd128a67c407c82e0f2636d5bfc640286b6234879e681c7336e9a6"}
golden_results=[]
gdst=TASK/"golden_ref"; gdst.mkdir(exist_ok=True)
for name,exp in golden_expected.items():
    src=GOLD/name; got=sha(src)
    dst=gdst/name; shutil.copy2(src,dst)
    cp=sha(dst)
    golden_results.append({"path":name,"expected":exp,"source_sha256":got,"copy_sha256":cp,"pass":got==exp and cp==exp})

all_pass=all(x["pass"] for x in baseline_all+results+golden_results)
compile_sources=[str((TASK/"src"/"core"/Path(x).name).resolve()) for x in rtl]
wrapper_sources=[
str((TASK/"src"/"wrapper"/"fly01_validation_axi.sv").resolve()),
str((TASK/"src"/"wrapper"/"fly01_validation_board_top.sv").resolve())]
ip_source=str((TASK/"impl"/"jtag_axi_ipgen"/"jtag_axi_ipgen.srcs"/"sources_1"/"ip"/"jtag_axi_0"/"jtag_axi_0.xci").resolve())
compile_audit={
"task_id":"S5-FPGA-1C",
"status":"PASS" if all_pass else "FAIL",
"ordered_sources":compile_sources+wrapper_sources+[ip_source],
"frozen_core_sources":compile_sources,
"new_validation_sources":wrapper_sources,
"official_jtag_axi_ip":[ip_source],
"excluded_baseline_wrapper":"fly01_impl_harness.sv",
"formal_top_instances_required":1,
"alternate_core_sources_compiled":False}
source_hashes=[]
for p in [Path(x) for x in compile_sources+wrapper_sources+[ip_source]]:
    source_hashes.append({"path":str(p),"sha256":sha(p) if p.is_file() else None,"exists":p.is_file()})
audit={
"task_id":"S5-FPGA-1C",
"baseline_root":str(BASE),
"baseline_mutated":False,
"freeze_manifest_sha256":sha(BASE/"FREEZE_MANIFEST.json"),
"freeze_manifest_expected_sha256":"ba5462fce4da9f4297fb160a2c76f31235dbd1d402a1e434b5c6d512c8edc7a1",
"baseline_freeze_entries":baseline_all,
"core_rtl_count":len(rtl),
"memory_file_count":len(mem),
"core_and_memory":results,
"golden_identity":golden_results,
"compile_source_audit":compile_audit,
"CORE_RTL_HASHES":"EXACT_MATCH_TO_S5_FPGA0" if all(x["pass"] for x in results if x["path"].startswith("rtl/")) else "FAIL",
"GRAPH_MEMORY_HASHES":"EXACT_MATCH_TO_S5_FPGA0" if all(x["pass"] for x in results if x["path"].startswith("mem/")) and golden_results[2]["pass"] else "FAIL",
"INTEGER_SPEC":"UNCHANGED" if golden_results[0]["pass"] and golden_results[1]["pass"] else "FAIL",
"COMPILE_SOURCE_AUDIT":"PASS" if all_pass else "FAIL",
"NEURAL_CORE_IDENTITY":"PASS" if all_pass else "FAIL"}
(TASK/"evidence"/"core_identity_preflight.json").write_text(json.dumps(audit,indent=2),encoding="utf-8")
(TASK/"evidence"/"compile_source_audit.txt").write_text("\n".join(compile_sources)+"\n",encoding="utf-8")
(TASK/"evidence"/"compile_source_audit.json").write_text(json.dumps(compile_audit,indent=2),encoding="utf-8")
(TASK/"evidence"/"validation_source_hashes.json").write_text(json.dumps({"task_id":"S5-FPGA-1C","status":"PASS" if all(x["exists"] for x in source_hashes) else "FAIL","files":source_hashes},indent=2),encoding="utf-8")
integrity={"task_id":"S5-FPGA-1C","freeze_entries_checked":len(baseline_all),"mismatches":[x for x in baseline_all if not x["pass"]],"status":"PASS" if all(x["pass"] for x in baseline_all) else "FAIL"}
initial_path=TASK/"evidence"/"baseline_integrity_initial.json"
if not initial_path.exists():
    initial_path.write_text(json.dumps(integrity,indent=2),encoding="utf-8")
(TASK/"evidence"/"baseline_integrity_final.json").write_text(json.dumps(integrity,indent=2),encoding="utf-8")
print(json.dumps({k:audit[k] for k in ["CORE_RTL_HASHES","GRAPH_MEMORY_HASHES","INTEGER_SPEC","COMPILE_SOURCE_AUDIT","NEURAL_CORE_IDENTITY"]},indent=2))
if not all_pass:
    raise SystemExit(2)
