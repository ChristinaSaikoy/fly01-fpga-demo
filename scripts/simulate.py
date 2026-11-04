"""Short simulation of the exact R13 source closure. Never accesses hardware."""
import argparse,json,os,shutil,subprocess,tempfile
from pathlib import Path
P=Path(__file__).resolve().parents[1];F=P/'fpga'
def run(output):
 cfg=json.loads((F/'fpga-auto-r13.json').read_text(encoding='utf-8'))
 for name in cfg['extra_files']:
  target=output/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(F/name,target)
 exe=os.environ.get('FLY01_IVERILOG') or shutil.which('iverilog');vvp=os.environ.get('FLY01_VVP') or shutil.which('vvp')
 if not exe or not vvp:raise RuntimeError('Set FLY01_IVERILOG and FLY01_VVP, or put Icarus on PATH')
 compile=[exe,'-g2012','-s',cfg['tb_top'],'-o',str(output/'r13.vvp'),*[str(F/x) for x in cfg['rtl']+cfg['tb']]]
 a=subprocess.run(compile,cwd=output,capture_output=True,text=True);(output/'compile.log').write_text(a.stdout+a.stderr,encoding='utf-8');a.check_returncode()
 with (output/'simulation.log').open('w',encoding='utf-8') as log:
  b=subprocess.run([vvp,'-i',str(output/'r13.vvp')],cwd=output,stdout=log,stderr=subprocess.STDOUT,text=True,timeout=300)
 b.check_returncode()
 if cfg['pass_marker'] not in (output/'simulation.log').read_text(encoding='utf-8',errors='replace'):raise RuntimeError('Simulation pass marker missing')
 print(json.dumps({'status':'PASS','marker':cfg['pass_marker'],'hardware':'NONE'}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path);a=p.parse_args()
 if a.output:a.output.mkdir(parents=True,exist_ok=False);run(a.output.resolve())
 else:
  with tempfile.TemporaryDirectory(prefix='fly01_sim_') as d:run(Path(d))
