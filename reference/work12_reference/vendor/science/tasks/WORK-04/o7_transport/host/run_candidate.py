"""Runnable hardware/mock audit + persistent online candidate.

Hardware mode requires an actual approved load receipt and existing own loopback
hw_server. This runner never programs, starts a server, or silently falls back.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np
from adapter import C, BIT_SHA, reference, FpgaAdapter, MockNeuralTransport, PersistentLabTransport, EdgeFpgaRuntime, Rejected
from local_tools import BIT,OwnedServer,vivado_command

def dump(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def source_identity():
    directory=Path(__file__).resolve().parent
    result={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file() and p.suffix in ('.py','.tcl')}
    result['../codec/packed10.py']=hashlib.sha256((directory.parent/'codec/packed10.py').read_bytes()).hexdigest()
    return result
def audit(adapter,out):
    result=[]
    for name in ('LEFT','RIGHT'):
        if adapter.frame:adapter.reset()
        target=C.MF['scenarios'][name]['target_position_world_m']
        rt=EdgeFpgaRuntime(adapter,target,audit=True)
        sw=reference.LiveRuntime(target)
        with (out/f'{name}_audit.jsonl').open('w',encoding='utf-8') as log:
            for k in range(300):
                got=rt.step();expected=sw.step();snap=got['backend_snapshot']
                if snap['states']!=sw.sim.state.tolist():raise RuntimeError(f'{name} frame{k}: state exact FAIL')
                if snap['acc_sat']!=int(sw.sim.acc_saturation_count) or snap['state_sat']!=int(sw.sim.state_saturation_count):
                    raise RuntimeError(f'{name} frame{k}: saturation exact FAIL')
                for key,value in expected.items():
                    if key=='candidate':continue
                    if key=='dn_frame_k':
                        if got[key]['slots']!=value['slots'] or got[key]['slots_sha256']!=value['slots_sha256']:
                            raise RuntimeError(f'{name} frame{k}: DN exact FAIL')
                    elif got[key]!=value:raise RuntimeError(f'{name} frame{k}: {key} exact FAIL')
                log.write(json.dumps(got,separators=(',',':'),allow_nan=False)+'\n');log.flush()
        result.append({'scenario':name,'frames':300,'PASS':True,'origin':adapter.origin,
                       'comparison':'state/DN/saturation and all observable causal fields exact; full spikes unavailable in hardware'})
    return result

def live(adapter,out,frames=1000):
    adapter.reset();rt=EdgeFpgaRuntime(adapter,audit=False)
    lock=threading.RLock();failure=[];finished=threading.Event();requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def answer(self,code,obj):
            b=json.dumps(obj,allow_nan=False).encode()
            try:
                self.send_response(code);self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        def do_GET(self):
            if self.path!='/status':return self.answer(404,{'error':'unknown read-only route'})
            with lock:s={'generation':rt.generation,'frame':rt.frame_id,'finished':finished.is_set(),'failure':failure}
            self.answer(200,s)
        def do_POST(self):
            start=time.perf_counter()
            try:
                if self.path!='/target':raise Rejected('unknown control route')
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=4096:raise Rejected('invalid request size')
                obj=json.loads(self.rfile.read(length),parse_constant=lambda x:(_ for _ in ()).throw(Rejected('nonfinite JSON')))
                with lock:
                    if finished.is_set() or failure:raise Rejected('clock stopped')
                    reply=rt.update(obj)
                    requests.append({'request':obj,'receipt':reply,'server_processing_ms':(time.perf_counter()-start)*1000})
                self.answer(200,reply)
            except (ValueError,TypeError) as exc:self.answer(409,{'error':str(exc)})
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    server_thread=threading.Thread(target=server.serve_forever,daemon=False);server_thread.start()
    client_log=(out/'client.log').open('w',encoding='utf-8')
    client=subprocess.Popen([sys.executable,'-B',str(Path(__file__).with_name('new_target_client.py')),
        '--url',f'http://127.0.0.1:{server.server_address[1]}','--output',str(out/'independent_client_requests.json')],stdout=client_log,stderr=subprocess.STDOUT)
    timings=[];trace=[];epoch=time.perf_counter()
    try:
        with (out/'online_trace.jsonl').open('w',encoding='utf-8') as log:
            for k in range(frames):
                scheduled=epoch+k*C.DT;deadline=scheduled+C.DT
                time.sleep(max(0,scheduled-time.perf_counter()))
                with lock:
                    start=time.perf_counter();row=rt.step()
                # Control service may acquire the state lock between model frames.
                log_start=time.perf_counter()
                log.write(json.dumps(row,separators=(',',':'),allow_nan=False)+'\n');log.flush()
                end=time.perf_counter()
                timing={'frame':k,'frame_total_ms':(end-start)*1000,'evidence_write_ms':(end-log_start)*1000,
                        'start_perf_counter':start,'scheduled_perf_counter':scheduled,'deadline_perf_counter':deadline,
                        'publication_perf_counter':end,
                        'deadline_miss':end>deadline,'start_lag_ms':max(0,(start-scheduled)*1000),
                        'completion_lateness_ms':max(0,(end-deadline)*1000), 'input_age_ms':(end-start)*1000,
                        'input_age_scope':'host frame start to result publication; synthetic target, not camera age',
                        'drop':row['backend_snapshot']['drop'],'stage_timings_ms':row['timings_ms'],
                        'MMIO_stage_timings_ms':row['backend_snapshot']['timings_ms']}
                timings.append(timing);trace.append(row)
        finished.set();client.wait(timeout=130)
        if client.returncode:raise RuntimeError('independent client failed, see client.log')
        sent=json.loads((out/'independent_client_requests.json').read_text())
        effects=[]
        for i,entry in enumerate(sent):
            k0=entry['receipt']['effective_frame'];assert 0<=k0<frames-1
            assert trace[k0]['world_state_k']['objects'][0]['position_xyz_world_m']==entry['request']['position_xyz_world_m']
            assert trace[k0+1]['source_drive_k']['q_vector_sha256']==trace[k0]['source_drive_k_plus_1']['q_vector_sha256']
            sw=reference.LiveRuntime();schedule={e['receipt']['effective_frame']:e['request']['position_xyz_world_m'] for e in sent[:i]}
            first={key:None for key in ('dn_frame_k','motor_drive_k','body_state_k_plus_1')}
            for k in range(min(frames,k0+200)):
                if k in schedule:sw.target=tuple(schedule[k])
                expected=sw.step()
                if k>k0:
                    for key in first:
                        actual=trace[k][key];counter=expected[key]
                        if key=='dn_frame_k':actual=actual['slots'];counter=counter['slots']
                        if first[key] is None and actual!=counter:first[key]=k
            effects.append({'request_seq':i,'effective_frame':k0,'counterfactual_origin':'SOFTWARE_REFERENCE',
                            'actual_origin':adapter.origin,'first_difference':first,'PASS':all(v is not None for v in first.values())})
        assert all(x['PASS'] for x in effects)
        assert [r['tick'] for r in trace]==list(range(frames))
        assert all(trace[k]['body_state_k']==trace[k-1]['body_state_k_plus_1'] for k in range(1,frames))
        a=np.array([x['frame_total_ms'] for x in timings])
        performance={'origin':adapter.origin,'samples':len(a),'mean_ms':float(a.mean()),'P50_ms':float(np.percentile(a,50)),'P95_ms':float(np.percentile(a,95)),
                     'P99_ms':float(np.percentile(a,99)),'max_ms':float(a.max()),'deadline_misses':sum(x['deadline_miss'] for x in timings),
                     'max_lag_ms':max(x['start_lag_ms'] for x in timings),'final_lag_ms':timings[-1]['completion_lateness_ms'],'drop':sum(x['drop'] for x in timings),
                     'candidate_observed_50Hz_PASS':float(np.percentile(a,99))<=20 and not any(x['deadline_miss'] for x in timings),
                     'latency_scope':'encoding/RNG + all transport + mapping/body + synchronous evidence flush; no async log hiding',
                     'frame_count':frames,'two_new_targets':effects,'model_clock_wall_s':end-epoch,
                     'clock_plus_counterfactual_analysis_wall_s':time.perf_counter()-epoch,
                     'hardware_claim':adapter.origin.startswith('FPGA_') or adapter.origin=='EDGE_FPGA_LIVE'}
        dump(out/'PERFORMANCE.json',performance)
        return performance
    except Exception as exc:
        failure.append(repr(exc));raise
    finally:
        finished.set();server.shutdown();server.server_close();server_thread.join(timeout=10)
        if client.poll() is None:client.terminate();client.wait(timeout=10)
        client_log.close();dump(out/'TIMINGS.json',timings);dump(out/'CONTROL_REQUESTS.json',requests)
        dump(out/'CLEANUP.json',{'HTTP_worker_alive':server_thread.is_alive(),'client_exit':client.returncode,
                               'server_address':list(server.server_address),'failure':failure})

def modes_equivalent(adapter,out):
    results=[]
    for name in ('LEFT','RIGHT'):
        adapter.reset();rt=EdgeFpgaRuntime(adapter,C.MF['scenarios'][name]['target_position_world_m'],audit=False)
        with (out/f'{name}_audit.jsonl').open() as baseline,(out/f'{name}_minimal_equivalence.jsonl').open('x') as log:
            for k in range(100):
                full=json.loads(next(baseline));minimal=rt.step()
                for key in ('source_drive_k','source_drive_k_plus_1','external_noise','dn_frame_k','motor_drive_k','body_state_k','body_state_k_plus_1','preprocessor','mapping','world_state_k','feedback_frame_k'):
                    assert minimal[key]==full[key],(name,k,key)
                for key in ('completed_id','input_sha256','noise_sha256','counts','acc_sat','state_sat','overflow','drop','cycles','status','error_status'):
                    assert minimal['backend_snapshot'][key]==full['backend_snapshot'][key],(name,k,key)
                log.write(json.dumps(minimal,separators=(',',':'))+'\n');log.flush()
        results.append({'scenario':name,'frames':100,'PASS':True,'origin':adapter.origin})
    return results

def bounded_fault_checks(adapter,out):
    from adapter import BackendFault
    checks=[];adapter.reset();q=[0]*311;ih=C.canonical_hash(q)
    mask=np.zeros(471,dtype=np.uint8);nh=hashlib.sha256(np.packbits(mask,bitorder='little').tobytes()).hexdigest()
    for label,call in [('bad_q',lambda:adapter.transact(adapter.generation,0,[1]*311,[],ih,nh)),
                       ('wrong_generation',lambda:adapter.transact(adapter.generation-1,0,q,[],ih,nh)),
                       ('bad_noise_order',lambda:adapter.transact(adapter.generation,0,q,[2,1],ih,nh)),
                       ('wrong_input_hash',lambda:adapter.transact(adapter.generation,0,q,[],'0'*64,nh))]:
        try:call()
        except Rejected:checks.append({'name':label,'PASS':True,'frame_unchanged':adapter.frame==0})
        else:raise RuntimeError('ERROR_INPUT_ACCEPTED '+label)
    first=adapter.transact(adapter.generation,0,q,[],ih,nh,False)
    assert adapter.transact(adapter.generation,0,q,[],ih,nh,False)['cached']
    checks.append({'name':'same_input_retry_cached','PASS':adapter.frame==1})
    adapter.reset();assert adapter.frame==0 and adapter.diff.previous==[0]*32
    recovered=adapter.transact(adapter.generation,0,q,[],ih,nh,False)
    assert first['counts']==recovered['counts'] and first['slots']==recovered['slots']
    checks.append({'name':'physical_reset_recovery','PASS':True})
    adapter.transport.abort()
    try:adapter.transact(adapter.generation,1,q,[],ih,nh,False)
    except BackendFault:checks.append({'name':'owned_connection_failure_stops_output','PASS':adapter.frame==1 and adapter.fault is not None})
    else:raise RuntimeError('OUTPUT_PUBLISHED_AFTER_CONNECTION_LOSS')
    dump(out/'FAULT_CHECKS.json',{'origin':adapter.origin,'checks':checks,'PASS':all(x['PASS'] for x in checks)})
    return checks

def main():
    raise RuntimeError('O5 entry disabled in WORK-03; use acceptance.py with exact O6 programming approval')
    ap=argparse.ArgumentParser();ap.add_argument('--backend',choices=['mock','fpga'],required=True)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--load-receipt',type=Path)
    ap.add_argument('--serial',default='210512180081');ap.add_argument('--remote-script',default='/home/roland/fly01-o5-live-20261013/persistent_o5.tcl')
    ap.add_argument('--mode',choices=['audit','online','all'],default='all');a=ap.parse_args()
    if a.backend=='fpga':
        if not a.serial or any(ch not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for ch in a.serial):
            ap.error('invalid hardware serial')
        if not a.load_receipt:ap.error('exact-artifact approved load receipt required; no fallback')
        r=json.loads(a.load_receipt.read_text(encoding='utf-8'))
        if r.get('programming_status')!='PASS' or r.get('bitstream_sha256')!=BIT_SHA or r.get('serial')!=a.serial:
            ap.error('load receipt identity mismatch; no fallback')
        if not a.remote_script.startswith('/home/roland/') or any(ch not in '/._-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789' for ch in a.remote_script):
            ap.error('remote script path must be scoped safe ASCII')
    a.output.mkdir(parents=True,exist_ok=False);t=None;remote_log=None;server=None;started=time.perf_counter()
    result={'status':'PARTIAL_WITH_BLOCKERS','backend':a.backend}
    result['source_identity']=source_identity()
    dump(a.output/'SOURCE_IDENTITY.json',result['source_identity'])
    try:
        if a.backend=='mock':t=MockNeuralTransport()
        else:
            if hashlib.sha256(BIT.read_bytes()).hexdigest()!=BIT_SHA:raise RuntimeError('EXACT_BIT_HASH_REQUIRED')
            server=OwnedServer(a.output)
            txpath=a.output/'remote_transactions.csv'  # identical reviewer schema, physically LOCAL
            command=vivado_command(Path(__file__).with_name('persistent_o5.tcl'),a.output,
                [a.serial,'localhost:3121',txpath,BIT,BIT_SHA])
            dump(a.output/'TRANSPORT_COMMAND.json',command)
            t=PersistentLabTransport(command,a.output/'remote_raw.log',timeout=120)
            h=t.handshake
            if h.get('bit_sha256')!=BIT_SHA or h.get('programming_status')!='PASS' or h.get('serial')!=a.serial or h.get('interface_version')!='F1050002' or not h.get('startup_verified'):
                raise RuntimeError('CURRENT_SESSION_LOAD_IDENTITY_MISMATCH')
            current={'bitstream_sha256':BIT_SHA,'programming_status':'PASS','serial':a.serial,
                     'current_handshake':h,'authority_receipt':str(a.load_receipt),'evidence_origin':'ACTUAL_FPGA'}
            result['execution_host']='Christina Windows; local JTAG, local scientific host, no SSH'
            dump(a.output/'CURRENT_LOAD_RECEIPT.json',current);a.load_receipt=a.output/'CURRENT_LOAD_RECEIPT.json'
        adapter=FpgaAdapter(t,loaded_sha=BIT_SHA if a.backend=='fpga' else None,load_receipt=a.load_receipt,
                            a_accepted=a.backend=='fpga',hardware_verified=a.backend=='fpga')
        result['origin']=adapter.origin
        if a.mode in ('audit','all'):
            result['audit']=audit(adapter,a.output)
            result['mode_equivalence']=modes_equivalent(adapter,a.output)
        if a.mode in ('online','all'):result['online']=live(adapter,a.output)
        if a.backend=='fpga':result['bounded_fault_checks']=bounded_fault_checks(adapter,a.output)
        result['status']='SUBMITTED_FOR_REVIEW';result['PASS']=True
        print('WORK02_B_CANDIDATE_PASS origin='+adapter.origin)
    except Exception as exc:
        import traceback
        result['PASS']=False;result['error']=repr(exc);(a.output/'failure.log').write_text(traceback.format_exc(),encoding='utf-8');raise
    finally:
        if t is not None:t.close()
        if server is not None:server.close()
        if a.backend=='fpga' and (a.output/'remote_transactions.csv.load.txt').exists():
            import shutil
            shutil.copy2(a.output/'remote_transactions.csv.load.txt',a.output/'native_load_receipt.txt')
        if remote_log is not None:
            # Preserve the complete local AXI log even after a fault; no remote deletion.
            command=['D:\\Git\\usr\\bin\\scp.exe','-F','C:\\Users\\54263\\.ssh\\config','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
                     'panasonic:'+remote_log,str(a.output/'remote_transactions.csv')]
            try:
                with (a.output/'transaction_log_fetch.log').open('w',encoding='utf-8') as log:
                    fetched=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=120)
                result['remote_transaction_log']={'path':remote_log,'local':str(a.output/'remote_transactions.csv'),'fetch_exit':fetched.returncode}
                if fetched.returncode:result['status']='PARTIAL_WITH_BLOCKERS';result['evidence_fetch_blocked']=True
                for remote_suffix,local_name in [(remote_log+'.load.txt','native_load_receipt.txt'),
                      (remote_log.rsplit('.',1)[0]+'.server.log','owned_server.log')]:
                    subprocess.run(['D:/Git/usr/bin/scp.exe','-F','C:/Users/54263/.ssh/config',
                        '-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','panasonic:'+remote_suffix,
                        str(a.output/local_name)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=120,check=True)
            except Exception as exc:
                result['status']='PARTIAL_WITH_BLOCKERS';result['evidence_fetch_error']=repr(exc)
        result['source_unchanged_during_run']=source_identity()==result['source_identity']
        if not result['source_unchanged_during_run']:
            result['status']='PARTIAL_WITH_BLOCKERS';result['PASS']=False;result['source_changed_during_run']=True
        for path in a.output.iterdir():
            if path.is_file():
                with path.open('r+b') as f:os.fsync(f.fileno())
        result['whole_command_seconds']=time.perf_counter()-started
        result['backend_origin']='ACTUAL_FPGA' if a.backend=='fpga' else 'MOCK'
        result['controller_acceptance']='PENDING'
        dump(a.output/'RESULT.json',result)
if __name__=='__main__':main()
