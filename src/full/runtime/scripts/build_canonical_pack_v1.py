from pathlib import Path
import json, hashlib, csv
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.ipc as ipc

ROOT=Path(r"D:\FPGA-AUTO\tasks\FLY-01-FULL-CNS")
SRC=ROOT/"source"
OUT=ROOT/"FULL-1"
PACK=OUT/"canonical_pack_v1"
PACK.mkdir(parents=True,exist_ok=True)

ANN=SRC/"body-annotations-male-cns-v1.0-minconf-0.5.feather"
NT=SRC/"body-neurotransmitters-male-cns-v1.0.feather"
CONN=SRC/"connectome-weights-male-cns-v1.0-minconf-0.5.feather"
BRAIN=Path(r"D:\FPGA-AUTO\tasks\S5-FPGA-0\golden\brain.npz")
CAND=Path(r"D:\FPGA-AUTO\tasks\S5-FPGA-0\golden\s4_candidate_graphs.npz")
DNJSON=Path(r"D:\FPGA-AUTO\tasks\S4-S5-DN-ID-0\FROZEN_32_DN_IDENTITY_AND_SLOT_ORDER.json")

KNOWN={"acetylcholine":1,"gaba":-1,"glutamate":-1}

def sha256_file(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()

ann=pd.read_feather(ANN)
sel=ann[ann["superclass"].notna()].drop_duplicates("bodyId").sort_values("bodyId").reset_index(drop=True)
body_ids=sel.bodyId.to_numpy(np.int64)
N=len(body_ids)
assert N==166700 and np.unique(body_ids).size==N and np.all(np.diff(body_ids)>0)
np.save(PACK/"body_ids.npy",body_ids,allow_pickle=False)
np.save(PACK/"index_to_body_id.npy",body_ids,allow_pickle=False)

with open(OUT/"BODY_ID_INDEX_MAP.csv","w",newline="",encoding="utf-8") as f:
    w=csv.writer(f); w.writerow(["runtime_index","body_id"])
    w.writerows((i,int(b)) for i,b in enumerate(body_ids))
np.savez_compressed(OUT/"body_id_to_index.npz",body_id=body_ids,runtime_index=np.arange(N,dtype=np.int32))
nt=pd.read_feather(NT,columns=["body","consensus_nt"])
nt_map=dict(zip(nt.body.astype(int),nt.consensus_nt))
sign=np.zeros(N,np.int8)
nt_label=np.empty(N,dtype=object)
for i,b in enumerate(body_ids):
    v=nt_map.get(int(b),None)
    nt_label[i]=v
    sign[i]=KNOWN.get(str(v).strip().casefold(),0) if isinstance(v,str) else 0
np.save(PACK/"presynaptic_sign.npy",sign,allow_pickle=False)

reader=ipc.open_file(pa.memory_map(str(CONN),"r"))
pre_parts=[]; post_parts=[]; signed_parts=[]; unsigned_parts=[]
raw_rows=0; structural_rows=0; structural_weight=0
drop_endpoint=drop_unsigned=drop_nonpos=0
for bi in range(reader.num_record_batches):
    batch=reader.get_batch(bi)
    pre_id=batch.column(reader.schema.get_field_index("body_pre")).to_numpy(zero_copy_only=False).astype(np.int64,copy=False)
    post_id=batch.column(reader.schema.get_field_index("body_post")).to_numpy(zero_copy_only=False).astype(np.int64,copy=False)
    wt=batch.column(reader.schema.get_field_index("weight")).to_numpy(zero_copy_only=False).astype(np.int64,copy=False)
    raw_rows += wt.size
    pi=np.searchsorted(body_ids,pre_id); qi=np.searchsorted(body_ids,post_id)
    pis=np.minimum(pi,N-1); qis=np.minimum(qi,N-1)
    endpoints=(pi<N)&(qi<N)&(body_ids[pis]==pre_id)&(body_ids[qis]==post_id)
    drop_endpoint += int((~endpoints).sum())
    structural_rows += int(endpoints.sum())
    structural_weight += int(wt[endpoints].sum())
    s=np.where(endpoints,sign[pis],0).astype(np.int64)
    signed=endpoints&(s!=0)
    drop_unsigned += int((endpoints&(s==0)).sum())
    keep=signed&(wt>0)
    drop_nonpos += int((signed&(wt<=0)).sum())
    if keep.any():
        pre_parts.append(pis[keep].astype(np.int32))
        post_parts.append(qis[keep].astype(np.int32))
        unsigned_parts.append(wt[keep].astype(np.int32))
        signed_parts.append((s[keep]*wt[keep]).astype(np.int32))

pre=np.concatenate(pre_parts); post=np.concatenate(post_parts)
unsigned=np.concatenate(unsigned_parts); signed_counts=np.concatenate(signed_parts)
del pre_parts,post_parts,unsigned_parts,signed_parts
assert structural_rows==25582938 and structural_weight==124177617
assert len(pre)==24469412 and int(unsigned.astype(np.int64).sum())==120260398
assert int(signed_counts.astype(np.int64).sum())==26721930
assert np.all(unsigned>0) and np.all(signed_counts!=0)
# deterministic source-major order and generic duplicate aggregation
order=np.lexsort((post,pre))
sp=pre[order].astype(np.int64); sq=post[order].astype(np.int64)
su=unsigned[order].astype(np.int64); ss=signed_counts[order].astype(np.int64)
key=sp*np.int64(N)+sq
first=np.empty(len(key),bool); first[0]=True; first[1:]=key[1:]!=key[:-1]
starts=np.flatnonzero(first)
if len(starts)!=len(key):
    sp2=sp[starts]; sq2=sq[starts]
    su2=np.add.reduceat(su,starts); ss2=np.add.reduceat(ss,starts)
else:
    sp2,sq2,su2,ss2=sp,sq,su,ss
assert len(sp2)==24469412
row_counts=np.bincount(sp2,minlength=N)
row_ptr=np.empty(N+1,dtype=np.int64); row_ptr[0]=0; np.cumsum(row_counts,out=row_ptr[1:])
assert row_ptr[-1]==24469412 and row_ptr[-1] < 2**31
row_ptr=row_ptr.astype(np.int32); dst=sq2.astype(np.int32)
unsigned=su2.astype(np.int32); signed_counts=ss2.astype(np.int32)
assert int(np.abs(signed_counts.astype(np.int64)).sum())==120260398
assert int(signed_counts.astype(np.int64).sum())==26721930

np.save(PACK/"row_ptr.npy",row_ptr,allow_pickle=False)
np.save(PACK/"dst_index.npy",dst,allow_pickle=False)
np.save(PACK/"signed_contact_count.npy",signed_counts,allow_pickle=False)
np.save(PACK/"contact_count.npy",unsigned,allow_pickle=False)

# frozen input maps
brain=np.load(BRAIN,allow_pickle=True); cand=np.load(CAND,allow_pickle=True)
input_local_idx=np.asarray(cand["B_visual_relay128_top32_inputs"],dtype=np.int64)
input_body=np.asarray(brain["ids"],dtype=np.int64)[input_local_idx]
runtime_idx=np.searchsorted(body_ids,input_body)
assert len(input_body)==311 and np.all(runtime_idx<N) and np.array_equal(body_ids[runtime_idx],input_body)
input_map=[]
for slot,(li,b,ri) in enumerate(zip(input_local_idx,input_body,runtime_idx)):
    input_map.append({"input_slot":slot,"legacy_brain_index":int(li),"body_id":int(b),"runtime_index":int(ri),
                      "cell_type":str(np.asarray(brain["cell_type"])[li]),"superclass":str(np.asarray(brain["superclass"])[li])})
(OUT/"INPUT_311_INDEX_MAP.json").write_text(json.dumps({"count":311,"exact_match":"311/311","entries":input_map},indent=2),encoding="utf-8")

dndata=json.loads(DNJSON.read_text(encoding="utf-8"))
dn_map=[]
for s in dndata["slots"]:
    b=int(s["source_neuron_identity"]); ri=int(np.searchsorted(body_ids,b))
    assert ri<N and int(body_ids[ri])==b
    dn_map.append({**s,"runtime_index":ri})
(OUT/"DN_32_INDEX_MAP.json").write_text(json.dumps({"count":32,"exact_match":"32/32","entries":dn_map},indent=2),encoding="utf-8")
structural={
 "source_release":"MaleCNS v1.0",
 "source_connectivity_file":CONN.name,
 "source_connectivity_sha256":sha256_file(CONN),
 "raw_official_rows":int(raw_rows),
 "canonical_node_rule":"annotation rows where superclass is non-null; ascending bodyId",
 "canonical_neurons":N,
 "structural_projection_rule":"both endpoints are canonical nodes; no NT/sign filter",
 "structural_edge_count":int(structural_rows),
 "structural_weight_sum":int(structural_weight),
 "runtime_subset_rule":"both endpoints canonical AND weight>0 AND presynaptic consensus_nt in {acetylcholine,gaba,glutamate}",
 "runtime_edges":int(len(dst)),
 "runtime_contact_weight_sum":int(unsigned.astype(np.int64).sum()),
 "runtime_signed_contact_sum":int(signed_counts.astype(np.int64).sum()),
 "unknown_nt_policy":"node kept; outgoing fast-sign edges excluded",
 "engineering_policy":True
}
(PACK/"STRUCTURAL_PROJECTION_MANIFEST.json").write_text(json.dumps(structural,indent=2),encoding="utf-8")

files={}
for p in sorted(PACK.iterdir()):
    if p.is_file():
        files[p.name]={"bytes":p.stat().st_size,"sha256":sha256_file(p)}
for p in [OUT/"BODY_ID_INDEX_MAP.csv",OUT/"body_id_to_index.npz",OUT/"INPUT_311_INDEX_MAP.json",OUT/"DN_32_INDEX_MAP.json"]:
    files["../"+p.name]={"bytes":p.stat().st_size,"sha256":sha256_file(p)}

manifest={
 "PACK_VERSION":"FLY01_FULL_CANONICAL_PACK_V1",
 "SOURCE_RELEASE":"MaleCNS v1.0",
 "NODE_RULE":"superclass != null; ascending bodyId",
 "EDGE_RULE":"pre/post canonical; weight>0; presynaptic consensus_nt in acetylcholine/gaba/glutamate",
 "SIGN_RULE":{"acetylcholine":1,"gaba":-1,"glutamate":-1},
 "UNKNOWN_NT_POLICY":"keep node; exclude outgoing fast-sign edges",
 "DYNAMICS_REFERENCE":"philshiu/Drosophila_brain_model@91bdd1e7dcf193f3e7ca5a8933497fcef63b7960",
 "PARAMETER_SET":"Shiu-derived engineering LIF; MaleCNS refit NO",
 "N":N,"E":int(len(dst)),
 "CONTACT_WEIGHT_SUM":int(unsigned.astype(np.int64).sum()),
 "SIGNED_CONTACT_SUM":int(signed_counts.astype(np.int64).sum()),
 "SELF_EDGES":int(np.sum(np.repeat(np.arange(N,dtype=np.int32),np.diff(row_ptr.astype(np.int64)))==dst)),
 "ROW_PTR_DTYPE":str(row_ptr.dtype),"DST_DTYPE":str(dst.dtype),"SIGNED_COUNT_DTYPE":str(signed_counts.dtype),
 "FILES":files
}
mp=OUT/"CANONICAL_PACK_MANIFEST.json"
mp.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
print(json.dumps({"N":N,"E":len(dst),"contact_sum":manifest["CONTACT_WEIGHT_SUM"],"signed_sum":manifest["SIGNED_CONTACT_SUM"],
 "input_map":len(input_map),"dn_map":len(dn_map),"manifest_sha256":sha256_file(mp),"pack_files":files},indent=2))
