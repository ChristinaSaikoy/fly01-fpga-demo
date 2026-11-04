"""Production O8 seed0/ownership simulation only; no synth or board access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

ROOT=Path(__file__).resolve().parent

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def verify(production):
    manifest=json.loads((ROOT/'FILES_SHA256.json').read_text(encoding='utf-8'))
    for name,digest in manifest.items():
        if sha(ROOT/name)!=digest:raise RuntimeError('Supplement changed: '+name)
    for name,digest in json.loads((production/'FILES_SHA256.json').read_text(encoding='utf-8')).items():
        if sha(production/name)!=digest:raise RuntimeError('Production input changed: '+name)
    vector=ROOT/'sim/vectors/l3_seed0'
    legacy=json.loads((vector/'manifest.json').read_text(encoding='utf-8'))
    for name,entry in legacy['files'].items():
        # Existing Windows validation text has CRLF; legacy generator hashes LF.
        canonical=(vector/name).read_bytes().replace(b'\r\n',b'\n')
        if hashlib.sha256(canonical).hexdigest()!=entry['sha256'] or len(canonical)!=entry['bytes']:
            raise RuntimeError('Legacy seed0 vector mismatch: '+name)
    return dict(supplement_files=len(manifest),vector_seed=0,vector_steps=300,
                vector_check='RAW_COPY_HASH_AND_LEGACY_LF_CANONICAL_HASH',rtl_changed=False)

def main():
    p=argparse.ArgumentParser();p.add_argument('--production',type=Path,default=ROOT.parent/'HY04_O8_PRODUCTION_BUILD_2026-10-19')
    p.add_argument('--sim',action='store_true');p.add_argument('--backend',choices=['xsim','icarus','both'],default='xsim')
    p.add_argument('--vivado-bin',type=Path,default=Path('D:/AMDDesignTools/2025.2/Vivado/bin'))
    p.add_argument('--iverilog',default=shutil.which('iverilog') or 'iverilog');p.add_argument('--vvp',default=shutil.which('vvp') or 'vvp')
    p.add_argument('--output',type=Path);p.add_argument('--seal-inputs',action='store_true');p.add_argument('--timeout-s',type=int,default=240);a=p.parse_args()
    if a.seal_inputs:
        paths=[ROOT/'run_sim.py',ROOT/'run_all.tcl']+[f for f in (ROOT/'sim').rglob('*') if f.is_file()]
        with (ROOT/'FILES_SHA256.json').open('x',encoding='utf-8') as f:json.dump({str(x.relative_to(ROOT)).replace('\\','/'):sha(x) for x in paths},f,indent=2)
    ready=verify(a.production)
    if not a.sim:print(json.dumps(dict(status='INPUTS_VERIFIED_SIMULATION_NOT_RUN',**ready)));return 0
    output=a.output or ROOT/'outputs'/time.strftime('%Y%m%dT%H%M%S')
    output.mkdir(parents=True,exist_ok=False)
    backends=['icarus','xsim'] if a.backend=='both' else [a.backend];results=[]
    for backend in backends:
        for top,marker,count in [('tb_o8_ownership','O8_OWNERSHIP_PASS checks=8',8),('tb_o8_full','O8_FULL_PASS seed=0 steps=300',300)]:
            run=output/(backend+'_'+top);run.mkdir();shutil.copytree(a.production/'generated',run/'generated');shutil.copytree(ROOT/'sim',run/'sim')
            shutil.copyfile(ROOT/'run_all.tcl',run/'run_all.tcl')
            sources=sorted((a.production/'src/core').glob('*.sv'))+[a.production/'src/wrapper'/n for n in ('fly01_o7_transport.sv','fly01_o7_endpoint.sv','fly01_o8_byte_endpoint.sv','fly01_o8_debug_axi.sv')]+[run/'sim'/(top+'.sv')]
            env=dict(os.environ,PROCESSOR_ARCHITECTURE='AMD64')
            def command(argv,label):
                with (run/(label+'.command.json')).open('x',encoding='utf-8') as out:json.dump(list(map(str,argv)),out)
                with (run/(label+'.log')).open('xb') as log:
                    child=subprocess.Popen(list(map(str,argv)),cwd=run,env=env,stdout=log,stderr=subprocess.STDOUT)
                    try:child.wait(timeout=a.timeout_s)
                    except subprocess.TimeoutExpired:
                        if os.name=='nt':subprocess.run(['taskkill.exe','/PID',str(child.pid),'/T','/F'],capture_output=True,timeout=5)
                        else:child.kill()
                        child.wait(timeout=5)
                        raise
                text=(run/(label+'.log')).read_text(encoding='utf-8',errors='replace')
                if child.returncode or re.search(r'(^|\n)\s*(?:ERROR:|FATAL:|Fatal:)|couldn.t read file',text):raise RuntimeError(label+' failed; see '+str(run))
                return text
            row=dict(backend=backend,top=top,status='FAIL',scope='BEHAVIORAL_NOT_BOARD_OR_TIMING')
            try:
                if backend=='icarus':
                    command([a.iverilog,'-g2012','-s',top,'-I',run,'-o',run/'test.vvp',*sources],'compile')
                    text=command([a.vvp,run/'test.vvp'],'simulate')
                else:
                    command([a.vivado_bin/'xvlog.bat','-sv','-i',run,*sources],'xvlog')
                    command([a.vivado_bin/'xelab.bat','-debug','typical','-s','test_snapshot','work.'+top],'xelab')
                    text=command([a.vivado_bin/'xsim.bat','test_snapshot','-tclbatch','run_all.tcl'],'simulate')
                if marker not in text or re.search(r'\b(?:FATAL|Fatal|Error):',text):raise RuntimeError('Missing PASS or unexpected error')
                if top=='tb_o8_full' and len(re.findall(r'^O8_STEP_PASS ',text,re.M))!=count:raise RuntimeError('Seed0 step count mismatch')
                if top=='tb_o8_ownership' and len(re.findall(r'^O8_OWNERSHIP_CASE_PASS ',text,re.M))!=count:raise RuntimeError('Ownership case count mismatch')
                row['status']='PASS';row['checks']=count
            except Exception as exc:row['error']=repr(exc)
            results.append(row)
            with (run/'RESULT.json').open('x',encoding='utf-8') as out:json.dump(row,out,indent=2)
            if row['status']!='PASS':break
        if results[-1]['status']!='PASS':break
    result=dict(status='PASS' if len(results)==2*len(backends) and all(r['status']=='PASS' for r in results) else 'FAIL',
                inputs=ready,jobs=results,hardware='NONE',timing='NOT_TESTED',full_5400='NOT_RUN_BY_THIS_SUPPLEMENT')
    with (output/'RESULT.json').open('x',encoding='utf-8') as out:json.dump(result,out,indent=2)
    print(json.dumps(result,indent=2));return 0 if result['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
