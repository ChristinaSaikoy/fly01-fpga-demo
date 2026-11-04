"""FULL_REFERENCE_RUNTIME_V1

Correctness-first deterministic CPU runtime for the frozen FLY-01 FULL-1 model.
Identity:
  MaleCNS v1.0 canonical runtime graph
  + Shiu-derived engineering LIF semantics
Precision:
  float64 state, int64 per-tick synaptic accumulation
Execution:
  single-thread deterministic Numba kernels; no fastmath, no GPU.
Not a real-time claim and not biological ground truth.
"""
from __future__ import annotations
from pathlib import Path
import hashlib, json, math, os, time
import numpy as np
import psutil
from numba import njit

DT_MS=0.1
V_REST_MV=-52.0
V_RESET_MV=-52.0
V_THRESHOLD_MV=-45.0
TAU_MEMBRANE_MS=20.0
TAU_SYNAPTIC_MS=5.0
REFRACTORY_MS=2.2
SYNAPTIC_DELAY_MS=1.8
W_SYN_MV=0.275
F_POI=250.0
W_EXTERNAL_MV=W_SYN_MV*F_POI
REFRACTORY_TICKS=round(REFRACTORY_MS/DT_MS)
DELAY_TICKS=round(SYNAPTIC_DELAY_MS/DT_MS)

DECAY_V=math.exp(-DT_MS/TAU_MEMBRANE_MS)
DECAY_G=math.exp(-DT_MS/TAU_SYNAPTIC_MS)
V0_TERM=V_REST_MV - V_REST_MV*math.exp(-DT_MS/TAU_MEMBRANE_MS)
COUPLE_G=((TAU_SYNAPTIC_MS/(TAU_MEMBRANE_MS-TAU_SYNAPTIC_MS)) *
          (-math.exp(DT_MS/TAU_MEMBRANE_MS)+math.exp(DT_MS/TAU_SYNAPTIC_MS)) *
          math.exp(-DT_MS/TAU_MEMBRANE_MS) * math.exp(-DT_MS/TAU_SYNAPTIC_MS))

@njit(cache=True, fastmath=False)
def _step(row_ptr,dst,signed_counts,v,g,last_spike,rfc_ticks,delay_ring,
          spike_counts,not_ref,current_spike,contrib,fired_buf,tick,
          ext_targets,ext_mult):
    n=v.size
    # 1) Brian2 groups/state-update slot + 2) strict threshold slot.
    for i in range(n):
        nr=(tick-last_spike[i]) >= rfc_ticks[i]
        not_ref[i]=1 if nr else 0
        if nr:
            oldg=g[i]
            v[i]=V0_TERM + (oldg*COUPLE_G + v[i]*DECAY_V)
            g[i]=oldg*DECAY_G
            current_spike[i]=1 if v[i] > V_THRESHOLD_MV else 0
        else:
            current_spike[i]=0

    # 3a) recurrent synapses. Accumulate integer contacts first exactly like oracle.
    for i in range(n):
        contrib[i]=0
    slot=tick % DELAY_TICKS
    for src in range(n):
        if delay_ring[slot,src] != 0:
            lo=row_ptr[src]
            hi=row_ptr[src+1]
            for e in range(lo,hi):
                j=dst[e]
                contrib[j] += signed_counts[e]
    for i in range(n):
        if not_ref[i] != 0 and contrib[i] != 0:
            g[i] += float(contrib[i]) * W_SYN_MV

    # 3b) deterministic external drive in synapses slot, after threshold.
    for k in range(ext_targets.size):
        j=ext_targets[k]
        if not_ref[j] != 0:
            v[j] += float(ext_mult[k]) * W_EXTERNAL_MV

    # 4) reset/refractory + 5) store current spike vector in delay ring.
    fired_count=0
    for i in range(n):
        if current_spike[i] != 0:
            v[i]=V_RESET_MV
            g[i]=0.0
            last_spike[i]=tick
            spike_counts[i] += 1
            fired_buf[fired_count]=i
            fired_count += 1
        delay_ring[slot,i]=current_spike[i]
    return fired_count
def _sha_array(a: np.ndarray) -> str:
    h=hashlib.sha256()
    h.update(memoryview(np.ascontiguousarray(a)).cast("B"))
    return h.hexdigest()

def _sha_file(path: Path) -> str:
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for block in iter(lambda:f.read(1<<20),b""):
            h.update(block)
    return h.hexdigest()

def _normalize_events(events):
    """Return sorted per-tick dict: tick -> (targets int32, multiplicities int32).
    Input entries are (tick, runtime_index[, multiplicity]). Same-tick same-target
    entries are integer-aggregated deterministically."""
    by={}
    for item in events or ():
        if len(item)==2:
            t,j=item; m=1
        else:
            t,j,m=item
        t=int(t); j=int(j); m=int(m)
        if m==0:
            continue
        d=by.setdefault(t,{})
        d[j]=d.get(j,0)+m
    out={}
    for t,d in by.items():
        keys=sorted(d)
        out[t]=(np.asarray(keys,dtype=np.int32),
                np.asarray([d[k] for k in keys],dtype=np.int32))
    return out

def initialize_state(n, rfc_zero_targets=(), initial_v=None, initial_g=None):
    v=np.full(n,V_REST_MV,dtype=np.float64) if initial_v is None else np.asarray(initial_v,dtype=np.float64).copy()
    g=np.zeros(n,dtype=np.float64) if initial_g is None else np.asarray(initial_g,dtype=np.float64).copy()
    if v.shape!=(n,) or g.shape!=(n,):
        raise ValueError("initial state shape mismatch")
    last_spike=np.full(n,-1_000_000_000,dtype=np.int32)
    rfc_ticks=np.full(n,REFRACTORY_TICKS,dtype=np.int32)
    if len(rfc_zero_targets):
        rfc_ticks[np.asarray(rfc_zero_targets,dtype=np.int64)]=0
    delay_ring=np.zeros((DELAY_TICKS,n),dtype=np.uint8)
    spike_counts=np.zeros(n,dtype=np.int64)
    return v,g,last_spike,rfc_ticks,delay_ring,spike_counts

def run_in_memory(row_ptr,dst,signed_counts,n_ticks,events=(),rfc_zero_targets=(),
                  initial_v=None,initial_g=None):
    row_ptr=np.asarray(row_ptr,dtype=np.int32)
    dst=np.asarray(dst,dtype=np.int32)
    signed_counts=np.asarray(signed_counts,dtype=np.int32)
    n=row_ptr.size-1
    v,g,last_spike,rfc_ticks,ring,counts=initialize_state(
        n,rfc_zero_targets,initial_v,initial_g)
    not_ref=np.empty(n,dtype=np.uint8)
    spike=np.empty(n,dtype=np.uint8)
    contrib=np.empty(n,dtype=np.int64)
    fired=np.empty(n,dtype=np.int32)
    schedule=_normalize_events(events)
    chunks=[]
    empty_i32=np.empty(0,dtype=np.int32)
    for t in range(int(n_ticks)):
        et,em=schedule.get(t,(empty_i32,empty_i32))
        nf=_step(row_ptr,dst,signed_counts,v,g,last_spike,rfc_ticks,ring,
                 counts,not_ref,spike,contrib,fired,t,et,em)
        if nf:
            tickcol=np.full(nf,t,dtype=np.int32)
            chunks.append(np.column_stack((tickcol,fired[:nf].copy())))
    ev=np.concatenate(chunks,axis=0) if chunks else np.empty((0,2),dtype=np.int32)
    return {"v":v,"g":g,"last_spike_tick":last_spike,"rfc_ticks":rfc_ticks,
            "delay_ring":ring,"spike_counts":counts,"events":ev}
def load_pack(pack_dir):
    p=Path(pack_dir)
    return {
      "body_ids":np.load(p/"body_ids.npy",mmap_mode="r",allow_pickle=False),
      "row_ptr":np.load(p/"row_ptr.npy",mmap_mode="r",allow_pickle=False),
      "dst":np.load(p/"dst_index.npy",mmap_mode="r",allow_pickle=False),
      "signed_counts":np.load(p/"signed_contact_count.npy",mmap_mode="r",allow_pickle=False),
    }

def run_to_artifacts(pack_dir,n_ticks,events,rfc_zero_targets,out_state,out_events,
                     dn_indices=(),input_indices=(),initial_v=None,initial_g=None,
                     warmup_compile=False):
    pack=load_pack(pack_dir)
    row_ptr=pack["row_ptr"]; dst=pack["dst"]; signed_counts=pack["signed_counts"]
    n=row_ptr.size-1
    if row_ptr[0]!=0 or row_ptr[-1]!=dst.size or dst.size!=signed_counts.size:
        raise ValueError("invalid canonical pack")
    schedule=_normalize_events(events)
    for t,(et,_) in schedule.items():
        if t<0 or t>=n_ticks or np.any(et<0) or np.any(et>=n):
            raise ValueError("external event out of bounds")

    v,g,last_spike,rfc_ticks,ring,counts=initialize_state(
        n,rfc_zero_targets,initial_v,initial_g)
    not_ref=np.empty(n,dtype=np.uint8)
    spike=np.empty(n,dtype=np.uint8)
    contrib=np.empty(n,dtype=np.int64)
    fired=np.empty(n,dtype=np.int32)
    empty_i32=np.empty(0,dtype=np.int32)

    # Compile kernel with the real dtypes but a scratch tiny no-op call if requested.
    # Normal timing below starts after this optional JIT warm-up.
    if warmup_compile:
        _step(np.array([0],np.int32),np.empty(0,np.int32),np.empty(0,np.int32),
              np.empty(0,np.float64),np.empty(0,np.float64),np.empty(0,np.int32),
              np.empty(0,np.int32),np.empty((DELAY_TICKS,0),np.uint8),
              np.empty(0,np.int64),np.empty(0,np.uint8),np.empty(0,np.uint8),
              np.empty(0,np.int64),np.empty(0,np.int32),0,empty_i32,empty_i32)

    proc=psutil.Process(os.getpid())
    peak_rss=proc.memory_info().rss
    per_tick_spikes=np.zeros(n_ticks,dtype=np.int32)
    event_hash=hashlib.sha256()
    total_spikes=0
    active_mask=np.zeros(n,dtype=np.uint8)
    dn_indices=np.asarray(dn_indices,dtype=np.int32)
    input_indices=np.asarray(input_indices,dtype=np.int32)
    dn_counts=np.zeros(len(dn_indices),dtype=np.int64)
    input_counts=np.zeros(len(input_indices),dtype=np.int64)
    dn_pos={int(x):i for i,x in enumerate(dn_indices)}
    input_pos={int(x):i for i,x in enumerate(input_indices)}
    out_events=Path(out_events); out_events.parent.mkdir(parents=True,exist_ok=True)

    start=time.perf_counter()
    with open(out_events,"wb") as ef:
        for t in range(int(n_ticks)):
            et,em=schedule.get(t,(empty_i32,empty_i32))
            nf=_step(row_ptr,dst,signed_counts,v,g,last_spike,rfc_ticks,ring,
                     counts,not_ref,spike,contrib,fired,t,et,em)
            per_tick_spikes[t]=nf
            total_spikes += nf
            if nf:
                fired_now=fired[:nf]
                active_mask[fired_now]=1
                rec=np.empty((nf,2),dtype=np.int32)
                rec[:,0]=t; rec[:,1]=fired_now
                raw=rec.tobytes(order="C")
                ef.write(raw); event_hash.update(raw)
                # Observation only; no motor/body mapping.
                for j in fired_now:
                    jj=int(j)
                    p=dn_pos.get(jj)
                    if p is not None: dn_counts[p]+=1
                    p=input_pos.get(jj)
                    if p is not None: input_counts[p]+=1
            rss=proc.memory_info().rss
            if rss>peak_rss: peak_rss=rss
    wall=time.perf_counter()-start

    state_path=Path(out_state); state_path.parent.mkdir(parents=True,exist_ok=True)
    np.savez(state_path,v=v,g=g,last_spike_tick=last_spike,rfc_ticks=rfc_ticks,
             delay_ring=ring,spike_counts=counts,per_tick_spikes=per_tick_spikes)
    finite=bool(np.isfinite(v).all() and np.isfinite(g).all())
    result={
      "ticks":int(n_ticks),"model_time_ms":float(n_ticks*DT_MS),
      "wall_time_s":float(wall),"ms_per_tick":float(1000.0*wall/max(1,n_ticks)),
      "walltime_per_biological_second":float(wall/(n_ticks*DT_MS/1000.0)) if n_ticks else None,
      "total_spikes":int(total_spikes),"active_neurons":int(active_mask.sum()),
      "v_min_mV":float(v.min()),"v_max_mV":float(v.max()),
      "g_min_mV":float(g.min()),"g_max_mV":float(g.max()),
      "nan_count":int(np.isnan(v).sum()+np.isnan(g).sum()),
      "inf_count":int(np.isinf(v).sum()+np.isinf(g).sum()),
      "state_finite":finite,
      "delay_ring_spikes":int(ring.sum()),
      "event_record_format":"little/native-endian int32 pairs [tick,runtime_index]",
      "event_record_count":int(total_spikes),
      "event_stream_sha256":event_hash.hexdigest(),
      "spike_count_vector_sha256":_sha_array(counts),
      "final_v_sha256":_sha_array(v),"final_g_sha256":_sha_array(g),
      "last_spike_sha256":_sha_array(last_spike),"delay_ring_sha256":_sha_array(ring),
      "dn32_spike_counts":dn_counts.tolist(),"dn32_total_spikes":int(dn_counts.sum()),
      "dn32_output_sha256":_sha_array(dn_counts),
      "input_spike_counts":input_counts.tolist(),"input_total_spikes":int(input_counts.sum()),
      "peak_process_rss_bytes":int(peak_rss),
      "state_file":str(state_path),"state_file_sha256":_sha_file(state_path),
      "event_file":str(out_events),"event_file_sha256":_sha_file(out_events),
      "runtime_precision":"float64",
      "runtime_backend":"CPU Numba single-thread deterministic",
      "gpu_used":False
    }
    return result
