from pathlib import Path
import sys,json
import numpy as np
import brian2 as b2
from brian2 import ms,mV

ROOT=Path(r"D:\FPGA-AUTO\tasks\FLY-01-FULL-CNS")
F1=ROOT/"FULL-1"
sys.path.insert(0,str(F1))
import FULL_CPU_ORACLE_V1 as oracle
PACK=F1/"canonical_pack_v1"
b2.prefs.codegen.target='numpy'
P=oracle.P

def csr_from_edges(n,pre,post,cnt):
    pre=np.asarray(pre,dtype=np.int64); post=np.asarray(post,dtype=np.int64); cnt=np.asarray(cnt,dtype=np.int64)
    if len(pre):
        o=np.lexsort((post,pre)); pre=pre[o]; post=post[o]; cnt=cnt[o]
    rc=np.bincount(pre,minlength=n) if len(pre) else np.zeros(n,dtype=np.int64)
    rp=np.zeros(n+1,dtype=np.int64); np.cumsum(rc,out=rp[1:])
    return rp.astype(np.int32),post.astype(np.int32),cnt.astype(np.int32)

def brian_run(n,pre,post,cnt,n_ticks,initial_v,external_events=(),rfc_ms=None,initial_g=None):
    b2.start_scope(); b2.defaultclock.dt=P.dt_ms*ms
    ns={"v_0":P.v_rest_mV*mV,"v_rst":P.v_reset_mV*mV,"v_th":P.v_threshold_mV*mV,
        "t_mbr":P.tau_membrane_ms*ms,"tau":P.tau_synaptic_ms*ms}
    eqs='''dv/dt = (v_0 - v + g) / t_mbr : volt (unless refractory)
dg/dt = -g / tau : volt (unless refractory)
rfc : second'''
    G=b2.NeuronGroup(n,eqs,method='linear',threshold='v > v_th',
        reset='v = v_rst; w = 0; g = 0 * mV',refractory='rfc',namespace=ns,name='neurons')
    G.v=np.asarray(initial_v)*mV
    G.g=(np.zeros(n) if initial_g is None else np.asarray(initial_g))*mV
    if rfc_ms is None: rfc_ms=np.full(n,P.refractory_ms)
    G.rfc=np.asarray(rfc_ms)*ms
    objs=[G]
    if len(pre):
        S=b2.Synapses(G,G,'w:volt',on_pre='g += w',delay=P.synaptic_delay_ms*ms,name='syn')
        S.connect(i=np.asarray(pre,dtype=int),j=np.asarray(post,dtype=int))
        S.w=np.asarray(cnt,dtype=float)*P.w_syn_mV*mV
        objs.append(S)
    if external_events:
        M=len(external_events)
        ticks=np.asarray([x[0] for x in external_events],dtype=int)
        targets=np.asarray([x[1] for x in external_events],dtype=int)
        counts=np.asarray([x[2] for x in external_events],dtype=float)
        X=b2.SpikeGeneratorGroup(M,indices=np.arange(M),times=ticks*P.dt_ms*ms,name='extsrc')
        SX=b2.Synapses(X,G,'w:volt',on_pre='v_post += w',delay=0*ms,name='extsyn')
        SX.connect(i=np.arange(M),j=targets)
        SX.w=counts*P.w_ext_mV*mV
        objs += [X,SX]
    SP=b2.SpikeMonitor(G,name='spikes')
    SM=b2.StateMonitor(G,['v','g'],record=True,when='end',name='states')
    objs += [SP,SM]
    net=b2.Network(*objs); net.run(n_ticks*P.dt_ms*ms,namespace={})
    events=np.column_stack([np.rint(np.asarray(SP.t/ms)/P.dt_ms).astype(np.int64),np.asarray(SP.i,dtype=np.int64)])
    final_v=np.asarray(SM.v[:,-1]/mV,dtype=np.float64)
    final_g=np.asarray(SM.g[:,-1]/mV,dtype=np.float64)
    return {"events":events,"spike_counts":np.asarray(SP.count,dtype=np.int64),"v_mV":final_v,"g_mV":final_g}

def compare(name,n,pre,post,cnt,n_ticks,initial_v,external_events=(),rfc_ms=None,initial_g=None,meta=None):
    rp,dst,sc=csr_from_edges(n,pre,post,cnt)
    o=oracle.run(rp,dst,sc,n_ticks,initial_v_mV=initial_v,initial_g_mV=initial_g,
        external_events=external_events,rfc_ms=rfc_ms,record_events=True)
    b=brian_run(n,pre,post,cnt,n_ticks,initial_v,external_events,rfc_ms,initial_g)
    event_equal=np.array_equal(o["events"],b["events"])
    count_equal=np.array_equal(o["spike_counts"],b["spike_counts"])
    dv=float(np.max(np.abs(o["v_mV"]-b["v_mV"]))) if n else 0.0
    dg=float(np.max(np.abs(o["g_mV"]-b["g_mV"]))) if n else 0.0
    passed=event_equal and count_equal and dv<=1e-10 and dg<=1e-10
    return {"name":name,"PASS":passed,"event_exact":event_equal,"spike_count_exact":count_equal,
      "max_abs_v_delta_mV":dv,"max_abs_g_delta_mV":dg,
      "oracle_events":o["events"].tolist(),"brian2_events":b["events"].tolist(),
      "oracle_counts":o["spike_counts"].tolist(),"brian2_counts":b["spike_counts"].tolist(),
      "meta":meta or {}}

tests=[]
tests.append(compare("excitatory_chain",3,[0,1],[1,2],[40,40],120,[-44,-52,-52]))
tests.append(compare("inhibitory_chain",2,[0],[1],[-35],80,[-44,-45.5]))
tests.append(compare("self_loop",1,[0],[0],[50],80,[-44]))
tests.append(compare("mixed_EI_simultaneous",3,[0,1],[2,2],[30,-10],100,[-44,-44,-52]))
tests.append(compare("refractory_arrival",3,[0,0],[1,2],[4,4],40,[-44,-44,-52]))
tests.append(compare("multi_presynaptic",3,[0,1],[2,2],[10,20],100,[-44,-44,-52]))
A,B,V0T,C=oracle.coefficients()
v_exact=(P.v_threshold_mV-V0T)/A
tests.append(compare("threshold_near_boundary",2,[],[],[],5,[v_exact,v_exact+1e-8]))
tests.append(compare("external_order",1,[],[],[],5,[-52],external_events=[(0,0,1)],rfc_ms=[0.0]))

row=np.load(PACK/"row_ptr.npy",allow_pickle=False).astype(np.int64)
dst_full=np.load(PACK/"dst_index.npy",allow_pickle=False).astype(np.int64)
cnt_full=np.load(PACK/"signed_contact_count.npy",allow_pickle=False).astype(np.int64)
body=np.load(PACK/"body_ids.npy",allow_pickle=False)
deg=np.diff(row); seed=int(np.argmax(deg))
selected=[seed]; seen={seed}; q=[seed]
while q and len(selected)<32:
    s=q.pop(0); lo,hi=int(row[s]),int(row[s+1])
    if hi<=lo: continue
    inds=np.arange(lo,hi)
    order=inds[np.argsort(-np.abs(cnt_full[inds]),kind='stable')]
    for e in order[:12]:
        d=int(dst_full[e])
        if d not in seen:
            seen.add(d); selected.append(d); q.append(d)
            if len(selected)>=32: break
sel=np.asarray(selected,dtype=np.int64)
g2l={int(g):i for i,g in enumerate(sel)}
pre=[]; post=[]; cnt=[]
for li,gidx in enumerate(sel):
    lo,hi=int(row[gidx]),int(row[gidx+1])
    for e in range(lo,hi):
        d=int(dst_full[e])
        if d in g2l:
            pre.append(li); post.append(g2l[d]); cnt.append(int(cnt_full[e]))
initial=np.full(len(sel),-52.0)
events=[(0,0,1),(40,0,1),(80,0,1),(120,0,1)]
rfc_arr=np.full(len(sel),P.refractory_ms); rfc_arr[0]=0.0
tests.append(compare("malecns_derived_connected_subnet",len(sel),pre,post,cnt,180,initial,
    external_events=events,rfc_ms=rfc_arr,
    meta={"global_runtime_indices":sel.tolist(),"body_ids":body[sel].astype(np.int64).tolist(),
          "seed_global_index":seed,"seed_body_id":int(body[seed]),"induced_edges":len(pre)}))

rp,dst,sc=csr_from_edges(len(sel),pre,post,cnt)
o1=oracle.run(rp,dst,sc,180,initial_v_mV=initial,external_events=events,rfc_ms=rfc_arr)
o2=oracle.run(rp,dst,sc,180,initial_v_mV=initial,external_events=events,rfc_ms=rfc_arr)
det=all(np.array_equal(o1[k],o2[k]) for k in ("spike_counts","events","v_mV","g_mV","last_spike_tick"))

report={"brian2_version":b2.__version__,"dt_ms":P.dt_ms,"tolerance_mV":1e-10,
 "tests":tests,"all_tests_pass":all(t["PASS"] for t in tests),"determinism_pass":bool(det),
 "tiny_synthetic_pass":all(t["PASS"] for t in tests if t["name"]!="malecns_derived_connected_subnet"),
 "malecns_subnet_pass":next(t["PASS"] for t in tests if t["name"]=="malecns_derived_connected_subnet")}
(F1/"BRIAN2_PARITY_REPORT.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
validation={"oracle":"FULL_CPU_ORACLE_V1","float_precision":"float64","determinism":"PASS" if det else "FAIL",
 "brian2_parity":"PASS" if report["all_tests_pass"] else "FAIL","test_count":len(tests),
 "exact_event_tests":sum(t["event_exact"] for t in tests),"exact_count_tests":sum(t["spike_count_exact"] for t in tests),
 "max_v_delta_mV":max(t["max_abs_v_delta_mV"] for t in tests),
 "max_g_delta_mV":max(t["max_abs_g_delta_mV"] for t in tests)}
(F1/"CPU_ORACLE_VALIDATION.json").write_text(json.dumps(validation,indent=2),encoding="utf-8")
print(json.dumps(validation,indent=2))
for t in tests:
    print(t["name"],t["PASS"],t["event_exact"],t["max_abs_v_delta_mV"],t["max_abs_g_delta_mV"])
