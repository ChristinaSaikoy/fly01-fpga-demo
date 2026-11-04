"""Read actual adopted ledger, replay frozen model/RNG/state/DN/body exactly."""
import argparse,hashlib,json,time
from pathlib import Path
import numpy as np
from neural import C

def replay(folder):
    sim=C.IM.CandidateBInteger(C.preloc,C.postloc,C.weights,C.IM.FORMATS['RECOMMENDED'])
    rng=np.random.default_rng(C.SEED);art=C.SH.FrozenArtifacts()
    pre=C.SH.FrozenPreprocessorV1_0(art);mapper=C.SH.FinalDNMotorMapperV1_0(art)
    bodyrt=art.bodyrt.BodyRuntime(art.body_config);body=art.bodyrt.BodyState.zero()
    expected_k=0;adopted={};groups={};latencies=[];begun=None;ended=None;max_gap=0;last=None
    for line in (Path(folder)/'ledger.jsonl').open(encoding='utf-8'):
        r=json.loads(line)
        if r['kind']=='RUN_START':begun=r
        elif r['kind']=='RUN_END':ended=r
        elif r['kind']=='ADOPTED_INPUT':adopted[r['model_step']]=r
        elif r['kind']=='VALIDATED_RESULT':
            k=r['model_step'];assert k==expected_k and r['dt_s']==.02 and r['model_time_s']==k*.02
            a=adopted.pop(k);assert a['q_applied']==r['q_applied'] and a['noise_local']==r['noise_local']
            full=rng.random(166700)<C.NOISE_P;noise=np.flatnonzero(full[C.nodes]).tolist()
            nh=hashlib.sha256(np.packbits(full[C.nodes].astype(np.uint8),bitorder='little').tobytes()).hexdigest()
            assert noise==r['noise_local'] and nh==r['noise_sha256']
            q=r['q_applied'];assert len(q)==311 and set(q)<={0,2458};assert C.canonical_hash(q)==r['q_sha256']
            assert sorted(int(C.input_local[i]) for i,v in enumerate(q) if v)+[512+i for i in noise]==r['input_events']
            C.apply_qvec(sim,q);fired=sim.step(noise);dn=C.dn_frame(k,fired,'MVP_LEDGER_ORACLE')
            pp=pre.step(dn);drive,mapping=mapper.map(dn,pp,k);body,_,_=bodyrt.step(drive,body)
            assert sim.state.tolist()==r['neural_state'] and list(dn.slots)==r['dn_slots'],('state_or_dn',k)
            assert pp==r['preprocessor'] and mapping==r['mapping'] and C.drive_dict(drive)==r['motor_drive_simulated'] and C.body_dict(body)==r['body_simulated'],('postprocess',k)
            group=r['sampling']['applied']['group'];groups[group]=groups.get(group,0)+1
            received=r['sampling']['applied'].get('received_ns')
            if received is not None:latencies.append((r['validated_ns']-received)/1e6)
            if last:max_gap=max(max_gap,(r['validated_ns']-last)/1e6)
            last=r['validated_ns'];expected_k+=1
    assert begun is not None and ended is not None
    assert not adopted,'Unresolved adopted inputs; not a complete replay acceptance'
    values=sorted(latencies)
    summary=json.loads((Path(folder)/'SUMMARY.json').read_text(encoding='utf-8'))
    assert summary['candidate_sha256']==begun['candidate_sha256']
    assert summary['stats']['model_steps']==expected_k
    return dict(status='EXACT_MATCH',model_steps=expected_k,adopted_groups=groups,
        complete_state_words=471,DN_slots=32,dt_s=.02,candidate_sha256=begun['candidate_sha256'],
        receive_estimate_to_validated_ms=dict(mean=sum(values)/len(values),p99=values[min(len(values)-1,int(len(values)*.99))],maximum=max(values)) if values else None,
        maximum_feedback_gap_ms=max_gap,exposure='UNKNOWN_EXPOSURE',origin=summary['backend'],
        scientific_independence='same frozen implementation, separate state and direct path; not biological validation',
        physical_output=False)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--output',required=True);a=p.parse_args()
    started=time.monotonic();r=replay(a.run);r['replay_wall_s']=time.monotonic()-started
    with Path(a.output).open('x',encoding='utf-8') as f:json.dump(r,f,indent=2);f.write('\n')
    print(json.dumps(r,indent=2))
