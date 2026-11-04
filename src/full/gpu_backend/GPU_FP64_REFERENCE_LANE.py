"""GPU_FP64_REFERENCE_LANE

Correctness-first RTX 4080 Laptop GPU backend for the frozen FLY-01 Full model.

Frozen semantics:
- same canonical source-major CSR
- float64 v/g
- int64 signed-contact accumulation
- same state-update -> threshold -> recurrent/external synapses -> reset ordering
- same 18-tick delay, refractory semantics, strict threshold, w_syn
- graph/state persist on GPU across frames

This lane is a numerical implementation candidate, not a new scientific model.
"""
from __future__ import annotations
import os,sys,ctypes,hashlib,json,math,time
from pathlib import Path
import numpy as np

BASE=Path(r"D:\FPGA-AUTO\tasks\FLY-01-FULL-CNS")
F1=BASE/"FULL-1"
F2=BASE/"FULL-2"
F3=BASE/"FULL-3"
PACK=F1/"canonical_pack_v1"

PACK_SHA256="b9a9168a653a90fd0c4405a78473a5f562ce55116361ca4f3e8781bef038e4a7"
RUNTIME_SHA256="942b1b06214c8de6ff6bad833e26bdd71ea0d2bcc6abe016fb3836eb238c2c8d"
INPUT_ADAPTER_SHA256="2abe9d79d6fb56a616d9e928cd9189ed7387f31ad60c3d057a142413c18a25da"
DN_ADAPTER_SHA256="1c880328df7febd816b6d23ec513faba042272e28420e9b6bb2760134fed9bbb"

DT_MS=0.1
V_REST_MV=-52.0
V_RESET_MV=-52.0
V_THRESHOLD_MV=-45.0
TAU_MEMBRANE_MS=20.0
TAU_SYNAPTIC_MS=5.0
REFRACTORY_TICKS=22
DELAY_TICKS=18
W_SYN_MV=0.275
W_EXTERNAL_MV=68.75

# Constants computed with CPython math, matching FULL_REFERENCE_RUNTIME_V1 source.
DECAY_V=math.exp(-DT_MS/TAU_MEMBRANE_MS)
DECAY_G=math.exp(-DT_MS/TAU_SYNAPTIC_MS)
V0_TERM=V_REST_MV - V_REST_MV*math.exp(-DT_MS/TAU_MEMBRANE_MS)
COUPLE_G=((TAU_SYNAPTIC_MS/(TAU_MEMBRANE_MS-TAU_SYNAPTIC_MS)) *
          (-math.exp(DT_MS/TAU_MEMBRANE_MS)+math.exp(DT_MS/TAU_SYNAPTIC_MS)) *
          math.exp(-DT_MS/TAU_MEMBRANE_MS) * math.exp(-DT_MS/TAU_SYNAPTIC_MS))

def _setup_cuda_wheel_dlls():
    venv=Path(sys.executable).resolve().parents[1]
    nvidia=venv/"Lib/site-packages/nvidia"
    nvrtc_bin=nvidia/"cuda_nvrtc/bin"
    runtime_root=nvidia/"cuda_runtime"
    runtime_bin=runtime_root/"bin"
    if os.name=="nt":
        os.environ["PATH"]=str(nvrtc_bin)+os.pathsep+str(runtime_bin)+os.pathsep+os.environ.get("PATH","")
        os.environ["CUDA_PATH"]=str(runtime_root)
        if nvrtc_bin.exists(): os.add_dll_directory(str(nvrtc_bin))
        if runtime_bin.exists(): os.add_dll_directory(str(runtime_bin))
        ctypes.windll.kernel32.SetDllDirectoryW(str(nvrtc_bin))
        builtins=nvrtc_bin/"nvrtc-builtins64_129.dll"
        nvrtc=nvrtc_bin/"nvrtc64_120_0.dll"
        if builtins.exists(): ctypes.WinDLL(str(builtins))
        if nvrtc.exists(): ctypes.WinDLL(str(nvrtc))

_setup_cuda_wheel_dlls()
import cupy as cp

def sha_file(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()

def pack_sha():
    rows=[]
    for p in sorted(x for x in PACK.iterdir() if x.is_file()):
        rows.append(f"{p.name}\t{p.stat().st_size}\t{sha_file(p)}\n")
    return hashlib.sha256("".join(rows).encode()).hexdigest()

def array_sha(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()

def startup_integrity():
    checks={
      "pack":{"expected":PACK_SHA256,"actual":pack_sha()},
      "cpu_runtime":{"expected":RUNTIME_SHA256,"actual":sha_file(F2/"FULL_REFERENCE_RUNTIME_V1.py")},
      "input_adapter":{"expected":INPUT_ADAPTER_SHA256,"actual":sha_file(F3/"FULL_INPUT_ADAPTER_V1.py")},
      "dn_adapter":{"expected":DN_ADAPTER_SHA256,"actual":sha_file(F3/"FULL_DN_ADAPTER_V1.py")},
    }
    for x in checks.values(): x["PASS"]=x["expected"]==x["actual"]
    return {"checks":checks,"PASS":all(x["PASS"] for x in checks.values())}
CUDA_SRC=r'''
extern "C" {

__global__ void state_threshold(
    double* v, double* g, const int* last_spike, const int* rfc_ticks,
    unsigned char* not_ref, unsigned char* current_spike,
    int tick, int n,
    double v0_term, double couple_g, double decay_v, double decay_g,
    double v_threshold)
{
    int i=blockDim.x*blockIdx.x+threadIdx.x;
    if(i>=n) return;
    bool nr=(tick-last_spike[i]) >= rfc_ticks[i];
    not_ref[i]=nr ? 1 : 0;
    if(nr){
        double oldg=g[i];
        double vi=v0_term + (oldg*couple_g + v[i]*decay_v);
        double gi=oldg*decay_g;
        v[i]=vi;
        g[i]=gi;
        current_spike[i]=(vi>v_threshold) ? 1 : 0;
    } else {
        current_spike[i]=0;
    }
}

__global__ void clear_i64(long long* x, int n)
{
    int i=blockDim.x*blockIdx.x+threadIdx.x;
    if(i<n) x[i]=0LL;
}

__device__ __forceinline__ void atomicAddSignedLL(long long* address, long long val)
{
    atomicAdd((unsigned long long*)address,(unsigned long long)val);
}

__global__ void propagate(
    const int* row_ptr, const int* dst, const int* signed_counts,
    const unsigned char* delay_ring, int slot, int n,
    long long* contrib)
{
    int src=blockDim.x*blockIdx.x+threadIdx.x;
    if(src>=n) return;
    if(delay_ring[(long long)slot*n + src]==0) return;
    int lo=row_ptr[src];
    int hi=row_ptr[src+1];
    for(int e=lo;e<hi;e++){
        atomicAddSignedLL(&contrib[dst[e]],(long long)signed_counts[e]);
    }
}

__global__ void apply_synaptic(
    double* g, const long long* contrib, const unsigned char* not_ref,
    int n, double w_syn)
{
    int i=blockDim.x*blockIdx.x+threadIdx.x;
    if(i<n && not_ref[i] && contrib[i]!=0LL)
        g[i] += ((double)contrib[i])*w_syn;
}

__global__ void apply_external(
    double* v, const unsigned char* not_ref,
    const int* targets, const int* mult, int m, double w_ext)
{
    int k=blockDim.x*blockIdx.x+threadIdx.x;
    if(k>=m) return;
    int j=targets[k];
    if(not_ref[j])
        v[j] += ((double)mult[k])*w_ext;
}

__global__ void reset_store(
    double* v, double* g, int* last_spike, long long* spike_counts,
    unsigned char* delay_ring, const unsigned char* current_spike,
    const int* dn_slot_by_neuron, long long* dn_counts,
    unsigned int* event_count, int* event_ticks, int* event_neurons, unsigned int event_capacity,
    int slot, int tick, int n, double v_reset, int capture_events)
{
    int i=blockDim.x*blockIdx.x+threadIdx.x;
    if(i>=n) return;
    unsigned char s=current_spike[i];
    if(s){
        v[i]=v_reset;
        g[i]=0.0;
        last_spike[i]=tick;
        spike_counts[i]+=1LL;
        int ds=dn_slot_by_neuron[i];
        if(ds>=0) atomicAddSignedLL(&dn_counts[ds],1LL);
        if(capture_events){
            unsigned int p=atomicAdd(event_count,1u);
            if(p<event_capacity){
                event_ticks[p]=tick;
                event_neurons[p]=i;
            }
        }
    }
    delay_ring[(long long)slot*n + i]=s;
}

__global__ void set_all_i32(int* x, int value, int n)
{
    int i=blockDim.x*blockIdx.x+threadIdx.x;
    if(i<n) x[i]=value;
}

__global__ void set_targets_i32(int* x, const int* targets, int value, int m)
{
    int i=blockDim.x*blockIdx.x+threadIdx.x;
    if(i<m) x[targets[i]]=value;
}

}
'''
class GPUFP64ReferenceLane:
    backend_id="GPU_FP64_REFERENCE_LANE_CUPY_RAWKERNEL_V1"
    precision="float64"
    def __init__(self, event_capacity=2_000_000):
        integ=startup_integrity()
        if not integ["PASS"]: raise RuntimeError(integ)
        self.integrity=integ
        props=cp.cuda.runtime.getDeviceProperties(0)
        self.device_name=props["name"].decode() if isinstance(props["name"],bytes) else str(props["name"])
        self.module=cp.RawModule(code=CUDA_SRC,options=("--std=c++11","--fmad=false"),
                                 name_expressions=("state_threshold","clear_i64","propagate",
                                   "apply_synaptic","apply_external","reset_store",
                                   "set_all_i32","set_targets_i32"))
        self.k_state=self.module.get_function("state_threshold")
        self.k_clear=self.module.get_function("clear_i64")
        self.k_prop=self.module.get_function("propagate")
        self.k_syn=self.module.get_function("apply_synaptic")
        self.k_ext=self.module.get_function("apply_external")
        self.k_reset=self.module.get_function("reset_store")
        self.k_setall=self.module.get_function("set_all_i32")
        self.k_settargets=self.module.get_function("set_targets_i32")
        self.threads=256

        self.body_ids_h=np.load(PACK/"body_ids.npy",allow_pickle=False)
        self.row_ptr_h=np.load(PACK/"row_ptr.npy",allow_pickle=False).astype(np.int32,copy=False)
        self.dst_h=np.load(PACK/"dst_index.npy",allow_pickle=False).astype(np.int32,copy=False)
        self.signed_h=np.load(PACK/"signed_contact_count.npy",allow_pickle=False).astype(np.int32,copy=False)
        self.n=len(self.body_ids_h)
        self.e=len(self.dst_h)

        dm=json.loads((F1/"DN_32_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
        dm=sorted(dm,key=lambda x:int(x["slot_index"]))
        self.dn_runtime_indices=np.asarray([int(x["runtime_index"]) for x in dm],dtype=np.int32)
        dn_slot=np.full(self.n,-1,dtype=np.int32)
        for slot,j in enumerate(self.dn_runtime_indices): dn_slot[j]=slot

        t0=time.perf_counter()
        self.row_ptr=cp.asarray(self.row_ptr_h)
        self.dst=cp.asarray(self.dst_h)
        self.signed=cp.asarray(self.signed_h)
        self.dn_slot=cp.asarray(dn_slot)
        self.v=cp.empty(self.n,dtype=cp.float64)
        self.g=cp.empty(self.n,dtype=cp.float64)
        self.last_spike=cp.empty(self.n,dtype=cp.int32)
        self.rfc_ticks=cp.empty(self.n,dtype=cp.int32)
        self.ring=cp.empty((DELAY_TICKS,self.n),dtype=cp.uint8)
        self.spike_counts=cp.empty(self.n,dtype=cp.int64)
        self.not_ref=cp.empty(self.n,dtype=cp.uint8)
        self.current_spike=cp.empty(self.n,dtype=cp.uint8)
        self.contrib=cp.empty(self.n,dtype=cp.int64)
        self.dn_counts=cp.empty(32,dtype=cp.int64)
        self.event_capacity=int(event_capacity)
        self.event_count=cp.zeros(1,dtype=cp.uint32)
        self.event_ticks=cp.empty(self.event_capacity,dtype=cp.int32)
        self.event_neurons=cp.empty(self.event_capacity,dtype=cp.int32)
        cp.cuda.Stream.null.synchronize()
        self.model_load_wall_s=time.perf_counter()-t0
        self.current_tick=0
        self.reset()

    def _grid(self,n): return ((int(n)+self.threads-1)//self.threads,)

    def reset(self, initial_v=None, initial_g=None, rfc_zero_targets=()):
        if initial_v is None: self.v.fill(V_REST_MV)
        else: self.v.set(np.asarray(initial_v,dtype=np.float64))
        if initial_g is None: self.g.fill(0.0)
        else: self.g.set(np.asarray(initial_g,dtype=np.float64))
        self.last_spike.fill(-1_000_000_000)
        self.rfc_ticks.fill(REFRACTORY_TICKS)
        if len(rfc_zero_targets):
            tg=cp.asarray(np.asarray(rfc_zero_targets,dtype=np.int32))
            self.k_settargets(self._grid(len(tg)),(self.threads,),(self.rfc_ticks,tg,np.int32(0),np.int32(len(tg))))
        self.ring.fill(0)
        self.spike_counts.fill(0)
        self.not_ref.fill(0)
        self.current_spike.fill(0)
        self.contrib.fill(0)
        self.dn_counts.fill(0)
        self.event_count.fill(0)
        self.current_tick=0
        cp.cuda.Stream.null.synchronize()

    def set_frame_refractory(self,active_targets=()):
        self.k_setall(self._grid(self.n),(self.threads,),(self.rfc_ticks,np.int32(REFRACTORY_TICKS),np.int32(self.n)))
        if len(active_targets):
            tg=cp.asarray(np.asarray(active_targets,dtype=np.int32))
            self.k_settargets(self._grid(len(tg)),(self.threads,),(self.rfc_ticks,tg,np.int32(0),np.int32(len(tg))))
    @staticmethod
    def normalize_events(events):
        by={}
        iterable=() if events is None else events
        for item in iterable:
            if len(item)==2: t,j=item; m=1
            else: t,j,m=item
            t=int(t); j=int(j); m=int(m)
            if m==0: continue
            d=by.setdefault(t,{})
            d[j]=d.get(j,0)+m
        out={}
        for t,d in by.items():
            keys=sorted(d)
            out[t]=(np.asarray(keys,dtype=np.int32),
                    np.asarray([d[k] for k in keys],dtype=np.int32))
        return out

    def run_ticks(self,n_ticks,events=(),rfc_zero_targets=(),capture_events=True,
                  start_tick=None,reset_event_buffer=True):
        if start_tick is None: start_tick=self.current_tick
        start_tick=int(start_tick)
        if start_tick!=self.current_tick: raise ValueError("non-contiguous start_tick")
        self.set_frame_refractory(rfc_zero_targets)
        schedule=self.normalize_events(events)
        if reset_event_buffer: self.event_count.fill(0)
        self.dn_counts.fill(0)

        # Upload all unique per-tick event arrays before measured compute.
        dev_events={}
        h2d_start=cp.cuda.Event(); h2d_end=cp.cuda.Event()
        h2d_start.record()
        for t,(targets,mult) in schedule.items():
            dev_events[int(t)]=(cp.asarray(targets),cp.asarray(mult))
        h2d_end.record(); h2d_end.synchronize()
        h2d_ms=float(cp.cuda.get_elapsed_time(h2d_start,h2d_end))

        comp_start=cp.cuda.Event(); comp_end=cp.cuda.Event()
        comp_start.record()
        for tick in range(start_tick,start_tick+int(n_ticks)):
            self.k_state(self._grid(self.n),(self.threads,),
                (self.v,self.g,self.last_spike,self.rfc_ticks,self.not_ref,self.current_spike,
                 np.int32(tick),np.int32(self.n),
                 np.float64(V0_TERM),np.float64(COUPLE_G),np.float64(DECAY_V),np.float64(DECAY_G),
                 np.float64(V_THRESHOLD_MV)))
            self.k_clear(self._grid(self.n),(self.threads,),(self.contrib,np.int32(self.n)))
            slot=tick%DELAY_TICKS
            self.k_prop(self._grid(self.n),(self.threads,),
                (self.row_ptr,self.dst,self.signed,self.ring,np.int32(slot),np.int32(self.n),self.contrib))
            self.k_syn(self._grid(self.n),(self.threads,),
                (self.g,self.contrib,self.not_ref,np.int32(self.n),np.float64(W_SYN_MV)))
            ev=dev_events.get(tick)
            if ev is not None:
                tg,mu=ev
                self.k_ext(self._grid(len(tg)),(self.threads,),
                    (self.v,self.not_ref,tg,mu,np.int32(len(tg)),np.float64(W_EXTERNAL_MV)))
            self.k_reset(self._grid(self.n),(self.threads,),
                (self.v,self.g,self.last_spike,self.spike_counts,self.ring,self.current_spike,
                 self.dn_slot,self.dn_counts,self.event_count,self.event_ticks,self.event_neurons,
                 np.uint32(self.event_capacity),np.int32(slot),np.int32(tick),np.int32(self.n),
                 np.float64(V_RESET_MV),np.int32(1 if capture_events else 0)))
        comp_end.record(); comp_end.synchronize()
        compute_ms=float(cp.cuda.get_elapsed_time(comp_start,comp_end))
        self.current_tick=start_tick+int(n_ticks)

        # Only compact events, 32 DN counts, and overflow counter are read back.
        d2h_start=cp.cuda.Event(); d2h_end=cp.cuda.Event(); d2h_start.record()
        total=int(cp.asnumpy(self.event_count)[0]) if capture_events else 0
        overflow=max(0,total-self.event_capacity)
        take=min(total,self.event_capacity)
        if capture_events and take:
            ticks=cp.asnumpy(self.event_ticks[:take])
            neurons=cp.asnumpy(self.event_neurons[:take])
            order=np.lexsort((neurons,ticks))
            events_h=np.column_stack((ticks[order],neurons[order])).astype(np.int32,copy=False)
        else:
            events_h=np.empty((0,2),dtype=np.int32)
        dn_counts_h=cp.asnumpy(self.dn_counts)
        d2h_end.record(); d2h_end.synchronize()
        d2h_ms=float(cp.cuda.get_elapsed_time(d2h_start,d2h_end))
        if overflow: raise RuntimeError(f"event buffer overflow {overflow}")
        return {"events":events_h,"dn_counts":dn_counts_h,
                "dn_slots":(dn_counts_h>0).astype(np.int32),
                "compute_ms":compute_ms,"h2d_ms":h2d_ms,"d2h_ms":d2h_ms,
                "total_gpu_events":total}

    def state_to_host(self):
        return {
          "v":cp.asnumpy(self.v),"g":cp.asnumpy(self.g),
          "last_spike_tick":cp.asnumpy(self.last_spike),
          "rfc_ticks":cp.asnumpy(self.rfc_ticks),
          "delay_ring":cp.asnumpy(self.ring),
          "spike_counts":cp.asnumpy(self.spike_counts)
        }

    def state_hashes(self):
        s=self.state_to_host()
        h=hashlib.sha256()
        for a in (s["v"],s["g"],s["last_spike_tick"],s["rfc_ticks"],s["delay_ring"],s["spike_counts"]):
            h.update(str(a.dtype).encode()); h.update(np.asarray(a.shape,dtype=np.int64).tobytes())
            h.update(np.ascontiguousarray(a).tobytes())
        h.update(np.asarray([self.current_tick],dtype=np.int64).tobytes())
        return {"state_digest":h.hexdigest(),
          "final_v_sha256":array_sha(s["v"]),"final_g_sha256":array_sha(s["g"]),
          "last_spike_sha256":array_sha(s["last_spike_tick"]),
          "delay_ring_sha256":array_sha(s["delay_ring"]),
          "spike_count_vector_sha256":array_sha(s["spike_counts"])}

    def memory_profile(self):
        free,total=cp.cuda.runtime.memGetInfo()
        return {"device":self.device_name,"free_bytes":int(free),"total_bytes":int(total),
                "cupy_pool_used_bytes":int(cp.get_default_memory_pool().used_bytes()),
                "cupy_pool_total_bytes":int(cp.get_default_memory_pool().total_bytes())}
