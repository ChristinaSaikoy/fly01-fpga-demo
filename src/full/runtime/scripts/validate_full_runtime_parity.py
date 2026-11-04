from pathlib import Path
import json,sys
import numpy as np

BASE=Path(r"D:\FPGA-AUTO\tasks\FLY-01-FULL-CNS")
sys.path.insert(0,str(BASE/"FULL-1"))
sys.path.insert(0,str(BASE/"FULL-2"))
import FULL_CPU_ORACLE_V1 as oracle
import FULL_REFERENCE_RUNTIME_V1 as rt

def csr(n,edges):
    if not edges:
        return np.zeros(n+1,np.int32),np.zeros(0,np.int32),np.zeros(0,np.int32)
    a=np.asarray(edges,dtype=np.int64)
    a=a[np.lexsort((a[:,1],a[:,0]))]
    rows=np.bincount(a[:,0],minlength=n)
    rp=np.zeros(n+1,dtype=np.int64); np.cumsum(rows,out=rp[1:])
    return rp.astype(np.int32),a[:,1].astype(np.int32),a[:,2].astype(np.int32)

def compare(name,n,edges,n_ticks,initial_v=None,initial_g=None,events=(),zero_targets=(),meta=None):
    rp,dst,cnt=csr(n,edges)
    rfc_ms=np.full(n,oracle.P.refractory_ms,dtype=np.float64)
    if len(zero_targets): rfc_ms[np.asarray(zero_targets,dtype=int)]=0.0
    a=oracle.run(rp,dst,cnt,n_ticks,initial_v_mV=initial_v,initial_g_mV=initial_g,
                 external_events=events,rfc_ms=rfc_ms,record_events=True)
    b=rt.run_in_memory(rp,dst,cnt,n_ticks,events=events,rfc_zero_targets=zero_targets,
                       initial_v=initial_v,initial_g=initial_g)
    ev=bool(np.array_equal(a["events"].astype(np.int32),b["events"]))
    counts=bool(np.array_equal(a["spike_counts"],b["spike_counts"]))
    dv=float(np.max(np.abs(a["v_mV"]-b["v"]))) if n else 0.0
    dg=float(np.max(np.abs(a["g_mV"]-b["g"]))) if n else 0.0
    passed=ev and counts and dv<=1e-10 and dg<=1e-10
    return {"name":name,"PASS":passed,"event_exact":ev,"count_exact":counts,
            "max_abs_v_delta_mV":dv,"max_abs_g_delta_mV":dg,
            "oracle_total_spikes":int(a["spike_counts"].sum()),
            "runtime_total_spikes":int(b["spike_counts"].sum()),"meta":meta or {}}

cases=[]
cases.append(compare("excitatory_chain",3,[(0,1,3000),(1,2,1200)],80,
    initial_v=[-44,-52,-52]))
cases.append(compare("inhibitory_chain",3,[(0,1,-2500),(1,2,-800)],70,
    initial_v=[-44,-46,-46]))
cases.append(compare("self_loop",1,[(0,0,1500)],100,initial_v=[-44]))
cases.append(compare("mixed_EI",3,[(0,2,1600),(1,2,-900)],80,
    initial_v=[-44,-44,-52]))
cases.append(compare("refractory_arrival",2,[(0,1,3000)],50,
    initial_v=[-44,-44]))
cases.append(compare("simultaneous_presynaptic",3,[(0,2,1000),(1,2,2000)],70,
    initial_v=[-44,-44,-52]))
A,B,V0T,C=oracle.coefficients()
v_exact=(oracle.P.v_threshold_mV-V0T)/A
cases.append(compare("threshold_boundary",2,[],5,initial_v=[v_exact,v_exact+1e-8]))
cases.append(compare("external_order",1,[],5,initial_v=[-52],
    events=[(0,0,1)],zero_targets=[0]))
# Actual MaleCNS-derived induced subnet.
P=BASE/"FULL-1/canonical_pack_v1"
full_rp=np.load(P/"row_ptr.npy",mmap_mode="r",allow_pickle=False).astype(np.int64)
full_dst=np.load(P/"dst_index.npy",mmap_mode="r",allow_pickle=False).astype(np.int64)
full_cnt=np.load(P/"signed_contact_count.npy",mmap_mode="r",allow_pickle=False).astype(np.int64)
body=np.load(P/"body_ids.npy",mmap_mode="r",allow_pickle=False)
deg=np.diff(full_rp)
root=int(np.argmax(deg))
selected=[root]; seen={root}; q=[root]
while q and len(selected)<64:
    s=q.pop(0)
    lo,hi=int(full_rp[s]),int(full_rp[s+1])
    inds=np.arange(lo,hi)
    order=inds[np.argsort(-np.abs(full_cnt[inds]),kind="stable")]
    for e in order[:16]:
        d=int(full_dst[e])
        if d not in seen:
            seen.add(d); selected.append(d); q.append(d)
            if len(selected)>=64: break
sel=np.asarray(selected,dtype=np.int64)
g2l={int(g):i for i,g in enumerate(sel)}
edges=[]
for li,gidx in enumerate(sel):
    for e in range(int(full_rp[gidx]),int(full_rp[gidx+1])):
        d=int(full_dst[e])
        if d in g2l:
            edges.append((li,g2l[d],int(full_cnt[e])))
subdeg=np.zeros(len(sel),dtype=np.int64)
for s,d,w in edges: subdeg[s]+=1
driven=np.argsort(-subdeg,kind="stable")[:4]
events=[(t,int(j),1) for t in range(0,180,20) for j in driven]
cases.append(compare("malecns_derived_subnet",len(sel),edges,180,
    initial_v=np.full(len(sel),-52.0),events=events,zero_targets=driven,
    meta={"neurons":len(sel),"edges":len(edges),"root_body_id":int(body[root]),
          "body_ids":[int(x) for x in body[sel[:16]]]}))

all_pass=all(x["PASS"] for x in cases)
report={
 "runtime":"FULL_REFERENCE_RUNTIME_V1",
 "runtime_precision":"float64",
 "runtime_backend":"CPU Numba single-thread, fastmath=False",
 "oracle":"FULL_CPU_ORACLE_V1",
 "tolerance_mV":1e-10,
 "tests":cases,
 "test_count":len(cases),
 "exact_event_tests":sum(1 for x in cases if x["event_exact"]),
 "exact_count_tests":sum(1 for x in cases if x["count_exact"]),
 "max_v_delta_mV":max(x["max_abs_v_delta_mV"] for x in cases),
 "max_g_delta_mV":max(x["max_abs_g_delta_mV"] for x in cases),
 "ORACLE_SUBNET_PARITY":"PASS" if all_pass else "FAIL"
}
(BASE/"FULL-2/ORACLE_RUNTIME_PARITY.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
print(json.dumps(report,indent=2))
sys.exit(0 if all_pass else 1)
