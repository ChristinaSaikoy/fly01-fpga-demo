"""Own local loopback server only. No SSH, GUI, public port or installation."""
import socket,subprocess,time,os,json
from pathlib import Path

BIN=Path('D:/Xilinx/Vivado/2024.2/bin')
READY=Path(__file__).resolve().parent.parent/'BUILD_READY.json'
BIT=Path(json.loads(READY.read_text(encoding='utf-8'))['bit']) if READY.exists() else Path('UNBUILT_NOT_AUTHORIZED')

def child_env():
    env=os.environ.copy()
    # The agent's stripped environment lacks this standard loader prerequisite.
    env.setdefault('PROCESSOR_ARCHITECTURE','AMD64')
    return env

def stop_tree(process):
    if process is not None and process.poll() is None:
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=10)
        process.wait(timeout=10)

class OwnedServer:
    def __init__(self,out):
        self.process=None;self.log=None;self.out=out
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',3121))==0:
                raise RuntimeError('PORT_3121_OCCUPIED_NO_SHARED_SESSION')
        self.log=(out/'owned_server.log').open('x',encoding='utf-8')
        # Keep AMD's driver/DLL environment bootstrap; record wrapper exit too.
        self.process=subprocess.Popen([str(BIN/'hw_server.bat'),'-p0','-s','tcp:127.0.0.1:3121','-I86400','-L'+str(out/'hw_server_trace.log')],
            stdout=self.log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW,env=child_env())
        try:
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                if self.process.poll() is not None:raise RuntimeError('OWNED_SERVER_EXITED')
                with socket.socket() as probe:
                    if probe.connect_ex(('127.0.0.1',3121))==0:return
                time.sleep(.1)
            raise RuntimeError('OWNED_SERVER_START_TIMEOUT')
        except Exception:self.close();raise
    def close(self):
        before=None if self.process is None else self.process.poll()
        stop_tree(self.process)
        if self.log is not None:self.log.close()
        (self.out/'SERVER_LIFECYCLE.json').write_text(json.dumps({'pid':None if self.process is None else self.process.pid,
            'exit_before_owned_cleanup':before,'exit_after_cleanup':None if self.process is None else self.process.poll()},indent=2)+'\n',encoding='utf-8')

def vivado_command(script,out,args=()):
    return [str(BIN/'vivado.bat'),'-mode','batch','-notrace','-source',str(script),
        '-log',str(out/'vivado.log'),'-journal',str(out/'vivado.jou'),'-tclargs',*map(str,args)]

if __name__=='__main__':
    import datetime
    root=Path(__file__).resolve().parent
    out=root/'runs'/('preflight_'+datetime.datetime.now().strftime('%Y%m%dT%H%M%S'))
    out.mkdir(parents=True,exist_ok=False)
    server=OwnedServer(out);proc=None
    try:
        with (out/'raw.log').open('x') as log:
            proc=subprocess.Popen(vivado_command(root/'preflight.tcl',out),stdout=log,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,cwd=out,env=child_env())
            proc.wait(timeout=120)
        print(str(out));print((out/'raw.log').read_text(errors='replace'))
    finally:stop_tree(proc);server.close()
