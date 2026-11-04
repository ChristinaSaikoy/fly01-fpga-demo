"""Frozen neural/RNG/postprocessor chain with explicitly selected backend."""
import hashlib,math,sys,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT/'vendor'))
from science_bridge import C,FpgaAdapter,MockNeuralTransport,UartNeuralTransport,encode_inputs
from pixel import PixelDirectionMVP

class NeuralRuntime:
    def __init__(self,adapter,backend,deadband=2):
        self.adapter,self.backend=adapter,backend;self.k=0;self.fault=None
        assert C.DT==.02
        self.provider=PixelDirectionMVP(C.SE.ROSTER,C.SE.Q,deadband)
        self.rng=np.random.default_rng(C.SEED);self.art=C.SH.FrozenArtifacts()
        self.pre=C.SH.FrozenPreprocessorV1_0(self.art);self.mapper=C.SH.FinalDNMotorMapperV1_0(self.art)
        self.bodyrt=self.art.bodyrt.BodyRuntime(self.art.body_config);self.body=self.art.bodyrt.BodyState.zero()
    @classmethod
    def reference(cls,**kwargs):return cls(FpgaAdapter(MockNeuralTransport()),'SOFTWARE_REFERENCE',**kwargs)
    def step(self,now_ns,attempt_log=None):
        if self.fault:raise RuntimeError('fault latched; explicit new session required')
        k=self.k;start=time.monotonic_ns();sampling=self.provider.sample(k,now_ns)
        q=sampling['applied']['q'];full=self.rng.random(166700)<C.NOISE_P
        noise=np.flatnonzero(full[C.nodes]).tolist()
        nh=hashlib.sha256(np.packbits(full[C.nodes].astype(np.uint8),bitorder='little').tobytes()).hexdigest()
        qh=C.canonical_hash(q);events=encode_inputs(q,noise,qh,nh)
        if attempt_log:attempt_log(dict(kind='ADOPTED_INPUT',generation=self.adapter.generation,
            model_step=k,q_applied=q,noise_local=noise,q_sha256=qh,noise_sha256=nh,sampling=sampling))
        try:
            response=self.adapter.transact(self.adapter.generation,k,q,noise,qh,nh,True)
            dn=C.SH.DNFrame(frame_id=k,timestamp_s=k*C.DT,dt_s=C.DT,slots=tuple(response['slots']),
                source_id='CandidateBIntegerClosedLoop',replay_id='MVP_DEMO_V1',stimulus_state='CLOSED_LOOP',source_timestep=k)
            pp=self.pre.step(dn);drive,mapping=self.mapper.map(dn,pp,k)
            body,_,_=self.bodyrt.step(drive,self.body);bd=C.body_dict(body)
            if not bd['valid'] or any(not math.isfinite(x) for key in ('position_xyz','orientation_wxyz','linear_velocity_xyz','angular_velocity_xyz') for x in bd[key]):raise RuntimeError('nonfinite body')
            self.k+=1;self.body=body
            return dict(kind='VALIDATED_RESULT',backend=self.backend,generation=self.adapter.generation,
                physical_generation=getattr(self.adapter,'hardware_generation',None),model_step=k,model_time_s=k*.02,dt_s=.02,
                q_applied=q,q_sha256=qh,noise_local=noise,noise_sha256=nh,input_events=events,
                sampling=sampling,neural_state=response['states'],dn_slots=response['slots'],
                preprocessor={n:float(v) for n,v in pp.items()},mapping={n:float(v) for n,v in mapping.items()},
                motor_drive_simulated=C.drive_dict(drive),body_simulated=bd,
                started_ns=start,validated_ns=time.monotonic_ns(),actuator_enabled=False,
                input_capture_status='UNKNOWN_EXPOSURE',motion_eligible=False)
        except Exception as exc:self.fault=repr(exc);raise

def hardware_runtime(config,evidence,cancel,recover_session=None):
    """Never called by offline tests; exact existing authority guard precedes port open."""
    import json,secrets
    from mvp_link import MVPClient
    from uart_windows import WindowsPort
    from mvp_authority import claim_scope
    lease=claim_scope(config['approval'],config['host_candidate_sha256'])
    deadline=lease['started_ns']+1795_000_000_000 # reserve cleanup/report time inside the 1800s scope
    port=WindowsPort.open_approved(config['identity'],2000000,config['approval'],config['receipt'],evidence)
    try:
        if recover_session:
            old=MVPClient(port,recover_session,cancel=cancel,scope_deadline_ns=deadline);old.claim();old.reset();old.release()
            evidence.record('EXPLICIT_OLD_OWNED_SESSION_RESET',old_session=recover_session,
                note='Host model, RNG and postprocessor restart from zero in a new session')
        client=MVPClient(port,secrets.randbelow(0xffffffff)+1,cancel=cancel,scope_deadline_ns=deadline);client.claim()
        adapter=FpgaAdapter(UartNeuralTransport(client),loaded_sha=json.loads((ROOT/'BUILD_READY.json').read_text())['bit_sha256'],load_receipt=config['receipt'])
        return NeuralRuntime(adapter,'FPGA_UART')
    except Exception:port.close();raise
