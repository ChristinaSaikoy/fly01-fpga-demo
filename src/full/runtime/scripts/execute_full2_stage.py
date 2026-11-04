from pathlib import Path
import sys,json,hashlib,time
import numpy as np

BASE=Path(r"D:\FPGA-AUTO\tasks\FLY-01-FULL-CNS")
F1=BASE/"FULL-1"
F2=BASE/"FULL-2"
PACK=F1/"canonical_pack_v1"
sys.path.insert(0,str(F2))
import FULL_REFERENCE_RUNTIME_V1 as rt

EXPECTED_PACK_SHA="b9a9168a653a90fd0c4405a78473a5f562ce55116361ca4f3e8781bef038e4a7"

def sha_file(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()

def pack_sha():
    rows=[]
    for p in sorted(x for x in PACK.iterdir() if x.is_file()):
        rows.append(f"{p.name}\t{p.stat().st_size}\t{sha_file(p)}\n")
    return hashlib.sha256("".join(rows).encode("utf-8")).hexdigest()

def load_maps():
    inp=json.loads((F1/"INPUT_311_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
    dn=json.loads((F1/"DN_32_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
    inp=sorted(inp,key=lambda x:int(x["input_slot"]))
    dn=sorted(dn,key=lambda x:int(x["slot_index"]))
    return inp,dn

def save_event_observations(name,event_path,input_idx,dn_idx):
    size=Path(event_path).stat().st_size
    assert size%8==0
    n=size//8
    ev=np.memmap(event_path,dtype=np.int32,mode="r",shape=(n,2)) if n else np.empty((0,2),np.int32)
    idx=ev[:,1] if n else np.empty(0,np.int32)

    dn_lookup={int(x):i for i,x in enumerate(dn_idx)}
    im_lookup={int(x):i for i,x in enumerate(input_idx)}
    if n:
        dnmask=np.isin(idx,dn_idx)
        immask=np.isin(idx,input_idx)
        dev=np.asarray(ev[dnmask])
        iev=np.asarray(ev[immask])
    else:
        dev=np.empty((0,2),np.int32); iev=np.empty((0,2),np.int32)

    dnrec=np.empty((len(dev),3),np.int32)
    if len(dev):
        dnrec[:,0]=dev[:,0]; dnrec[:,2]=dev[:,1]
        dnrec[:,1]=[dn_lookup[int(x)] for x in dev[:,1]]
    imrec=np.empty((len(iev),3),np.int32)
    if len(iev):
        imrec[:,0]=iev[:,0]; imrec[:,2]=iev[:,1]
        imrec[:,1]=[im_lookup[int(x)] for x in iev[:,1]]

    dnp=F2/"events"/f"{name}_DN32_EVENTS.npy"
    imp=F2/"events"/f"{name}_INPUT_EVENTS.npy"
    np.save(dnp,dnrec,allow_pickle=False)
    np.save(imp,imrec,allow_pickle=False)
    bounds=bool(n==0 or (int(idx.min())>=0 and int(idx.max())<166700))
    return {
      "event_index_bounds_pass":bounds,
      "dn32_event_count":int(len(dnrec)),
      "dn32_event_file":str(dnp),"dn32_event_file_sha256":sha_file(dnp),
      "input_event_count":int(len(imrec)),
      "input_event_file":str(imp),"input_event_file_sha256":sha_file(imp)
    }

def finalize(name,summary,input_idx,dn_idx):
    state=np.load(summary["state_file"],allow_pickle=False)
    counts=state["spike_counts"]
    pts=state["per_tick_spikes"]
    ring=state["delay_ring"]
    obs=save_event_observations(name,summary["event_file"],input_idx,dn_idx)
    expected_ring=int(pts[-min(len(pts),rt.DELAY_TICKS):].astype(np.int64).sum()) if len(pts) else 0
    integrity={
      "spike_count_sum_matches_events":int(counts.sum())==summary["total_spikes"],
      "per_tick_sum_matches_events":int(pts.astype(np.int64).sum())==summary["total_spikes"],
      "delay_ring_consistency":int(ring.sum())==expected_ring,
      "delay_ring_expected_spikes":expected_ring,
      "runtime_index_bounds":obs["event_index_bounds_pass"],
      "state_vector_lengths_pass":len(state["v"])==166700 and len(state["g"])==166700,
      "nan_count_zero":summary["nan_count"]==0,
      "inf_count_zero":summary["inf_count"]==0
    }
    integrity["PASS"]=all(v for k,v in integrity.items() if isinstance(v,bool))
    summary.update(obs)
    summary["state_integrity"]=integrity
    summary["run_name"]=name
    summary["pack_sha256"]=pack_sha()
    (F2/f"{name}.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    return summary

def run_stage(stage):
    ps=pack_sha()
    if ps!=EXPECTED_PACK_SHA:
        raise RuntimeError(f"pack sha mismatch {ps}")
    inp,dn=load_maps()
    input_idx=np.asarray([int(x["runtime_index"]) for x in inp],np.int32)
    dn_idx=np.asarray([int(x["runtime_index"]) for x in dn],np.int32)
    body=np.load(PACK/"body_ids.npy",mmap_mode="r",allow_pickle=False)
    # JIT before formal timing.
    rt.run_in_memory(np.array([0,0],np.int32),np.empty(0,np.int32),np.empty(0,np.int32),1)

    if stage=="T0":
        n=len(body)
        v,g,last,rfc,ring,counts=rt.initialize_state(n)
        rep={
          "run_name":"T0_INITIALIZATION","pack_sha256":ps,"neurons":n,"ticks":0,
          "v_all_rest":bool(np.all(v==rt.V_REST_MV)),
          "g_all_zero":bool(np.all(g==0.0)),
          "delay_ring_empty":bool(ring.sum()==0),
          "spikes_zero":bool(counts.sum()==0),
          "last_spike_initialized":bool(np.all(last==-1_000_000_000)),
          "PASS":bool(np.all(v==rt.V_REST_MV) and np.all(g==0.0) and ring.sum()==0 and counts.sum()==0)
        }
        (F2/"T0_INITIALIZATION.json").write_text(json.dumps(rep,indent=2),encoding="utf-8")
        print(json.dumps(rep,indent=2)); return

    if stage=="T1":
        name="RUN_ZERO_100T"; ticks=100; events=[]; zero=[]
    elif stage=="T2":
        name="RUN_SINGLE_INPUT_100T"; ticks=100
        j=int(input_idx[0]); events=[(0,j,1)]; zero=[j]
    elif stage=="T3":
        name="RUN_MULTI_INPUT_500T"; ticks=500
        subset=input_idx[:16]
        events=[(t,int(j),1) for t in (0,100,200,300,400) for j in subset]
        zero=[int(x) for x in subset]
    elif stage.startswith("T4R"):
        repno=int(stage[3:])
        name=f"RUN_311_INPUT_1000T_R{repno}"; ticks=1000
        event_ticks=(0,100,200,300,400,500,600,700,800,900)
        events=[(t,int(j),1) for t in event_ticks for j in input_idx]
        zero=[int(x) for x in input_idx]
    else:
        raise ValueError(stage)

    state=F2/"events"/f"{name}_STATE.npz"
    ev=F2/"events"/f"{name}_EVENTS.i32.bin"
    summary=rt.run_to_artifacts(PACK,ticks,events,zero,state,ev,
        dn_indices=dn_idx,input_indices=input_idx)
    summary["external_event_count"]=sum(int(x[2]) if len(x)>2 else 1 for x in events)
    summary["external_target_count"]=len(set(int(x[1]) for x in events))
    if stage=="T2":
        summary["selected_input_slot"]=0
        summary["selected_input_runtime_index"]=int(input_idx[0])
        summary["selected_input_body_id"]=int(body[input_idx[0]])
    if stage=="T3":
        summary["selected_input_slots"]=list(range(16))
    if stage.startswith("T4R"):
        summary["input_policy"]="all 311 inputs, deterministic 100 Hz equivalent: one explicit event every 100 ticks"
    summary=finalize(name,summary,input_idx,dn_idx)
    print(json.dumps(summary,indent=2))

if __name__=="__main__":
    run_stage(sys.argv[1])
