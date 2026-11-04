"""Offline contract/chain evidence. Mock results are never hardware measurements."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
from adapter import C, CounterDifferencer, FpgaAdapter, MockNeuralTransport, EdgeFpgaRuntime, Rejected, BackendFault, encode_inputs

def dump(path, value): path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def noise_hash(noise):
    mask=np.zeros(471,dtype=np.uint8);mask[noise]=1
    return hashlib.sha256(np.packbits(mask,bitorder='little').tobytes()).hexdigest()

def protocol_tests():
    tests=[]
    def good(name, value):
        tests.append({'name':name,'PASS':bool(value)});assert value,name
    def bad(name, call):
        try: call()
        except (Rejected,BackendFault): good(name,True)
        else: good(name,False)
    q=[0]*311; ih=C.canonical_hash(q);nh=noise_hash([])
    t=MockNeuralTransport();a=FpgaAdapter(t)
    r=a.transact(1,0,q,[],ih,nh);size=len(t.transactions)
    good('duplicate_exact_cached_no_backend_step',a.transact(1,0,q,[],ih,nh)['cached'] and len(t.transactions)==size)
    for name, g, f, qq, nn, i, n in [
        ('generation',0,1,q,[],ih,nh),('bool_generation',True,1,q,[],ih,nh),
        ('frame_gap',1,3,q,[],ih,nh),('bool_frame',1,True,q,[],ih,nh),
        ('input_hash',1,1,q,[],'0'*64,nh),('noise_hash',1,1,q,[],ih,'0'*64),
        ('Q_unrepresentable',1,1,[1]*311,[],C.canonical_hash([1]*311),nh),
        ('Q_boolean',1,1,[False]*311,[],ih,nh),('Q_shape',1,1,q[:-1],[],ih,nh),
        ('noise_duplicate',1,1,q,[1,1],ih,noise_hash([1])),
        ('noise_order',1,1,q,[3,1],ih,noise_hash([1,3])),
        ('noise_range',1,1,q,[471],ih,nh)]:
        bad(name,lambda g=g,f=f,qq=qq,nn=nn,i=i,n=n:a.transact(g,f,qq,nn,i,n))
    good('all_prevalidation_before_mutation',len(t.transactions)==size and a.frame==1)
    q2=list(q);q2[0]=2458
    bad('conflicting_duplicate',lambda:a.transact(1,0,q2,[],C.canonical_hash(q2),nh))
    a.reset();good('reset_no_extra_step_and_zero_counts',a.frame==0 and a.generation==2 and a.diff.previous==[0]*32 and t.sim.steps==0)
    bad('old_generation_post_reset',lambda:a.transact(1,0,q,[],ih,nh))
    d=CounterDifferencer();d.reset(1);d.previous=[0xffffffff]*32
    good('counter_modulo32_wrap_exact',d.accept(1,0,[0]*32)==[1]*32)
    good('counter_duplicate_cached',d.accept(1,0,[0]*32)==[1]*32 and d.expected==1)
    bad('counter_duplicate_changed',lambda:d.accept(1,0,[1]*32))
    bad('counter_gap',lambda:d.accept(1,2,[1]*32))
    bad('counter_nonbinary',lambda:d.accept(1,1,[2]*32))
    good('counter_reject_does_not_update',d.previous==[0]*32 and d.expected==1)
    for field,value in [('completed_id',7),('generation',99),('input_sha256','0'*64),('noise_sha256','0'*64),
                        ('overflow',1),('drop',1),('error_status',1),('status',326),('cycles',0),('counts',[2]*32),('states',[])]:
        class FaultTransport(MockNeuralTransport):
            def step(self,*args):
                result=super().step(*args);result[field]=value;return result
        ft=FaultTransport();fa=FpgaAdapter(ft)
        bad('fault_'+field,lambda:fa.transact(1,0,q,[],ih,nh))
        good('fault_latches_no_valid_frame_'+field,fa.fault is not None and fa.frame==0)
        count=len(ft.transactions)
        bad('fault_replay_block_'+field,lambda:fa.transact(1,0,q,[],ih,nh))
        good('fault_replay_no_backend_mutation_'+field,len(ft.transactions)==count)
    class TimeoutTransport(MockNeuralTransport):
        def step(self,*args): raise TimeoutError('injected transport timeout')
    fa=FpgaAdapter(TimeoutTransport());bad('timeout_invalid_output',lambda:fa.transact(1,0,q,[],ih,nh))
    good('timeout_latched',fa.fault is not None and fa.frame==0)
    for mode in ('bad_guard','raised_exception'):
        class PartialResetTransport(MockNeuralTransport):
            mode='healthy'
            def reset(self,generation):
                result=super().reset(generation)
                if self.mode=='bad_guard':result['reset_guard_complete']=False
                if self.mode=='raised_exception':raise RuntimeError('injected after partial backend reset')
                return result
        pt=PartialResetTransport();pa=FpgaAdapter(pt)
        pa.transact(1,0,q,[],ih,nh);pt.mode=mode
        bad('partial_reset_fault_'+mode,pa.reset)
        size=len(pt.transactions)
        good('partial_reset_latched_old_generation_'+mode,pa.fault is not None and pa.generation==1 and pa.frame==1)
        bad('partial_reset_no_cached_old_output_'+mode,lambda:pa.transact(1,0,q,[],ih,nh))
        bad('partial_reset_no_next_step_'+mode,lambda:pa.transact(1,1,q,[],ih,nh))
        good('partial_reset_backend_not_called_'+mode,len(pt.transactions)==size)
        pt.mode='healthy';pa.reset()
        good('partial_reset_confirmed_recovery_'+mode,pa.generation==2 and pa.frame==0 and pa.fault is None)
        good('partial_reset_first_legal_frame_'+mode,pa.transact(2,0,q,[],ih,nh)['completed_id']==0)
    # DN order is the frozen roster, never remapped for aesthetic direction.
    good('frozen_DN_slot_order',len(set(C.out_local.tolist()))==32)
    e=encode_inputs([2458]*311,[0,470],C.canonical_hash([2458]*311),noise_hash([0,470]))
    good('stimulus_ascending_then_noise_ascending',e[:311]==sorted(C.input_local.tolist()) and e[311:]==[512,982])
    return tests

def regression(out):
    manifest=json.loads((C.TASK/'GENERATED_CLOSED_LOOP_EVIDENCE_MANIFEST.json').read_text())
    results=[]
    for info in manifest['runs']:
        p=Path(info['trace_path']);assert C.sha(p)==info['trace_sha256']
        expected=[json.loads(x) for x in p.read_text().splitlines()]
        transport=MockNeuralTransport();rt=EdgeFpgaRuntime(FpgaAdapter(transport),info['target'])
        count=0
        with (out/(info['scenario']+'_mock_trace.jsonl')).open('w',encoding='utf-8') as f:
            for k in range(300):
                got=rt.step();f.write(json.dumps(got,separators=(',',':'))+'\n')
                for key,value in expected[k].items():
                    if key=='dn_frame_k':
                        assert got[key]['slots']==value['slots'] and got[key]['slots_sha256']==value['slots_sha256']
                    else: assert got[key]==value,(info['scenario'],k,key)
                assert got['backend_snapshot']['origin']=='MOCK_FPGA_TRANSPORT'
                assert got['backend_snapshot']['neural_state_sha256']==hashlib.sha256(np.asarray(transport.sim.state,dtype='<i8').tobytes()).hexdigest()
                count+=1
        assert got['backend_snapshot']['neural_state_sha256']==info['final_neural_state_sha256']
        results.append({'scenario':info['scenario'],'frames':count,'PASS':True,'origin':'MOCK_FPGA_TRANSPORT',
                        'comparison':'all observable frozen chain fields exact; fired_local_count unavailable in MMIO',
                        'reference_sha256':info['trace_sha256']})
    return results

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    result={'origin':'MOCK_FPGA_TRANSPORT','hardware':'NOT_MEASURED','realtime':'NOT_MEASURED'}
    try:
        result['protocol']=protocol_tests();result['regression']=regression(args.output)
        result['PASS']=True
        print('WORK02_B_MOCK_PASS protocol='+str(len(result['protocol']))+' frames=600')
    except Exception as exc:
        import traceback
        result['PASS']=False;result['error']=repr(exc)
        (args.output/'failure.log').write_text(traceback.format_exc(),encoding='utf-8');raise
    finally: dump(args.output/'RESULT.json',result)
if __name__=='__main__': main()
