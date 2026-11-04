"""Original 1+20 complete-state plans; no device is opened by this module."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import time
from identity import FORMAL_ROOT

HISTORY='07e20c8cf006d37bf7376a272461e72a5655d1db/docs/controller/2026-10-21/README.md'


def check_inputs(inputs=None):
    inputs=Path(inputs) if inputs is not None else FORMAL_ROOT/'formal_inputs'
    identities=json.loads((inputs/'INPUT_IDENTITY.json').read_text(encoding='utf-8'))
    selected=[f'{name}_{kind}.csv' for name in ('single','sequence20') for kind in ('plan','expected')]
    for name in selected:
        if hashlib.sha256((inputs/name).read_bytes()).hexdigest()!=identities[name]:
            raise RuntimeError('formal input identity '+name)
    return inputs


def run_short(adapter,output,*,origin,inputs=None):
    if origin not in ('ACTUAL_FPGA_UART','SOFTWARE_FIXTURE_NOT_HARDWARE'):
        raise ValueError('Explicit evidence origin required')
    inputs=check_inputs(inputs);output=Path(output)
    completed=0;started=time.monotonic()
    with (output/'formal_capture.jsonl').open('x',encoding='utf-8') as log:
        for scope,repeat,name in [('PREFIX1',0,'single'),('PREFIX20',0,'sequence20')]:
            with (inputs/(name+'_expected.csv')).open(encoding='utf-8') as exp_file, (inputs/(name+'_plan.csv')).open(encoding='utf-8') as plan_file:
                expected=iter(csv.reader(exp_file));seed=condition=None
                for row in csv.reader(plan_file):
                    if row[0]=='CASE':
                        seed,condition=map(int,row[1:3]);adapter.reset();continue
                    if row[0]!='STEP' or seed is None:raise RuntimeError('formal plan syntax')
                    frame,enable,count=map(int,row[1:4]);events=[int(x,16) for x in row[4:]]
                    if len(events)!=count:raise RuntimeError('formal plan count')
                    got=adapter.transport.formal(adapter.generation,frame,events,enable,True)
                    golden=next(expected)
                    actual=['STEP',str(seed),str(condition),str(frame),str(got['completed_id'])]
                    actual += [str(got[key]) for key in ('acc_sat','state_sat','overflow','drop','cycles')]
                    actual += [f'{int(value)&0xFFFFFFFF:08X}' for value in got['states']+got['counts']]
                    if len(actual)!=513 or len(golden)!=513:raise RuntimeError('formal complete read count')
                    for index,(a,b) in enumerate(zip(actual,golden)):
                        # Same accepted comparison: cycles are measured, never required to equal simulation.
                        if index!=9 and a.upper()!=b.upper():
                            raise RuntimeError(f'FIRST_DIVERGENCE {scope}/{repeat}/{seed}/{condition}/{frame}/{index}')
                    log.write(json.dumps(dict(scope=scope,repeat=repeat,seed=seed,condition=condition,frame=frame,dn_enable=enable,events=events,snapshot=got),separators=(',',':'))+'\n')
                    log.flush();completed+=1
                if next(expected,None) is not None:raise RuntimeError('formal missing expected rows')
    if completed!=21:raise RuntimeError('formal frame coverage')
    result=dict(origin=origin,status='PASS',mode='TARGETED_INTERACTION_CONTINUATION',prefix_steps=21,
        formal_steps=0,formal_regression='NOT_RUN_THIS_SUITE',prior_regression='PRIOR_EVIDENCE_ACCEPTED',
        prior_evidence=HISTORY,full_words=530,steps=completed,wall_seconds=time.monotonic()-started)
    with (output/'FORMAL_RESULT.json').open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true',required=True);parser.parse_args()
    check_inputs();print(json.dumps(dict(status='SHORT_INPUTS_PASS',steps=21,hardware='NONE')))
