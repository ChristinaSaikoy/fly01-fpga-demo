"""Offline package verification. Does not connect to devices or start the panel."""
from pathlib import Path
import argparse,json,hashlib,subprocess,sys
P=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--tests',action='store_true');a=p.parse_args()
 m=json.loads((P/'MANIFEST.json').read_text(encoding='utf-8'))
 for row in m['files']:
  f=P/row['path']
  if not f.resolve().is_relative_to(P):raise ValueError('Path escape')
  if not f.is_file() or f.stat().st_size!=row['bytes'] or hashlib.sha256(f.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Changed input: '+row['path'])
 print(json.dumps({'status':'MANIFEST_MATCH','files':len(m['files']),'hardware':'NONE'}),flush=True)
 if a.tests:
  subprocess.run([sys.executable,'-B',str(P/'reference/desktop/identity.py')],check=True)
  import tempfile
  with tempfile.TemporaryDirectory(prefix='fly01_offline_') as d:
   subprocess.run([sys.executable,'-B',str(P/'reference/desktop/offline_checks.py'),'--output',str(Path(d)/'checks')],check=True)
  subprocess.run(['node','--test',*[str(f) for f in sorted((P/'panel/tests').glob('*.test.mjs'))]],cwd=P/'panel',check=True)
 return 0
if __name__=='__main__':raise SystemExit(main())
