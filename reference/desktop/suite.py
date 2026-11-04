"""One approved programming/regression/camera window, <=1800s including reports.

Default command verifies files only. No approval records are minted by --check.
"""
import time
PROCESS_START_NS = time.monotonic_ns()
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading

from identity import ROOT, BIT, BIT_SHA, FORMAL_ROOT, verify, sha

def dump(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())

def approval(path, now_ns=None):
    auth = json.loads(Path(path).read_text(encoding='utf-8'))
    lock = verify()
    now = time.monotonic_ns() if now_ns is None else now_ns
    start = auth.get('mvp_scope', {}).get('suite_started_monotonic_ns')
    if (auth.get('status') != 'APPROVED_EXACT_ARTIFACT' or auth.get('candidate_sha256') != lock['candidate_sha256']
        or auth.get('bit_sha256') != BIT_SHA or auth.get('target_serial') != '210512180081'
        or auth.get('host_platform') != 'windows-native' or auth.get('execution_host') != socket.gethostname()
        or auth.get('programming_mode') != 'PROGRAM_EXACT_ONCE' or auth.get('uart_data_test_authorized') is not True
        or auth.get('uart_baud') != 2000000 or auth.get('confirmation_mode') != 'USER_CONFIRMED_WORK13_COMBINED'
        or not auth.get('user_confirmation_source') or not auth.get('power_setup_confirmed')
        or auth.get('camera_preview_authorized') is not True or auth.get('image_recording') is not False
        or auth.get('physical_motion_authorized') is not False or auth.get('suite_limit_s') != 1800
        or auth.get('mvp_scope', {}).get('name') != 'MVP-DEMO-V1_NON_MOTION'
        or auth.get('mvp_scope', {}).get('restart_policy') != 'EXPLICIT_SAME_PROCESS_WITHIN_WINDOW'
        or type(start) is not int or not 0 <= now-start < 1800_000_000_000):
        raise PermissionError('Fresh exact combined WORK13 confirmation missing/expired; no device access')
    if not isinstance(auth.get('suite_id'), str) or not auth['suite_id'] or auth['suite_id'] in lock['previously_consumed_suite_ids']:
        raise PermissionError('Fresh suite ID required')
    from camera import bind
    bind([auth['camera_device']], name=auth['camera_device']['name'], symbolic_link=auth['camera_device']['symbolic_link'])
    return auth

def formal_function():
    """Unchanged accepted 5421-frame formal function; verified external source."""
    source = FORMAL_ROOT/'host/acceptance_worker.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('formal', 'dump')]
    namespace = dict(__file__=str(source), Path=Path, json=json, hashlib=hashlib, time=time, csv=__import__('csv'))
    exec(compile(tree, str(source), 'exec'), namespace)
    return namespace['formal']

def program(auth, output, deadline):
    from windows_job import stop_owned_tree
    env = dict(os.environ, PROCESSOR_ARCHITECTURE='AMD64', FLY01_SHA_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE='1')
    binary = Path(os.environ.get('FLY01_VIVADO_BIN','D:/AMDDesignTools/2025.2/Vivado/bin'))
    server = child = None
    logs = []
    def launch(argv, name):
        stream = (output/(name+'.log')).open('x', encoding='utf-8');logs.append(stream)
        dump(output/(name+'.command.json'), dict(argv=list(map(str, argv))))
        return subprocess.Popen(list(map(str, argv)), cwd=output, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',3121)) == 0:
                raise RuntimeError('Existing hw_server is not ours; no takeover')
        server = launch([binary/'hw_server.bat','-p0','-s','tcp:127.0.0.1:3121','-I86400'],'hw_server')
        for _ in range(100):
            if time.monotonic()>=deadline or server.poll() is not None:raise RuntimeError('Owned hw_server failed')
            with socket.socket() as probe:
                if probe.connect_ex(('127.0.0.1',3121))==0:break
            time.sleep(.1)
        else:raise TimeoutError('Owned hw_server startup deadline')
        receipt = output/'CURRENT_LOAD_RECEIPT.json'
        child = launch([binary/'vivado.bat','-mode','batch','-notrace','-source',ROOT/'program_exact_windows.tcl',
                        '-tclargs',BIT,BIT_SHA,auth['target_serial'],receipt,auth['suite_id']],'program')
        child.wait(timeout=max(.001,min(deadline-time.monotonic(),150)))
        raw = (output/'program.log').read_text(encoding='utf-8',errors='replace')
        import re
        if child.returncode or not re.search(r'^O8_EXACT_VOLATILE_PROGRAM_AND_READONLY_IDENTITY_PASS\s*$',raw,re.M) or re.search(r'^\s*(ERROR:|CRITICAL WARNING:)',raw,re.M):
            raise RuntimeError('Programming gate failed; preserve raw logs')
        loaded = json.loads(receipt.read_text(encoding='utf-8'))
        if (loaded.get('programming_status')!='PASS' or loaded.get('suite_id')!=auth['suite_id']
            or loaded.get('target_serial')!=auth['target_serial'] or loaded.get('volatile_only') is not True
            or any(loaded.get(k)!=BIT_SHA for k in ('before_sha256','after_sha256','bitstream_sha256'))):
            raise RuntimeError('Fresh load receipt mismatch')
        return receipt
    finally:
        stop_owned_tree(child);stop_owned_tree(server)
        for stream in logs:stream.flush();os.fsync(stream.fileno());stream.close()

def regress(auth, approval_path, receipt, output, *, targeted=False):
    from mvp_authority import claim_scope
    from mvp_link import MVPClient
    from neural import ClosingTransport
    from science_bridge import FpgaAdapter
    from uart_host import EvidenceLog
    from uart_windows import WindowsPort
    lease = claim_scope(approval_path, auth['candidate_sha256'])
    evidence = EvidenceLog(output/'formal_wire','ACTUAL_FPGA_UART_WORK13_FORMAL')
    port = transport = None
    try:
        port = WindowsPort.open_approved(auth['uart_identity'],2000000,approval_path,receipt,evidence)
        client = MVPClient(port,secrets.randbelow(0xffffffff)+1,scope_deadline_ns=lease['started_ns']+1200_000_000_000)
        client.claim();transport = ClosingTransport(client)
        adapter = FpgaAdapter(transport,loaded_sha=BIT_SHA,load_receipt=receipt)
        formal_dir = output/'formal';formal_dir.mkdir()
        if targeted:
            from targeted import run_short
            return run_short(adapter,formal_dir,origin='ACTUAL_FPGA_UART')
        return formal_function()(adapter,formal_dir)
    finally:
        try:
            if transport:transport.close()
            elif port:port.close()
        finally:evidence.close()

def wait_for_operator(controller, auth, output):
    # Same suite origin; waiting never extends/restarts the 1800s budget.
    deadline=min(time.monotonic()+300,auth['mvp_scope']['suite_started_monotonic_ns']/1e9+1370)
    with controller.lock:
        controller.preview_start_deadline=deadline
    while True:
        if controller.cancel.is_set():raise RuntimeError('Operator stopped before preview')
        if time.monotonic()>=deadline:raise TimeoutError('Operator not ready within reserved suite window; no camera opened')
        if controller.preview_gate.wait(.1):break
    if controller.cancel.is_set():raise RuntimeError('Operator stopped while readiness was signalled')
    if time.monotonic()>=deadline:raise TimeoutError('Readiness arrived after reserved suite deadline')
    dump(output/'OPERATOR_READY.json',dict(kind='LOCAL_UI_OPERATOR_READY',confirmed_monotonic_ns=time.monotonic_ns(),
        suite_id=auth['suite_id'],note='Readiness only; not a direction-calibration marker or new authority'))

def interaction(auth, approval_path, receipt, output):
    from camera import enumerate_devices, bind
    import app
    device = auth['camera_device']
    fresh = bind(enumerate_devices(),name=device['name'],symbolic_link=device['symbolic_link'])
    # Fresh enumeration may reorder indexes, but never changes the bound physical identity.
    camera_auth = output/'CAMERA_APPROVAL.json'
    dump(camera_auth,dict(status='APPROVED_CAMERA_PREVIEW',execution_host=auth['execution_host'],
        camera_index=fresh['index'],scope='LOCAL_PREVIEW_NO_RAW_RECORDING',work13_confirmed=True,
        user_confirmation_source=auth['user_confirmation_source'],device_name=fresh['name'],
        symbolic_link=fresh['symbolic_link'],suite_id=auth['suite_id']))
    controller = app.Controller(output/'interaction')
    controller.required_config=dict(source='camera',backend='fpga',camera_index=fresh['index'],
        camera_approval=str(camera_auth),approval=str(approval_path),receipt=str(receipt),identity=auth['uart_identity'],
        sensor_mirror_x=auth.get('sensor_mirror_x',False),recover=False)
    controller.confirmed_suite=True
    http=app.server(controller)
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    first=None;started=time.monotonic();stats=[]
    try:
        controller.arm_preview()
        ready=dict(url=f'http://127.0.0.1:{http.server_port}',pid=os.getpid(),backend='FPGA_UART_PENDING_OPERATOR',source='REAL_CAMERA_PENDING_OPERATOR',
                   waits_for_operator=True,instructions='Click target ready to begin preview; then confirm LEFT/RIGHT/CENTER/REMOVED. No images saved.')
        dump(output/'UI_READY.json',ready);print(json.dumps(ready),flush=True)
        wait_for_operator(controller,auth,output)
        controller.start(controller.required_config);started=time.monotonic()
        while time.monotonic_ns()<auth['mvp_scope']['suite_started_monotonic_ns']+1600_000_000_000:
            controller.supervise()
            status=controller.status()
            if status['stats'].get('source_frames') and first is None:first=time.monotonic()
            stats.append(dict(ns=time.monotonic_ns(),phase=status['phase'],health=status['health'],
                              model_step=status['model_step'],result_age_ms=status['result_age_ms']))
            if first is not None and time.monotonic()-first>=180:break
            if first is None and time.monotonic()-started>30:break
            if status['phase']=='STOPPED':break
            time.sleep(.1)  # FAULT stays visible; only explicit bounded recovery, no automatic reset
    finally:
        controller.stop()
        if controller.worker:controller.worker.join(8)
        controller.jpeg=None;http.shutdown();http.server_close();thread.join(2)
        dump(output/'UI_SUPERVISION.json',stats)
        dump(output/'INTERACTION_EXIT.json',dict(status=controller.status(),
             camera_thread_stopped=not controller.capture or not controller.capture.is_alive(),
             worker_stopped=not controller.worker or not controller.worker.is_alive(),
             server_thread_stopped=not thread.is_alive(),explicit_recoveries=controller.explicit_recoveries,
             camera_stream_window_s=time.monotonic()-first if first else 0,images_saved=False))
    if controller.capture and controller.capture.is_alive() or controller.worker and controller.worker.is_alive():
        raise RuntimeError('Device release unconfirmed; parent must terminate owned job')

def review(output):
    import replay
    reviews=[]
    for folder in sorted((output/'interaction').glob('*')):
        if not folder.is_dir():continue
        result=replay.replay(folder,allow_unresolved=True)
        stages=[]
        visions={};adopted=[];faults=[]
        for line in replay.ledger_lines(folder/'ledger.jsonl'):
            row=json.loads(line)
            if row['kind']=='OPERATOR_STAGE':stages.append(row)
            elif row['kind']=='VISION':
                o=row['observation'];visions[f"{o['session_id']}:{o['frame_id']}"]=o
            elif row['kind']=='ADOPTED_INPUT':adopted.append(row)
            elif row['kind'] in ('SOURCE_FAULT','FAULT_OUTPUT_INVALID'):faults.append(row)
        consumed=0
        for a in adopted:
            selected=a['sampling']['applied'];identifier=selected.get('observation_id')
            if identifier is None:continue
            o=visions[identifier]
            if o['status']!='VALID' or o['source']['kind']!='REAL_CAMERA' or o['received_monotonic_ns']!=selected['received_ns']:
                raise RuntimeError('Adopted input not backed by valid real-camera observation')
            consumed+=1
        reviews.append(dict(run=str(folder),replay=result,operator_stages=stages,
            camera_adopted_steps=consumed,faults=faults,physical_direction_check='CONFIRMED_INPUT_ONLY' if
                set(m['phase'] for m in stages if m['input_check']=='INPUT_MATCH')=={'LEFT','RIGHT','CENTER','REMOVED'} else 'PENDING_OPERATOR_STAGES'))
    dump(output/'SESSION_REVIEWS.json',reviews)
    return reviews

def worker(args):
    cookie=sys.stdin.readline().strip()
    if not cookie or cookie!=os.environ.get('WORK13_OWNED_COOKIE'):raise PermissionError('Owned job bootstrap required')
    auth=approval(args.approval)
    targeted=getattr(args,'targeted',False)
    if targeted and auth.get('regression_mode')!='TARGETED_INTERACTION_CONTINUATION':
        raise PermissionError('Targeted continuation must be included in this suite binding')
    result=dict(status='PARTIAL_WITH_BLOCKERS',actual_hardware='NOT_STARTED',strict_packet='OLD_FAIL_NOT_RETESTED',strict_50hz='OLD_FAIL_NOT_RETESTED')
    try:
        from uart_windows import select_device
        dump(args.output/'PASSIVE_UART_IDENTITY.json',select_device(auth['uart_identity']))
        receipt=program(auth,args.output,auth['mvp_scope']['suite_started_monotonic_ns']/1e9+180)
        result['actual_hardware']='EXACT_HISTORICAL_O8_PROGRAMMED'
        if targeted:result['formal']=regress(auth,args.approval,receipt,args.output,targeted=True)
        else:result['formal']=regress(auth,args.approval,receipt,args.output)
        if time.monotonic_ns()>auth['mvp_scope']['suite_started_monotonic_ns']+1250_000_000_000:
            raise TimeoutError('Not enough reserved time for one camera session/review/cleanup')
        interaction(auth,args.approval,receipt,args.output)
        result['sessions']=review(args.output)
        exit_info=json.loads((args.output/'INTERACTION_EXIT.json').read_text(encoding='utf-8'))
        result['interaction']=dict(camera_window_s=exit_info['camera_stream_window_s'],
            sources=[r['replay']['origin'] for r in result['sessions']],
            valid_camera_adopted_steps=sum(r['camera_adopted_steps'] for r in result['sessions']),
            unresolved_steps=[dict(run=r['run'],steps=r['replay']['unresolved_steps']) for r in result['sessions'] if r['replay']['unresolved_steps']],
            physical_direction=[r['physical_direction_check'] for r in result['sessions']],
            explicit_recoveries=exit_info['explicit_recoveries'],stop_status=exit_info['status']['phase'])
        if (exit_info['camera_stream_window_s']<180 or not result['sessions']
            or not result['interaction']['valid_camera_adopted_steps'] or any(r['replay']['origin']!='FPGA_UART' for r in result['sessions'])):
            raise RuntimeError('Camera/FPGA interaction coverage incomplete; keep partial evidence')
        result['status']='SUBMITTED_FOR_REVIEW'
    except BaseException as exc:
        result['error']=repr(exc)
        result['traceback']=__import__('traceback').format_exc()
    finally:
        result['elapsed_s']=(time.monotonic_ns()-auth['mvp_scope']['suite_started_monotonic_ns'])/1e9
        dump(args.output/'WORKER_RESULT.json',result)
    return 0 if result['status']=='SUBMITTED_FOR_REVIEW' else 1

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--check',action='store_true');p.add_argument('--execute',action='store_true')
    p.add_argument('--approval',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--targeted',action='store_true',help='Run original 1+20 prefix only; preserve historical full regression as prior evidence')
    p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=p.parse_args()
    if args.worker:return worker(args)
    lock=verify()
    if not args.execute:
        print(json.dumps(dict(status='READY_FOR_BOARD_OFFLINE_CHECK_ONLY',candidate_sha256=lock['candidate_sha256'],hardware='NONE')))
        return 0
    if args.approval is None or args.output is None:raise PermissionError('Exact fresh approval and unique output required')
    auth=approval(args.approval)
    args.output.mkdir(parents=True,exist_ok=False)
    uses=ROOT/'authorization_uses';uses.mkdir(exist_ok=True)
    dump(uses/(hashlib.sha256(auth['suite_id'].encode()).hexdigest()+'.whole_suite_intent.json'),dict(suite_id=auth['suite_id'],candidate_sha256=lock['candidate_sha256']))
    from windows_job import OwnedJob,stop_owned_tree
    job=OwnedJob();child=None;cookie=secrets.token_hex(24)
    final=dict(status='PARTIAL_WITH_BLOCKERS',hard_deadline_s=1800,start_ns=auth['mvp_scope']['suite_started_monotonic_ns'])
    try:
        with (args.output/'worker.log').open('x',encoding='utf-8') as log:
            child=subprocess.Popen([sys.executable,'-B',__file__,'--worker','--approval',str(args.approval.resolve()),'--output',str(args.output.resolve())]+(['--targeted'] if args.targeted else []),
                stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,cwd=ROOT,text=True,
                env=dict(os.environ,WORK13_OWNED_COOKIE=cookie,PROCESSOR_ARCHITECTURE='AMD64',PYTHONDONTWRITEBYTECODE='1'),
                creationflags=subprocess.CREATE_NO_WINDOW)
            job.assign_waiting_child(child)
            child.stdin.write(cookie+'\n');child.stdin.flush();child.stdin.close()
            child.wait(timeout=max(.001,auth['mvp_scope']['suite_started_monotonic_ns']/1e9+1740-time.monotonic()))
            if child.returncode==0:final['status']='SUBMITTED_FOR_REVIEW'
            else:final['child_exit_code']=child.returncode
            log.flush();os.fsync(log.fileno())
    except BaseException as exc:
        final['error']=repr(exc)
    finally:
        job.terminate();stop_owned_tree(child)
        final['owned_processes_remaining']=job.active();job.close()
        final['elapsed_s']=(time.monotonic_ns()-auth['mvp_scope']['suite_started_monotonic_ns'])/1e9
        final['within_30_minutes']=final['elapsed_s']<=1800
        if final['owned_processes_remaining'] or not final['within_30_minutes']:final['status']='PARTIAL_WITH_BLOCKERS'
        dump(args.output/'FINAL_RECEIPT.json',final)
    print(json.dumps(final));return 0 if final['status']=='SUBMITTED_FOR_REVIEW' else 1

if __name__=='__main__':raise SystemExit(main())
