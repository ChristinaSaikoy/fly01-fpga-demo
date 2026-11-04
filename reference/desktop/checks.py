"""Small repeatable software checks; unique output, never opens real devices."""
import argparse,hashlib,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    folder=Path(a.output);folder.mkdir(parents=True,exist_ok=False);rows=[]
    for module,cwd in [('test_mvp',ROOT),('test_host',ROOT/'vendor')]:
        started=time.monotonic();r=subprocess.run([sys.executable,'-B','-m','unittest','-v',module],cwd=cwd,capture_output=True,text=True,timeout=90)
        (folder/(module+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
        rows.append(dict(module=module,returncode=r.returncode,wall_s=time.monotonic()-started))
    (folder/'RESULT.json').write_text(json.dumps(dict(status='PASS' if all(x['returncode']==0 for x in rows) else 'FAIL',
        scope='SOFTWARE_INJECTION_AND_OLD_HOST_CHECKS_NOT_REAL_UART',jobs=rows),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(rows,indent=2));return 0 if all(x['returncode']==0 for x in rows) else 1
if __name__=='__main__':raise SystemExit(main())
