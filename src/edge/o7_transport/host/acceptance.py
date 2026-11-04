"""One persistent session: prefix + 5400 exact + 600/200 + 3x1000 + faults.

Called only under launch_actual.py's whole-command 1800s process-tree watchdog.
MOCK deliberately skips board/formal evidence and is never submit-ready.
"""
import argparse,csv,hashlib,json,os,struct,subprocess,sys,time,traceback
from pathlib import Path
from adapter import BIT_SHA,C,FpgaAdapter,MockNeuralTransport,PersistentLabTransport,make_packet
from local_tools import OwnedServer,BIT,vivado_command
from approval_gate import check as approval_check
from run_candidate import audit,modes_equivalent,live,bounded_fault_checks,source_identity,dump
ROOT=Path(__file__).resolve().parent.parent

def paired_benchmark(adapter,out):
    # Archived identical input replay, not new live feedback or a controlled A/B.
    baseline=Path('D:/FPGA-AUTO/tasks/WORK-03/o6_realtime/host/runs/actual_20261013T200945/evidence')
    import importlib.util
    spec=importlib.util.spec_from_file_location('accepted_o6_wire_decoder',ROOT.parent.parent/'WORK-03/o6_realtime/verify_actual.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    old_packets,_=module.raw_packets(baseline/'transactions.csv')
    old_rows=[json.loads(x) for x in (baseline/'LEFT_audit.jsonl').open(encoding='utf-8')]
    trace_sha=hashlib.sha256((baseline/'LEFT_audit.jsonl').read_bytes()).hexdigest()
    adapter.reset();records=[]
    origin='ACTUAL_FPGA_TRANSPORT_REPLAY_NOT_DYNAMIC_LOOP' if adapter.transport.origin.startswith('FPGA_') else 'MOCK_TRANSPORT_REPLAY_NOT_HARDWARE'
    with (out/'PAIRED_TRANSPORT_BENCHMARK.jsonl').open('x',encoding='utf-8') as log:
        for k,row in enumerate(old_rows):
            original=row['backend_snapshot'];events=old_packets[(original['hardware_generation'],k)]['events']
            started=time.perf_counter();got=adapter.transport._call(['FORMAL',adapter.generation,k,1,1,*events])
            assert got['states']==original['states'] and got['counts']==original['counts']
            assert all(got[key]==original[key] for key in ('acc_sat','state_sat','overflow','drop','cycles'))
            record={'frame':k,'events':events,'snapshot':got,'origin':origin,
                    'whole_replay_call_ms':1000*(time.perf_counter()-started),'old_snapshot':original,
                    'baseline_trace_sha256':trace_sha}
            log.write(json.dumps(record,separators=(',',':'))+'\n');log.flush();records.append(record)
    assert len(records)==300
    value={'status':'PASS','frames':300,'input_noise_schedule':'IDENTICAL_ARCHIVED_O6_LEFT_AUDIT',
           'limitation':'Different bits and historical host load, O7 reads530 vs O6 528; not controlled simultaneous A/B, not pure encoding causal proof',
           'evidence':'PAIRED_TRANSPORT_BENCHMARK.jsonl','does_not_replace_live_trials':True}
    dump(out/'PAIRED_TRANSPORT_BENCHMARK.json',value);return value

def codec_faults(adapter,out):
    checked=[]
    for kind in ('PAD','FLAGS','DUPLICATE','NODE','LEGACY','CRC','HALF'):
        adapter.reset();reply=adapter.transport._call(['CODEC_FAULT',kind])
        assert reply['PASS'] and reply['accepted_events']==0 and reply['snapshot_valid']==0
        assert reply['generation']==adapter.generation and reply['hardware_generation']==adapter.hardware_generation
        checked.append(reply)
    adapter.reset()  # Explicitly clears a decoded half packet/fault, preserves guard.
    dump(out/'CODEC_FAULTS.json',{'status':'PASS','origin':'ACTUAL_FPGA','checks':checked});return checked

def formal(adapter,out):
    inputs=ROOT/'formal_inputs';manifest=json.loads((inputs/'INPUT_IDENTITY.json').read_text(encoding='utf-8'))
    for name,digest in manifest.items():
        with (inputs/name).open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==digest,name
    completed=0;formal_count=0;prefix_times=[]
    matrix=[('PREFIX1',0,'single'),('PREFIX20',0,'sequence20')]+[('FORMAL',rep,'formal') for rep in range(1,4)]
    started=time.perf_counter()
    with (out/'formal_capture.jsonl').open('x',encoding='utf-8') as log:
        for scope,rep,name in matrix:
            expected=iter(csv.reader((inputs/(name+'_expected.csv')).open(encoding='utf-8')))
            seed=condition=None
            for row in csv.reader((inputs/(name+'_plan.csv')).open(encoding='utf-8')):
                if row[0]=='CASE':
                    seed,condition=map(int,row[1:3]);adapter.reset();continue
                assert row[0]=='STEP' and seed is not None
                frame,enable,count=map(int,row[1:4]);events=[int(x,16) for x in row[4:]];assert count==len(events)
                frame_start=time.perf_counter()
                got=adapter.transport._call(['FORMAL',adapter.generation,frame,enable,1,*events])
                golden=next(expected)
                actual=['STEP',str(seed),str(condition),str(frame),str(got['completed_id'])]
                actual += [str(got[key]) for key in ('acc_sat','state_sat','overflow','drop','cycles')]
                actual += [f'{int(x)&0xffffffff:08X}' for x in got['states']+got['counts']]
                assert len(actual)==len(golden)==513
                assert 0<got['cycles']<=500000
                for index,(a,b) in enumerate(zip(actual,golden)):
                    if index!=9 and a.upper()!=b.upper():raise RuntimeError(f'FORMAL_FIRST_DIVERGENCE {scope}/{rep}/{seed}/{condition}/{frame}/col{index}')
                checksum=make_packet(got['hardware_generation'],frame,events,enable)[7]
                assert got['accepted_request_crc32']==checksum and got['accepted_events']==count
                record={'scope':scope,'repeat':rep,'seed':seed,'condition':condition,'frame':frame,
                    'generation':adapter.generation,'events':events,'dn_enable':enable,'snapshot':got,
                    'origin':'ACTUAL_FPGA','expected_source_sha256':manifest[name+'_expected.csv']}
                log.write(json.dumps(record,separators=(',',':'))+'\n');log.flush()
                wall=time.perf_counter()-frame_start
                completed+=1
                if scope=='FORMAL':formal_count+=1
                else:prefix_times.append(wall)
            assert next(expected,None) is None
            if scope=='PREFIX20':
                # Conservative engineering admission, not a 30-minute proof.
                # Extra packet calls/core work margin protects varying formal inputs.
                upper_full=max(prefix_times)+.012
                forecast=1.15*(upper_full*6550+95)+90
                dump(out/'SHORT_ADMISSION.json',{'origin':'PREFIX_TIMING_DESIGN_ESTIMATE','samples':21,
                    'forecast_whole_seconds':forecast,'gate_seconds':1500,'not_actual_whole_run_PASS':True})
                if forecast>1500:raise RuntimeError('SHORT_FORECAST_OVER_BUDGET_OPTIMIZE_FIRST')
    assert completed==5421 and formal_count==5400
    value={'origin':'ACTUAL_FPGA','exact':'PASS','prefix_steps':21,'formal_steps':5400,'all_steps':completed,
        'wall_seconds':time.perf_counter()-started,'full_state_words':471,'view_words':530,
        'raw_capture':'formal_capture.jsonl','input_identity':manifest}
    dump(out/'FORMAL_RESULT.json',value)
    return value

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--backend',choices=['mock','fpga'],required=True)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--approval',type=Path,default=ROOT/'PROGRAMMING_APPROVAL.json')
    a=ap.parse_args()
    # Gate first: no server/board touched when unapproved.
    ready=approval_check(a.approval) if a.backend=='fpga' else None
    a.output.mkdir(parents=True,exist_ok=False)
    t=server=None;start=time.perf_counter();result={'status':'PARTIAL_WITH_BLOCKERS','backend':a.backend,
        'source_identity':source_identity(),'hardware_50Hz':'NOT_ESTABLISHED','controller_acceptance':'PENDING'}
    dump(a.output/'SOURCE_IDENTITY.json',result['source_identity'])
    try:
        if a.backend=='fpga':
            server=OwnedServer(a.output);tx=a.output/'transactions.csv'
            command=vivado_command(Path(__file__).with_name('persistent_o7.tcl'),a.output,
                ['210512180081','localhost:3121',tx,BIT,BIT_SHA,a.approval])
            dump(a.output/'TRANSPORT_COMMAND.json',command)
            t=PersistentLabTransport(command,a.output/'native_raw.log',timeout=120)
            h=t.handshake
            assert h['bit_sha256']==BIT_SHA and h['interface_version']=='F1070001' and h['serial']=='210512180081' and h['startup_verified']
            receipt={'programming_status':'PASS','bitstream_sha256':BIT_SHA,'serial':'210512180081',
                'origin':'ACTUAL_FPGA','handshake':h,'authority':str(a.approval)}
            dump(a.output/'CURRENT_LOAD_RECEIPT.json',receipt)
            result['warmup']=t._call(['WARM'])
            adapter=FpgaAdapter(t,loaded_sha=BIT_SHA,load_receipt=a.output/'CURRENT_LOAD_RECEIPT.json',hardware_verified=True)
            result['formal']=formal(adapter,a.output)
            result['paired_benchmark']=paired_benchmark(adapter,a.output)
            adapter.reset()
        else:
            t=MockNeuralTransport();adapter=FpgaAdapter(t)
            result['formal']={'status':'NOT_RUN_IN_MOCK_MODE','not_hardware_evidence':True}
        result['audit']=audit(adapter,a.output)
        result['modes']=modes_equivalent(adapter,a.output)
        result['online_rounds']=[]
        for trial in range(1,4):
            output=a.output/f'online_round_{trial}';output.mkdir()
            perf=live(adapter,output,frames=1000)  # reset neural/RNG/generation before each epoch
            result['online_rounds'].append(perf)
        if a.backend=='fpga':
            result['codec_faults']=codec_faults(adapter,a.output)
            result['faults']=bounded_fault_checks(adapter,a.output)
        result['functional']='PASS'
        result['hardware_50Hz']=('PASS' if all(p['candidate_observed_50Hz_PASS'] for p in result['online_rounds']) else 'FAIL') if a.backend=='fpga' else 'NOT_ESTABLISHED_MOCK'
        result['status']='SUBMITTED_FOR_REVIEW' if a.backend=='fpga' else 'MOCK_ONLY_NOT_SUBMITTABLE'
        result['PASS']=True
    except Exception as exc:
        result['PASS']=False;result['error']=repr(exc)
        (a.output/'failure.log').write_text(traceback.format_exc(),encoding='utf-8')
        raise
    finally:
        if t is not None:t.close()
        if server is not None:server.close()
        result['source_unchanged_during_run']=source_identity()==result['source_identity']
        if not result['source_unchanged_during_run']:result['PASS']=False;result['status']='PARTIAL_WITH_BLOCKERS'
        # Final evidence flush is part of the single command; no async hidden writes.
        for p in a.output.rglob('*'):
            if p.is_file():
                with p.open('r+b') as f:os.fsync(f.fileno())
        result['whole_command_seconds']=time.perf_counter()-start
        result['within_30min']=result['whole_command_seconds']<=1800
        if not result['within_30min']:result['PASS']=False;result['status']='PARTIAL_WITH_BLOCKERS'
        dump(a.output/'RESULT.json',result)
        print(json.dumps({'status':result['status'],'hardware_50Hz':result['hardware_50Hz'],
            'whole_command_seconds':result['whole_command_seconds']}),flush=True)
if __name__=='__main__':main()
