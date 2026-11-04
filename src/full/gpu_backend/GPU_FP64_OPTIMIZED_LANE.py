"""GPU_FP64_OPTIMIZED_LANE

Semantics-preserving optimized FP64 lane.
Two kernels per tick, persistent GPU state, CUDA Graph replay per 200-tick FLY frame.
External drive policy supported here is the frozen deterministic frame policy:
all active input targets receive one W_EXTERNAL event on each flagged local tick.
"""
from __future__ import annotations
import hashlib,json,time
from pathlib import Path
import numpy as np
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import GPU_FP64_REFERENCE_LANE as R
cp=R.cp

CUDA_OPT=r'''
extern "C" {

__device__ __forceinline__ void atomicAddSignedLL(long long* address, long long val)
{
    atomicAdd((unsigned long long*)address,(unsigned long long)val);
}

__global__ void state_and_propagate(
    double* v, double* g, const int* last_spike, const int* rfc_ticks,
    unsigned char* not_ref, unsigned char* current_spike,
    const int* row_ptr, const int* dst, const int* signed_counts,
    const unsigned char* delay_ring, const int* tick_base, int local_tick, int n,
    long long* contrib,
    double v0_term, double couple_g, double decay_v, double decay_g, double v_threshold)
{
    int i=blockDim.x*blockIdx.x+threadIdx.x;
    if(i>=n) return;
    int tick=(*tick_base)+local_tick;
    bool nr=(tick-last_spike[i]) >= rfc_ticks[i];
    not_ref[i]=nr ? 1 : 0;
    if(nr){
        double oldg=g[i];
        double vi=v0_term + (oldg*couple_g + v[i]*decay_v);
        double gi=oldg*decay_g;
        v[i]=vi; g[i]=gi;
        current_spike[i]=(vi>v_threshold) ? 1 : 0;
    } else current_spike[i]=0;

    int slot=tick % 18;
    if(delay_ring[(long long)slot*n+i]){
        int lo=row_ptr[i], hi=row_ptr[i+1];
        for(int e=lo;e<hi;e++)
            atomicAddSignedLL(&contrib[dst[e]],(long long)signed_counts[e]);
    }
}

__global__ void apply_reset_clear(
    double* v, double* g, int* last_spike, long long* spike_counts,
    int* rfc_ticks, unsigned char* delay_ring,
    const unsigned char* not_ref, const unsigned char* current_spike,
    long long* contrib,
    const unsigned char* active_mask, const unsigned char* ext_flags,
    const int* tick_base, int local_tick, int n,
    const int* dn_slot_by_neuron, long long* dn_counts,
    unsigned int* event_count, int* event_ticks, int* event_neurons,
    unsigned int event_capacity, int capture_events,
    double w_syn, double w_ext, double v_reset)
{
    int i=blockDim.x*blockIdx.x+threadIdx.x;
    if(i>=n) return;
    int tick=(*tick_base)+local_tick;
    if(not_ref[i] && contrib[i]!=0LL)
        g[i] += ((double)contrib[i])*w_syn;
    if(ext_flags[local_tick] && active_mask[i] && not_ref[i])
        v[i] += w_ext;

    unsigned char s=current_spike[i];
    if(s){
        v[i]=v_reset; g[i]=0.0; last_spike[i]=tick; spike_counts[i]+=1LL;
        int ds=dn_slot_by_neuron[i];
        if(ds>=0) atomicAddSignedLL(&dn_counts[ds],1LL);
        if(capture_events){
            unsigned int p=atomicAdd(event_count,1u);
            if(p<event_capacity){ event_ticks[p]=tick; event_neurons[p]=i; }
        }
    }
    int slot=tick % 18;
    delay_ring[(long long)slot*n+i]=s;
    contrib[i]=0LL;
}

__global__ void prepare_frame(int* rfc_ticks, unsigned char* active_mask, int n)
{
    int i=blockDim.x*blockIdx.x+threadIdx.x;
    if(i<n){ rfc_ticks[i]=22; active_mask[i]=0; }
}

__global__ void activate_targets(int* rfc_ticks, unsigned char* active_mask,
                                 const int* targets, int m)
{
    int k=blockDim.x*blockIdx.x+threadIdx.x;
    if(k<m){ int j=targets[k]; rfc_ticks[j]=0; active_mask[j]=1; }
}

}
'''
class GPUFP64OptimizedLane:
    backend_id="GPU_FP64_CUPY_2KERNEL_CUDAGRAPH_V1"
    precision="float64"
    def __init__(self,event_capacity=2_000_000):
        integ=R.startup_integrity()
        if not integ["PASS"]: raise RuntimeError(integ)
        self.integrity=integ
        props=cp.cuda.runtime.getDeviceProperties(0)
        self.device_name=props["name"].decode() if isinstance(props["name"],bytes) else str(props["name"])
        self.mod=cp.RawModule(code=CUDA_OPT,options=("--std=c++11","--fmad=false"),
          name_expressions=("state_and_propagate","apply_reset_clear","prepare_frame","activate_targets"))
        self.k_sp=self.mod.get_function("state_and_propagate")
        self.k_ar=self.mod.get_function("apply_reset_clear")
        self.k_prep=self.mod.get_function("prepare_frame")
        self.k_act=self.mod.get_function("activate_targets")
        self.th=256

        self.body_ids_h=np.load(R.PACK/"body_ids.npy",allow_pickle=False)
        self.rp_h=np.load(R.PACK/"row_ptr.npy",allow_pickle=False).astype(np.int32,copy=False)
        self.dst_h=np.load(R.PACK/"dst_index.npy",allow_pickle=False).astype(np.int32,copy=False)
        self.cnt_h=np.load(R.PACK/"signed_contact_count.npy",allow_pickle=False).astype(np.int32,copy=False)
        self.n=len(self.body_ids_h); self.e=len(self.dst_h)
        dm=json.loads((R.F1/"DN_32_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
        dm=sorted(dm,key=lambda x:int(x["slot_index"]))
        self.dn_runtime_indices=np.asarray([int(x["runtime_index"]) for x in dm],np.int32)
        dnslot=np.full(self.n,-1,np.int32)
        for slot,j in enumerate(self.dn_runtime_indices): dnslot[j]=slot

        t0=time.perf_counter()
        self.rp=cp.asarray(self.rp_h); self.dst=cp.asarray(self.dst_h); self.cnt=cp.asarray(self.cnt_h)
        self.dnslot=cp.asarray(dnslot)
        self.v=cp.empty(self.n,cp.float64); self.g=cp.empty(self.n,cp.float64)
        self.last=cp.empty(self.n,cp.int32); self.rfc=cp.empty(self.n,cp.int32)
        self.ring=cp.empty((R.DELAY_TICKS,self.n),cp.uint8)
        self.counts=cp.empty(self.n,cp.int64); self.notref=cp.empty(self.n,cp.uint8)
        self.spike=cp.empty(self.n,cp.uint8); self.contrib=cp.empty(self.n,cp.int64)
        self.active_mask=cp.empty(self.n,cp.uint8)
        self.ext_flags=cp.zeros(200,cp.uint8)
        self.tick_base=cp.zeros(1,cp.int32)
        self.dnc=cp.zeros(32,cp.int64)
        self.event_capacity=int(event_capacity); self.ec=cp.zeros(1,cp.uint32)
        self.et=cp.empty(self.event_capacity,cp.int32); self.en=cp.empty(self.event_capacity,cp.int32)
        cp.cuda.Stream.null.synchronize()
        self.model_load_wall_s=time.perf_counter()-t0
        self.current_tick=0; self._graphs={}
        self.reset()

    def grid(self,n): return ((int(n)+self.th-1)//self.th,)

    def reset(self):
        self.v.fill(R.V_REST_MV); self.g.fill(0.0); self.last.fill(-1_000_000_000)
        self.rfc.fill(R.REFRACTORY_TICKS); self.ring.fill(0); self.counts.fill(0)
        self.notref.fill(0); self.spike.fill(0); self.contrib.fill(0); self.active_mask.fill(0)
        self.ext_flags.fill(0); self.tick_base.fill(0); self.dnc.fill(0); self.ec.fill(0)
        self.current_tick=0; cp.cuda.Stream.null.synchronize()

    def _launch_tick(self,local_tick,capture_events):
        self.k_sp(self.grid(self.n),(self.th,),
          (self.v,self.g,self.last,self.rfc,self.notref,self.spike,self.rp,self.dst,self.cnt,self.ring,
           self.tick_base,np.int32(local_tick),np.int32(self.n),self.contrib,
           np.float64(R.V0_TERM),np.float64(R.COUPLE_G),np.float64(R.DECAY_V),np.float64(R.DECAY_G),
           np.float64(R.V_THRESHOLD_MV)))
        self.k_ar(self.grid(self.n),(self.th,),
          (self.v,self.g,self.last,self.counts,self.rfc,self.ring,self.notref,self.spike,self.contrib,
           self.active_mask,self.ext_flags,self.tick_base,np.int32(local_tick),np.int32(self.n),
           self.dnslot,self.dnc,self.ec,self.et,self.en,np.uint32(self.event_capacity),
           np.int32(1 if capture_events else 0),np.float64(R.W_SYN_MV),np.float64(R.W_EXTERNAL_MV),
           np.float64(R.V_RESET_MV)))

    def _ensure_graph(self,capture_events):
        key=bool(capture_events)
        if key in self._graphs: return self._graphs[key]
        # Warm both kernels before stream capture.
        self._launch_tick(0,capture_events); cp.cuda.Stream.null.synchronize()
        # Restore initial state after warm-up side effect.
        self.reset()
        stream=cp.cuda.Stream(non_blocking=False)
        with stream:
            stream.begin_capture()
            for lt in range(200):
                self._launch_tick(lt,capture_events)
            graph=stream.end_capture()
        graph.upload(stream)
        stream.synchronize()
        self._graphs[key]=(graph,stream)
        return graph,stream

    def prepare_frame(self,active_targets,ext_local_ticks,tick_base):
        tg=np.asarray(active_targets,dtype=np.int32)
        flags=np.zeros(200,np.uint8)
        for t in ext_local_ticks:
            t=int(t)
            if t<0 or t>=200: raise ValueError("ext tick outside frame")
            flags[t]=1
        self.k_prep(self.grid(self.n),(self.th,),(self.rfc,self.active_mask,np.int32(self.n)))
        if len(tg):
            dtg=cp.asarray(tg)
            self.k_act(self.grid(len(tg)),(self.th,),(self.rfc,self.active_mask,dtg,np.int32(len(tg))))
        self.ext_flags.set(flags); self.tick_base.set(np.asarray([int(tick_base)],np.int32))
        self.dnc.fill(0); self.ec.fill(0)
    def run_frame(self,active_targets,ext_local_ticks=(33,100,166),capture_events=False,
                  use_graph=True,tick_base=None):
        if tick_base is None: tick_base=self.current_tick
        if int(tick_base)!=self.current_tick: raise ValueError("non-contiguous frame")
        graph,stream=self._ensure_graph(capture_events) if use_graph else (None,cp.cuda.Stream.null)

        h2d0=cp.cuda.Event(); h2d1=cp.cuda.Event(); h2d0.record()
        self.prepare_frame(active_targets,ext_local_ticks,tick_base)
        h2d1.record(); h2d1.synchronize(); h2d_ms=float(cp.cuda.get_elapsed_time(h2d0,h2d1))

        e0=cp.cuda.Event(); e1=cp.cuda.Event(); e0.record(stream)
        if use_graph:
            graph.launch(stream)
        else:
            with stream:
                for lt in range(200): self._launch_tick(lt,capture_events)
        e1.record(stream); e1.synchronize()
        compute_ms=float(cp.cuda.get_elapsed_time(e0,e1))
        self.current_tick += 200

        d0=cp.cuda.Event(); d1=cp.cuda.Event(); d0.record()
        dn=cp.asnumpy(self.dnc)
        total=int(cp.asnumpy(self.ec)[0]) if capture_events else 0
        overflow=max(0,total-self.event_capacity); take=min(total,self.event_capacity)
        if capture_events and take:
            ticks=cp.asnumpy(self.et[:take]); neurons=cp.asnumpy(self.en[:take])
            order=np.lexsort((neurons,ticks))
            ev=np.column_stack((ticks[order],neurons[order])).astype(np.int32,copy=False)
        else: ev=np.empty((0,2),np.int32)
        d1.record(); d1.synchronize(); d2h_ms=float(cp.cuda.get_elapsed_time(d0,d1))
        if overflow: raise RuntimeError(f"event overflow {overflow}")
        return {"events":ev,"dn_counts":dn,"dn_slots":(dn>0).astype(np.int32),
                "compute_ms":compute_ms,"h2d_ms":h2d_ms,"d2h_ms":d2h_ms}

    def state_to_host(self):
        return {"v":cp.asnumpy(self.v),"g":cp.asnumpy(self.g),"last_spike_tick":cp.asnumpy(self.last),
          "rfc_ticks":cp.asnumpy(self.rfc),"delay_ring":cp.asnumpy(self.ring),
          "spike_counts":cp.asnumpy(self.counts)}

    def state_hashes(self):
        s=self.state_to_host(); h=hashlib.sha256()
        for a in (s["v"],s["g"],s["last_spike_tick"],s["rfc_ticks"],s["delay_ring"],s["spike_counts"]):
            h.update(str(a.dtype).encode()); h.update(np.asarray(a.shape,np.int64).tobytes())
            h.update(np.ascontiguousarray(a).tobytes())
        h.update(np.asarray([self.current_tick],np.int64).tobytes())
        return {"state_digest":h.hexdigest(),"final_v_sha256":R.array_sha(s["v"]),
          "final_g_sha256":R.array_sha(s["g"]),"last_spike_sha256":R.array_sha(s["last_spike_tick"]),
          "delay_ring_sha256":R.array_sha(s["delay_ring"]),"spike_count_vector_sha256":R.array_sha(s["spike_counts"])}

    def memory_profile(self):
        free,total=cp.cuda.runtime.memGetInfo()
        return {"device":self.device_name,"free_bytes":int(free),"total_bytes":int(total),
          "cupy_pool_used_bytes":int(cp.get_default_memory_pool().used_bytes()),
          "cupy_pool_total_bytes":int(cp.get_default_memory_pool().total_bytes())}
