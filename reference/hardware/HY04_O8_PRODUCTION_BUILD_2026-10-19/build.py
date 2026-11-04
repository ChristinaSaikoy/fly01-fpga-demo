"""Portable production O8 entry. Verify-only by default; never programs hardware."""
import argparse,datetime,hashlib,json,re,shutil,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def verify():
    files=json.loads((ROOT/'FILES_SHA256.json').read_text(encoding='utf-8'))
    for name,value in files.items():
        p=(ROOT/name).resolve();assert p.is_relative_to(ROOT) and sha(p)==value,name
    # Initialization closure, not an assertion that all testbenches were rebuilt.
    for file in (ROOT/'src').rglob('*.sv'):
        for name in re.findall(r'"(generated/[^"]+\.mem)"',file.read_text(encoding='utf-8')):
            # Legacy unused parameter defaults are superseded by banked ROMs.
            if name in ('generated/syn_dst.mem','generated/syn_weight_w16f14.mem'):continue
            assert (ROOT/name).is_file(),name
    assert len(list((ROOT/'generated').rglob('*.mem')))==35
    assert not any(x in (ROOT/'build.tcl').read_text() for x in ('D:/FPGA-AUTO','D:\\FPGA-AUTO'))
    return len(files)
def main():
    p=argparse.ArgumentParser();p.add_argument('--build',action='store_true');p.add_argument('--vivado');a=p.parse_args()
    count=verify()
    if not a.build:print(json.dumps(dict(input_integrity='PASS',files=count,build='NOT_RUN',hardware='NONE')));return
    if not a.vivado or not Path(a.vivado).is_file():raise ValueError('--vivado requires local Vivado 2025.2 executable/bat')
    run=ROOT/'outputs'/datetime.datetime.now().strftime('%Y%m%dT%H%M%S%f');run.mkdir(parents=True,exist_ok=False)
    for d in ('src','generated','ip'):shutil.copytree(ROOT/d,run/d)
    for f in ('build.tcl','constraints.xdc'):shutil.copy2(ROOT/f,run/f)
    started=time.monotonic()
    with (run/'process.log').open('wb') as log:
        proc=subprocess.Popen([a.vivado,'-mode','batch','-source','build.tcl','-notrace'],cwd=run,stdout=log,stderr=subprocess.STDOUT)
        try:code=proc.wait(timeout=2400)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True);code=-1
    text=(run/'process.log').read_text(encoding='utf-8',errors='replace')
    errors=[l for l in text.splitlines() if re.match(r'^\s*(?:ERROR|CRITICAL WARNING):',l)]
    bit=run/'HY04_O8_CANDIDATE_NOT_PROGRAMMED.bit'
    metrics=dict(l.split('=',1) for l in (run/'metrics.txt').read_text().splitlines() if '=' in l) if (run/'metrics.txt').exists() else {}
    reports=('utilization_route.rpt','timing_summary.rpt','drc.rpt','check_timing.rpt','cdc_route.rpt','bus_skew.rpt')
    ok=code==0 and not errors and 'HY04_PRODUCTION_BUILD_DONE' in text.splitlines() and bit.exists() and bit.stat().st_size>0
    ok=ok and all((run/f).is_file() for f in reports) and float(metrics.get('WNS','-1'))>=0 and float(metrics.get('WHS','-1'))>=0 and metrics.get('DRC_BLOCKERS')=='0'
    result=dict(status='SUBMITTED_FOR_REVIEW' if ok else 'PARTIAL_WITH_BLOCKERS',wall_s=time.monotonic()-started,
        exit_code=code,errors=errors,metrics=metrics,bit_sha256=sha(bit) if bit.exists() else None,
        hardware='NONE',programming='NOT_AUTHORIZED',warning_count=sum('WARNING:' in l for l in text.splitlines()))
    (run/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
