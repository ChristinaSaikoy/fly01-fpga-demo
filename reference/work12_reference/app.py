"""Loopback-only MVP UI. Capture, neural I/O and UI/supervision are independent."""
import argparse,copy,hashlib,io,json,math,os,secrets,socket,sys,threading,time,uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from PIL import Image,ImageDraw,ImageSequence
import numpy as np
from neural import NeuralRuntime,hardware_runtime,C
from actuator import DryRunActuator
from fly01_vision.pipeline import VisionPipeline
from fly01_vision.settings import load_settings
ROOT=Path(__file__).resolve().parent
VERSION='MVP-DEMO-V1'

def version_hash():
    paths=[ROOT/n for n in ('app.py','neural.py','pixel.py','mvp_link.py','mvp_authority.py','actuator.py','index.html','BUILD_READY.json')]+list((ROOT/'vendor').rglob('*'))
    items=[(p.relative_to(ROOT).as_posix(),hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths if p.is_file() and '__pycache__' not in p.parts]
    return hashlib.sha256(json.dumps(sorted(items),separators=(',',':')).encode()).hexdigest()

class Journal:
    def __init__(self,folder):
        self.lock=threading.Lock();self.closed=False
        self.f=(folder/'ledger.jsonl').open('x',encoding='utf-8',buffering=1)
    def emit(self,row):
        with self.lock:
            if not self.closed:self.f.write(json.dumps(dict(host_log_ns=time.monotonic_ns(),**row),ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n')
    def close(self):
        with self.lock:
            if not self.closed:self.f.flush();os.fsync(self.f.fileno());self.f.close();self.closed=True

class Latest:
    def __init__(self):self.lock=threading.Lock();self.value=None;self.replaced=0
    def put(self,value):
        with self.lock:
            if self.value is not None:self.replaced+=1
            self.value=value
    def take(self):
        with self.lock:v=self.value;self.value=None;return v

def validate_config(config):
    c=dict(source='replay',path=str(ROOT/'assets/sequence.gif'),backend='reference',camera_index=0,
        replay_fps=5.,loop=True,sensor_mirror_x=False,deadband_px=2.,approval=None,receipt=None,
        identity=None,camera_approval=None,recover=False)
    c.update(config)
    # Use explicit merge below rather than silently changing neural constants.
    if c['source'] not in ('replay','camera') or c['backend'] not in ('reference','fpga'):raise ValueError('source/backend')
    if type(c['sensor_mirror_x']) is not bool or type(c['loop']) is not bool:raise ValueError('mirror/loop bool')
    if type(c['camera_index']) is not int or not 0<=c['camera_index']<=32:raise ValueError('camera index')
    if not math.isfinite(c['replay_fps']) or not .5<=c['replay_fps']<=30:raise ValueError('replay fps .5..30')
    if not math.isfinite(c['deadband_px']) or not 0<=c['deadband_px']<=100:raise ValueError('pixel deadband')
    if c['source']=='replay':
        p=Path(c['path']).resolve()
        if not p.is_file() or p.suffix.lower() not in ('.gif','.mp4','.avi','.mov','.mkv','.png','.jpg','.jpeg'):raise ValueError('supported replay file required')
        c['path']=str(p)
    else:
        if not c['camera_approval']:raise PermissionError('fresh camera preview scope required; no camera opened')
        a=json.loads(Path(c['camera_approval']).read_text(encoding='utf-8'))
        if a.get('status')!='APPROVED_CAMERA_PREVIEW' or a.get('execution_host')!=socket.gethostname() or a.get('camera_index')!=c['camera_index'] or a.get('scope')!='LOCAL_PREVIEW_NO_RAW_RECORDING':raise PermissionError('camera approval mismatch')
    if c['backend']=='fpga' and not all(c.get(k) for k in ('approval','receipt','identity')):raise PermissionError('fresh exact host/bit/port authority required; no port opened')
    return c

def frames(c,cancel):
    """Unknown sensor exposure; only actual host receive/decode timestamps recorded."""
    if c['source']=='replay' and Path(c['path']).suffix.lower() in ('.gif','.png','.jpg','.jpeg'):
        with Image.open(c['path']) as image:
            if image.width*image.height>2073600:raise ValueError('image too large')
            images=[np.array(f.convert('RGB')) for f in ImageSequence.Iterator(image)]
        while not cancel.is_set():
            for rgb in images:
                if cancel.is_set():return
                now=time.monotonic_ns()
                yield rgb,dict(kind='REPLAY',input=c['path'],capture_time_ns=None,capture_time_verified=False,
                    exposure='UNKNOWN_EXPOSURE',host_decode_done_ns=now,
                    provenance='BY02_SYNTHETIC_SAMPLE' if Path(c['path']).is_relative_to(ROOT/'assets') else 'USER_SUPPLIED_REPLAY'),now
                if cancel.wait(1/c['replay_fps']):return
            if not c['loop']:return
    else:
        import cv2
        camera=c['source']=='camera';cap=cv2.VideoCapture(c['camera_index'] if camera else c['path'])
        try:
            if not cap.isOpened():raise RuntimeError('capture open failed')
            if camera:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH,640);cap.set(cv2.CAP_PROP_FRAME_HEIGHT,480)
                cap.set(cv2.CAP_PROP_BUFFERSIZE,1) # request only, not verified latency
            while not cancel.is_set():
                before=time.monotonic_ns();ok,bgr=cap.read();received=time.monotonic_ns()
                if not ok:
                    if camera:raise RuntimeError('camera disconnected/read failed')
                    if c['loop']:cap.set(cv2.CAP_PROP_POS_FRAMES,0);continue
                    return
                if bgr.shape[0]*bgr.shape[1]>2073600:raise ValueError('capture frame too large')
                yield np.ascontiguousarray(bgr[:,:,::-1]),dict(kind='REAL_CAMERA' if camera else 'REPLAY',
                    input=c['camera_index'] if camera else c['path'],capture_time_ns=None,capture_time_verified=False,
                    exposure='UNKNOWN_EXPOSURE',host_read_begin_ns=before,host_decode_done_ns=received,
                    camera_buffer_age_verified=False),received
                if not camera and cancel.wait(1/c['replay_fps']):return
        finally:cap.release()

class Controller:
    def __init__(self,root=ROOT/'runs'):
        self.root=Path(root);self.lock=threading.RLock();self.act_lock=threading.Lock()
        self.worker=None;self.capture=None;self.cancel=threading.Event();self.journal=None;self.runtime=None
        self.config=None;self.folder=None;self.last=None;self.observation=None;self.jpeg=None;self.recovery_session=None
        self.phase='STOPPED';self.error=None;self.source_error=None;self.stats={};self.latencies=[]
        self.actuator=DryRunActuator(self.log)
    def log(self,row):
        if self.journal:self.journal.emit(row)
    def start(self,config):
        with self.lock:
            if self.worker and self.worker.is_alive() or self.capture and self.capture.is_alive():raise RuntimeError('previous worker still active; stop/wait first')
            defaults=dict(source='replay',path=str(ROOT/'assets/sequence.gif'),backend='reference',camera_index=0,
                replay_fps=5.,loop=True,sensor_mirror_x=False,deadband_px=2.,approval=None,receipt=None,identity=None,camera_approval=None,recover=False)
            defaults.update(config);self.config=validate_config(defaults)
            self.config['host_candidate_sha256']=version_hash()
            self.cancel=threading.Event();self.mailbox=Latest();self.last=self.observation=self.jpeg=None
            self.error=self.source_error=None;self.latencies=[];self.phase='INITIALIZING'
            self.stats=dict(source_frames=0,model_steps=0,valid_target_feedback=0,neutral_steps=0,source_invalid=0)
            self.started=time.monotonic();self.session_id=uuid.uuid4().hex
            self.folder=self.root/(time.strftime('%Y%m%dT%H%M%S')+'_'+self.session_id[:8]);self.folder.mkdir(parents=True,exist_ok=False)
            self.journal=Journal(self.folder);self.runtime=None
            self.log(dict(kind='RUN_START',version=VERSION,candidate_sha256=version_hash(),config=self.config,
                source_identity='REAL_CAMERA' if self.config['source']=='camera' else 'REPLAY',
                backend='FPGA_UART' if self.config['backend']=='fpga' else 'SOFTWARE_REFERENCE',
                dt_s=.02,timeout_s=.5,retries=1,max_step_io_wait_s=2.,result_age_limit_ms=250,
                actuator='DRY_RUN_ONLY',physical_motion_authorized=False,reset_semantics='NEW_RNG_MODEL_POSTPROCESSOR_FROM_ZERO'))
            self.worker=threading.Thread(target=self._compute,daemon=True,name='mvp-neural');self.worker.start()
            return dict(started=True,run_dir=str(self.folder),session=self.session_id)
    def stop(self):
        self.cancel.set()
        with self.act_lock:self.actuator.stop('OPERATOR_STOP')
        with self.lock:
            if self.worker and self.worker.is_alive():self.phase='STOPPING'
        return dict(stopping=True)
    def _capture(self):
        c=self.config;settings=load_settings();settings['input']['sensor_mirror_x']=c['sensor_mirror_x']
        pipeline=VisionPipeline(settings,self.session_id,'HOST_MONOTONIC');frame=0
        try:
            for rgb,source,received in frames(c,self.cancel):
                obs,processed=pipeline.process_rgb(rgb,frame_id=frame,source=source,received_ns=received)
                image=Image.fromarray(processed);draw=ImageDraw.Draw(image)
                for box in obs['bounding_boxes_xyxy_exclusive']:draw.rectangle(box,outline=(0,180,160),width=2)
                draw.text((5,5),f"{source['kind']} | {obs['status']} | {frame}",fill=(235,180,40))
                buffer=io.BytesIO();image.save(buffer,format='JPEG',quality=80)
                self.mailbox.put(obs);self.log(dict(kind='VISION',observation=obs))
                with self.lock:
                    self.observation=obs;self.jpeg=buffer.getvalue();self.stats['source_frames']+=1
                    if obs['status']!='VALID':self.stats['source_invalid']+=1
                if obs['status']!='VALID':
                    with self.act_lock:
                        if self.actuator.enabled:self.actuator.stop(obs['status'])
                frame+=1
        except Exception as exc:
            self.source_error=repr(exc);self.log(dict(kind='SOURCE_FAULT',error=self.source_error))
        finally:
            terminal=dict(schema='BY02_VISION_OBSERVATION_V1',coordinate_system='IMAGE_X_RIGHT_Y_DOWN_PIXEL_CENTERS',
                session_id=self.session_id,frame_id=frame,status='ERROR' if self.source_error else 'INPUT_ENDED',
                object_count=0,clock_domain='HOST_MONOTONIC',received_monotonic_ns=time.monotonic_ns(),processed_monotonic_ns=time.monotonic_ns(),source={})
            self.mailbox.put(terminal)
            with self.lock:self.observation=terminal
            self.log(dict(kind='SOURCE_ENDED',observation=terminal))
    def _compute(self):
        evidence=None
        try:
            if self.config['backend']=='reference':self.runtime=NeuralRuntime.reference(deadband=self.config['deadband_px'])
            else:
                from uart_host import EvidenceLog
                evidence=EvidenceLog(self.folder/'wire','FPGA_UART_MVP_CANDIDATE')
                prior=self.recovery_session if self.config['recover'] else None
                self.runtime=hardware_runtime(self.config,evidence,self.cancel,prior)
            self.log(dict(kind='SESSION_READY',backend=self.runtime.backend,generation=self.runtime.adapter.generation,
                physical_generation=getattr(self.runtime.adapter,'hardware_generation',None),model_step=0,
                recovered_prior_session=bool(self.config['recover'])))
            self.phase='RUNNING';self.capture=threading.Thread(target=self._capture,daemon=True,name='mvp-vision');self.capture.start()
            while not self.cancel.is_set():
                if time.monotonic()-self.started>=1800:break # finite demo session, no automatic restart
                start=time.monotonic();observation=self.mailbox.take()
                if observation:self.runtime.provider.submit(observation)
                record=self.runtime.step(time.monotonic_ns(),self.log)
                self.log(record)
                with self.lock:
                    self.last=record;self.stats['model_steps']+=1
                    self.stats['valid_target_feedback' if record['sampling']['applied']['observation_id'] else 'neutral_steps']+=1
                    self.latencies.append((record['validated_ns']-record['started_ns'])/1e6)
                with self.act_lock:self.actuator.update(record,time.monotonic_ns())
                if self.source_error:raise RuntimeError('source failed: '+self.source_error)
                if self.observation and self.observation['status']=='INPUT_ENDED' and self.mailbox.value is None:break
                self.cancel.wait(max(0,.02-(time.monotonic()-start))) # dt is never changed, no catch-up skipping
        except Exception as exc:
            self.error=repr(exc);self.phase='FAULT';self.log(dict(kind='FAULT_OUTPUT_INVALID',error=self.error,
                model_step=self.runtime.k if self.runtime else None,action='EXPLICIT_NEW_SESSION_REQUIRED'))
        finally:
            self.cancel.set()
            with self.act_lock:self.actuator.stop('RUN_ENDED_OR_FAULT')
            if self.capture:self.capture.join(timeout=2)
            if self.runtime:
                transport=self.runtime.adapter.transport
                if hasattr(transport,'client'):self.recovery_session=transport.client.session
                try:transport.close()
                except Exception as exc:self.error=self.error or repr(exc)
            if evidence:evidence.close()
            if self.capture and self.capture.is_alive():self.error=self.error or 'CAPTURE_STOP_UNCONFIRMED'
            self.phase='FAULT' if self.error else 'STOPPED'
            summary=self.summary();self.log(dict(kind='RUN_END',summary=summary))
            (self.folder/'SUMMARY.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
            self.journal.close()
    def status(self):
        with self.lock:
            now=time.monotonic_ns();last=self.last;obs=copy.deepcopy(self.observation)
            age=(now-last['validated_ns'])/1e6 if last else None
            target_age=(now-obs['received_monotonic_ns'])/1e6 if obs else None
            fresh=bool(last and age<250 and self.phase=='RUNNING')
            target_valid=bool(obs and obs['status']=='VALID' and target_age<250)
            health='FAULT' if self.error else 'STOPPED' if self.phase=='STOPPED' else 'STALE' if not fresh or obs and obs['status']=='VALID' and not target_valid else obs['status'] if obs and not target_valid else 'RUNNING'
            drive=last['motor_drive_simulated'] if last and fresh else None
            stats=dict(self.stats);stats['visual_replacements']=getattr(getattr(self,'mailbox',None),'replaced',0)
            client=getattr(getattr(getattr(self.runtime,'adapter',None),'transport',None),'client',None)
            stats['link']=dict(client.stats) if client else dict(retries=0,bad_segments=0,timeouts=0,stale_responses=0)
            elapsed=time.monotonic()-self.started if hasattr(self,'started') else 0
            return dict(version=VERSION,phase=self.phase,health=health,error=self.error,source_error=self.source_error,
                backend=self.runtime.backend if self.runtime else 'NOT_STARTED',source='REAL_CAMERA' if self.config and self.config['source']=='camera' else 'REPLAY',
                observation=obs,stimulus=last['sampling']['applied'] if last and fresh else None,
                dn_slots=last['dn_slots'] if fresh else None,motor_drive_simulated=drive,
                output_valid=fresh,target_valid=target_valid,result_age_ms=age,receive_age_ms=target_age,
                exposure='UNKNOWN_EXPOSURE',motion_eligible=False,physical_output=False,
                dry_run_enabled=self.actuator.enabled,dry_run_fault=self.actuator.fault,
                model_step=last['model_step'] if last else None,model_time_s=last['model_time_s'] if last else 0,
                model_rate_hz=stats.get('model_steps',0)/elapsed if elapsed else 0,
                source_rate_hz=stats.get('source_frames',0)/elapsed if elapsed else 0,stats=stats,
                run_dir=str(self.folder) if self.folder else None)
    def supervise(self):
        s=self.status()
        with self.act_lock:
            self.actuator.poll(time.monotonic_ns())
            if self.actuator.enabled and (not s['output_valid'] or not s['target_valid']):self.actuator.stop('SUPERVISOR_INVALID_OR_STALE')
    def summary(self):
        values=sorted(self.latencies);elapsed=time.monotonic()-self.started
        return dict(version=VERSION,candidate_sha256=version_hash(),status='FAULT' if self.error else 'SOFTWARE_RUN_COMPLETE' if self.config['backend']=='reference' else 'HARDWARE_RUN_REQUIRES_REVIEW',
            error=self.error,source='REAL_CAMERA' if self.config['source']=='camera' else 'REPLAY',
            backend=self.runtime.backend if self.runtime else self.config['backend'],wall_s=elapsed,
            stats=dict(self.stats,visual_replacements=self.mailbox.replaced),
            valid_target_feedback_hz=self.stats['valid_target_feedback']/elapsed,
            model_rate_hz=self.stats['model_steps']/elapsed,
            step_ms=dict(mean=sum(values)/len(values),p99=values[min(len(values)-1,int(len(values)*.99))],maximum=max(values)) if values else None,
            capture_join_complete=not self.capture or not self.capture.is_alive(),dt_s=.02,
            exposure='UNKNOWN_EXPOSURE',physical_output=False,strict_50hz='OLD_FAIL_NOT_RETESTED',
            strict_packet='OLD_FAIL_NOT_RETESTED')

def server(controller,port=0):
    token=secrets.token_urlsafe(24)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,code,data,kind='application/json'):
            if not isinstance(data,bytes):data=json.dumps(data,ensure_ascii=False).encode()
            self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if self.headers.get('Host')!=f'127.0.0.1:{self.server.server_port}':return self.reply(403,{'error':'loopback host only'})
            if self.path=='/':return self.reply(200,(ROOT/'index.html').read_text(encoding='utf-8').replace('__TOKEN__',token).encode(),'text/html; charset=utf-8')
            if self.path=='/status':return self.reply(200,controller.status())
            if self.path.startswith('/frame.jpg'):
                if controller.jpeg:return self.reply(200,controller.jpeg,'image/jpeg')
                return self.reply(404,{'error':'no frame'})
            return self.reply(404,{'error':'not found'})
        def do_POST(self):
            origin=f'http://127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host')!=origin[7:] or self.headers.get('X-MVP-Token')!=token or self.headers.get('Origin',origin)!=origin or self.headers.get('Content-Type')!='application/json':return self.reply(403,{'error':'local token/origin required'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<=size<=16384:raise ValueError('request too large')
                data=json.loads(self.rfile.read(size))
                if self.path=='/start':result=controller.start(data)
                elif self.path=='/stop':result=controller.stop()
                elif self.path=='/dry-enable':
                    s=controller.status()
                    if not s['output_valid'] or not s['target_valid']:raise ValueError('need fresh target and result; dry-run stays disabled')
                    with controller.act_lock:controller.actuator.enable()
                    result={'dry_run_only':True,'physical_output':False}
                else:raise ValueError('unknown operation')
                self.reply(200,result)
            except Exception as exc:self.reply(400,dict(error=str(exc)))
    http=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    http.daemon_threads=True;return http

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=0);p.add_argument('--autostart-replay',action='store_true')
    p.add_argument('--seconds',type=float,default=0);p.add_argument('--ready-file');a=p.parse_args()
    c=Controller();http=server(c,a.port);ready=dict(url=f'http://127.0.0.1:{http.server_port}',pid=os.getpid(),version=VERSION)
    if a.ready_file:
        with Path(a.ready_file).open('x',encoding='utf-8') as f:json.dump(ready,f)
    print(json.dumps(ready),flush=True)
    if a.autostart_replay:c.start({})
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start();started=time.monotonic()
    try:
        while not a.seconds or time.monotonic()-started<a.seconds:c.supervise();time.sleep(.05)
    except KeyboardInterrupt:pass
    finally:
        c.stop()
        if c.worker:c.worker.join(timeout=5)
        http.shutdown();http.server_close()
if __name__=='__main__':main()
