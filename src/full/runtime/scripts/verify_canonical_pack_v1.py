from pathlib import Path
import json, hashlib
import numpy as np
import pyarrow.feather as feather
import pyarrow.ipc as ipc
import pyarrow as pa

ROOT=Path(r"D:\FPGA-AUTO\tasks\FLY-01-FULL-CNS")
P=ROOT/"FULL-1/canonical_pack_v1"
ANN=ROOT/"source/body-annotations-male-cns-v1.0-minconf-0.5.feather"
NT=ROOT/"source/body-neurotransmitters-male-cns-v1.0.feather"
CONN=ROOT/"source/connectome-weights-male-cns-v1.0-minconf-0.5.feather"
KNOWN={"acetylcholine":1,"gaba":-1,"glutamate":-1}
rep={"verifier":"independent dict-based raw-source reconstruction"}

ids=np.load(P/"body_ids.npy",allow_pickle=False)
row_ptr=np.load(P/"row_ptr.npy",allow_pickle=False)
dst=np.load(P/"dst_index.npy",allow_pickle=False)
cnt=np.load(P/"signed_contact_count.npy",allow_pickle=False)
ucnt=np.load(P/"contact_count.npy",allow_pickle=False)
sign_pack=np.load(P/"presynaptic_sign.npy",allow_pickle=False)
N=len(ids); E=len(dst)
rep["N"]=N; rep["E"]=E

ann=feather.read_table(ANN,columns=["bodyId","superclass"])
body=ann["bodyId"].to_numpy(zero_copy_only=False).astype(np.int64).tolist()
sup=ann["superclass"].to_pylist()
expected_ids=np.array(sorted(b for b,s in zip(body,sup) if s is not None),dtype=np.int64)
rep["body_ids_exact"]=bool(np.array_equal(ids,expected_ids))
rep["body_ids_unique"]=bool(np.unique(ids).size==N)
idx={int(b):i for i,b in enumerate(expected_ids)}
rep["index_range_pass"]=bool(N==166700 and int(row_ptr[0])==0 and int(row_ptr[-1])==E)
rep["csr_monotonic"]=bool(np.all(np.diff(row_ptr.astype(np.int64))>=0))
rep["dst_bounds"]=bool(np.all((dst>=0)&(dst<N)))
rep["zero_edge_none"]=bool(np.all(cnt!=0) and np.all(ucnt>0))

nt=feather.read_table(NT,columns=["body","consensus_nt"])
nt_map=dict(zip(nt["body"].to_numpy(zero_copy_only=False).astype(np.int64).tolist(),nt["consensus_nt"].to_pylist()))
expected_sign=np.zeros(N,dtype=np.int8)
for i,b in enumerate(expected_ids):
    v=nt_map.get(int(b))
    expected_sign[i]=KNOWN.get(v.strip().casefold(),0) if isinstance(v,str) else 0
rep["sign_vector_exact"]=bool(np.array_equal(sign_pack,expected_sign))
reader=ipc.open_file(pa.memory_map(str(CONN),"r"))
preL=[]; postL=[]; signedL=[]; unsignedL=[]
raw=0; endpoint=0; unsigned_drop=0; nonpos_drop=0
get=idx.get
for bi in range(reader.num_record_batches):
    b=reader.get_batch(bi)
    bp=b.column(reader.schema.get_field_index("body_pre")).to_pylist()
    bq=b.column(reader.schema.get_field_index("body_post")).to_pylist()
    w=b.column(reader.schema.get_field_index("weight")).to_numpy(zero_copy_only=False).astype(np.int64)
    raw += len(bp)
    pi=np.fromiter((get(int(x),-1) for x in bp),dtype=np.int64,count=len(bp))
    qi=np.fromiter((get(int(x),-1) for x in bq),dtype=np.int64,count=len(bq))
    end=(pi>=0)&(qi>=0); endpoint += int(end.sum())
    sg=np.zeros(len(pi),dtype=np.int8); sg[end]=expected_sign[pi[end]]
    unsigned_drop += int((end&(sg==0)).sum())
    nonpos_drop += int((end&(sg!=0)&(w<=0)).sum())
    keep=end&(sg!=0)&(w>0)
    if keep.any():
        preL.append(pi[keep].astype(np.int32)); postL.append(qi[keep].astype(np.int32))
        unsignedL.append(w[keep].astype(np.int32)); signedL.append((sg[keep].astype(np.int64)*w[keep]).astype(np.int32))

pre=np.concatenate(preL); post=np.concatenate(postL)
su=np.concatenate(unsignedL); ss=np.concatenate(signedL)
del preL,postL,unsignedL,signedL
rep.update({"raw_rows":raw,"structural_projection_edges":endpoint,
            "dropped_unsigned_presynaptic":unsigned_drop,"dropped_nonpositive":nonpos_drop,
            "raw_runtime_rows":int(len(pre))})
# Independent canonicalization: stable sort integer pair key then Python/NumPy reduce.
keys=pre.astype(np.int64)*np.int64(N)+post.astype(np.int64)
o=np.argsort(keys,kind="stable"); k=keys[o]; ssu=su[o].astype(np.int64); sss=ss[o].astype(np.int64)
first=np.empty(len(k),bool); first[0]=True; first[1:]=k[1:]!=k[:-1]
st=np.flatnonzero(first)
uk=k[st]; eu=np.add.reduceat(ssu,st); es=np.add.reduceat(sss,st)
exp_pre=uk//N; exp_dst=(uk%N).astype(np.int32)
exp_rows=np.bincount(exp_pre,minlength=N)
exp_rp=np.zeros(N+1,dtype=np.int64); np.cumsum(exp_rows,out=exp_rp[1:])

rep["duplicates_aggregated"]=int(len(k)-len(uk))
rep["canonical_edges"]=int(len(uk))
rep["contact_sum"]=int(eu.sum())
rep["signed_sum"]=int(es.sum())
rep["abs_signed_sum"]=int(np.abs(es).sum())
rep["row_ptr_exact"]=bool(np.array_equal(row_ptr.astype(np.int64),exp_rp))
rep["dst_exact"]=bool(np.array_equal(dst,exp_dst))
rep["unsigned_count_exact"]=bool(np.array_equal(ucnt.astype(np.int64),eu))
rep["signed_count_exact"]=bool(np.array_equal(cnt.astype(np.int64),es))
src=np.repeat(np.arange(N,dtype=np.int32),np.diff(row_ptr.astype(np.int64)))
rep["self_edges"]=int(np.sum(src==dst))
rep["self_edge_policy_pass"]=rep["self_edges"]==80

# Unknown-NT source must have empty runtime row.
unsigned_sources=np.flatnonzero(expected_sign==0)
rep["unknown_nt_outgoing_edge_none"]=bool(np.all(np.diff(row_ptr.astype(np.int64))[unsigned_sources]==0))

inp=json.loads((ROOT/"FULL-1/INPUT_311_INDEX_MAP.json").read_text(encoding="utf-8"))
dn=json.loads((ROOT/"FULL-1/DN_32_INDEX_MAP.json").read_text(encoding="utf-8"))
rep["input_311_exact"]=sum(1 for x in inp["entries"] if ids[int(x["runtime_index"])]==int(x["body_id"]))
rep["dn_32_exact"]=sum(1 for x in dn["entries"] if ids[int(x["runtime_index"])]==int(x["source_neuron_identity"]))

checks=["body_ids_exact","body_ids_unique","index_range_pass","csr_monotonic","dst_bounds","zero_edge_none",
"sign_vector_exact","row_ptr_exact","dst_exact","unsigned_count_exact","signed_count_exact","self_edge_policy_pass",
"unknown_nt_outgoing_edge_none"]
rep["PASS"]=bool(all(rep[x] for x in checks) and N==166700 and E==24469412 and rep["contact_sum"]==120260398 and
 rep["signed_sum"]==26721930 and rep["abs_signed_sum"]==120260398 and rep["input_311_exact"]==311 and rep["dn_32_exact"]==32)
(ROOT/"FULL-1/PACK_VERIFICATION.json").write_text(json.dumps(rep,indent=2),encoding="utf-8")
print(json.dumps(rep,indent=2))
