"""Run local injected tests and original log replay; no device access."""
import argparse
import ast
import json
import os
from pathlib import Path
import sys
import time
import unittest
from identity import ROOT, OLD, verify, sha

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--replay-old-camera',action='store_true');args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    lock=verify();jobs=[]
    delivery=json.loads((OLD/'DELIVERY.json').read_text(encoding='utf-8'))
    unchanged=[name for name in delivery['files'] if name.startswith('vendor/') or name in ('pixel.py','mvp_link.py','mvp_authority.py','actuator.py','BUILD_READY.json')]
    for name in unchanged:
        if sha(ROOT/name)!=delivery['files'][name] or sha(OLD/name)!=delivery['files'][name]:raise RuntimeError('Frozen/transport input changed: '+name)
    def neural_class(root):
        tree=ast.parse((root/'neural.py').read_text(encoding='utf-8'))
        return ast.dump(next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='NeuralRuntime'),include_attributes=False)
    if neural_class(ROOT)!=neural_class(OLD):raise RuntimeError('Neural/RNG/postprocess class changed')
    script=(ROOT/'index.html').read_text(encoding='utf-8').split('<script>',1)[1].split('</script>',1)[0]
    js=__import__('subprocess').run(['node','--check'],input=script,text=True,capture_output=True,timeout=10)
    (args.output/'javascript_syntax.log').write_text(js.stdout+js.stderr,encoding='utf-8')
    if js.returncode:raise RuntimeError('UI JavaScript syntax failed')
    for module in ('test_work13','test_start_stop_boundary','test_targeted','test_mvp','test_host'):
        suite=unittest.defaultTestLoader.loadTestsFromName(module)
        with (args.output/(module+'.log')).open('x',encoding='utf-8') as stream:
            result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
        jobs.append(dict(module=module,run=result.testsRun,passed=result.testsRun-len(result.skipped)-len(result.errors)-len(result.failures),
                         skipped=len(result.skipped),failures=len(result.failures),errors=len(result.errors),successful=result.wasSuccessful()))
    old_replay=None
    if args.replay_old_camera:
        import replay
        run=OLD.parent/'camera_preview_20261019/directshow/runs/20261019T204404_e9540915'
        old_replay=replay.replay(run)
        old_replay['scope']='OLD_SOFTWARE_CAMERA_DATA_REPLAY_NOT_NEW_FPGA_TEST'
    outcome=dict(status='PASS' if all(j['successful'] for j in jobs) else 'FAIL',candidate_sha256=lock['candidate_sha256'],
                 jobs=jobs,old_camera_replay=old_replay,unchanged_frozen_and_transport_files=len(unchanged),neural_class_ast='IDENTICAL',
                 ui_javascript_syntax='PASS',hardware_operations='NONE',actual_fpga_test='NOT_RUN',strict_50hz='OLD_FAIL_NOT_RETESTED')
    with (args.output/'RESULT.json').open('x',encoding='utf-8') as stream:json.dump(outcome,stream,indent=2)
    print(json.dumps(outcome,indent=2));return 0 if outcome['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
