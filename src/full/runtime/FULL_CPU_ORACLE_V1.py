"""FULL_CPU_ORACLE_V1
Frozen float64 CPU correctness oracle for FLY-01 FULL-1.
Semantics reproduce philshiu/Drosophila_brain_model Brian2 2.5.1 scheduling.
Not a performance runtime.
"""
from dataclasses import dataclass
import math
import numpy as np

@dataclass(frozen=True)
class LifParams:
    dt_ms: float = 0.1
    v_rest_mV: float = -52.0
    v_reset_mV: float = -52.0
    v_threshold_mV: float = -45.0
    tau_membrane_ms: float = 20.0
    tau_synaptic_ms: float = 5.0
    refractory_ms: float = 2.2
    synaptic_delay_ms: float = 1.8
    w_syn_mV: float = 0.275
    f_poi: float = 250.0
    @property
    def w_ext_mV(self):
        return self.w_syn_mV*self.f_poi
    @property
    def refractory_ticks(self):
        return round(self.refractory_ms/self.dt_ms)
    @property
    def delay_ticks(self):
        return round(self.synaptic_delay_ms/self.dt_ms)

P=LifParams()

def coefficients(p=P):
    dt=p.dt_ms; tm=p.tau_membrane_ms; ts=p.tau_synaptic_ms
    decay_v=math.exp(-dt/tm)
    decay_g=math.exp(-dt/ts)
    v0_term=p.v_rest_mV-p.v_rest_mV*math.exp(-dt/tm)
    couple_g=((ts/(tm-ts))*(-math.exp(dt/tm)+math.exp(dt/ts))
              *math.exp(-dt/tm)*math.exp(-dt/ts))
    return decay_v,decay_g,v0_term,couple_g

def run(row_ptr,dst,signed_contact_count,n_ticks,initial_v_mV=None,initial_g_mV=None,
        external_events=None,rfc_ms=None,record_events=True,p=P):
    row_ptr=np.asarray(row_ptr,dtype=np.int64)
    dst=np.asarray(dst,dtype=np.int64)
    cnt=np.asarray(signed_contact_count,dtype=np.int64)
    n=len(row_ptr)-1
    if row_ptr[0]!=0 or row_ptr[-1]!=len(dst) or len(dst)!=len(cnt):
        raise ValueError("invalid CSR")
    src=np.repeat(np.arange(n,dtype=np.int64),np.diff(row_ptr))
    v=np.full(n,p.v_rest_mV,dtype=np.float64) if initial_v_mV is None else np.asarray(initial_v_mV,dtype=np.float64).copy()
    g=np.zeros(n,dtype=np.float64) if initial_g_mV is None else np.asarray(initial_g_mV,dtype=np.float64).copy()
    if rfc_ms is None:
        rfc_ticks=np.full(n,p.refractory_ticks,dtype=np.int64)
    else:
        rfc_ticks=np.rint(np.asarray(rfc_ms,dtype=np.float64)/p.dt_ms).astype(np.int64)
    last_spike=np.full(n,-10**12,dtype=np.int64)
    ring=np.zeros((p.delay_ticks,n),dtype=bool)
    spike_counts=np.zeros(n,dtype=np.int64)
    events=[]
    ext={}
    if external_events:
        for t,i,c in external_events:
            ext.setdefault(int(t),[]).append((int(i),int(c)))
    A,B,V0T,C=coefficients(p)

    for t in range(int(n_ticks)):
        # Brian2 schedule: groups/stateupdate
        not_ref=(t-last_spike)>=rfc_ticks
        v_upd=V0T+(g*C+v*A)
        g_upd=g*B
        v=np.where(not_ref,v_upd,v)
        g=np.where(not_ref,g_upd,g)

        # thresholds
        spike=not_ref & (v>p.v_threshold_mV)

        # synapses; the ring emits spikes exactly delay_ticks later
        slot=t%p.delay_ticks
        delayed=ring[slot]
        contrib=np.zeros(n,dtype=np.int64)
        active=delayed[src]
        if active.any():
            np.add.at(contrib,dst[active],cnt[active])
        # g has "unless refractory": writes during refractory are dropped
        g += np.where(not_ref,contrib.astype(np.float64)*p.w_syn_mV,0.0)

        # deterministic equivalent of upstream PoissonInput target_var='v'
        # PoissonInput is scheduled in the synapses slot after threshold.
        for i,c in ext.get(t,()):
            if not_ref[i]:
                v[i]+=float(c)*p.w_ext_mV

        # resets
        if spike.any():
            fired=np.flatnonzero(spike)
            v[fired]=p.v_reset_mV
            g[fired]=0.0
            last_spike[fired]=t
            spike_counts[fired]+=1
            if record_events:
                events.extend((t,int(i)) for i in fired)
        ring[slot]=spike

    return {
        "spike_counts":spike_counts,
        "events":np.asarray(events,dtype=np.int64).reshape((-1,2)) if events else np.zeros((0,2),dtype=np.int64),
        "v_mV":v,
        "g_mV":g,
        "last_spike_tick":last_spike
    }
