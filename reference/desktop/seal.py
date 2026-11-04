"""Record local source identity only. Never grants a device permission."""
import json
from identity import ROOT, OLD, BIT, BIT_SHA, FORMAL_ROOT, files, candidate, sha

def seal():
    delivery=json.loads((OLD/'DELIVERY.json').read_text(encoding='utf-8'))
    for name,digest in delivery['files'].items():
        if sha(OLD/name)!=digest:raise RuntimeError('Original WORK12 source changed: '+name)
    if sha(BIT)!=BIT_SHA:raise RuntimeError('Historical production bit changed')
    external={str(FORMAL_ROOT/'host/acceptance_worker.py'):sha(FORMAL_ROOT/'host/acceptance_worker.py')}
    inputs=FORMAL_ROOT/'formal_inputs'
    external[str(inputs/'INPUT_IDENTITY.json')]=sha(inputs/'INPUT_IDENTITY.json')
    for name,digest in json.loads((inputs/'INPUT_IDENTITY.json').read_text(encoding='utf-8')).items():
        if sha(inputs/name)!=digest:raise RuntimeError('Formal input changed: '+name)
        external[str(inputs/name)]=digest
    external={str(__import__('pathlib').Path(k).relative_to(ROOT.parent)).replace('\\','/'):v for k,v in external.items()}
    value=dict(candidate_sha256=candidate(),files=files(),external_inputs=external,
        previously_consumed_suite_ids=[],origin='WORK13_NEW_HOST_READY_FOR_BOARD_NOT_HARDWARE_ACCEPTANCE',
        base_candidate_sha256=delivery['candidate_sha256'],bit_sha256=BIT_SHA,requires_new_combined_confirmation=True,
        relocation_status='TEAM_PORTABLE_LOCAL_BY05_CANDIDATE_NOT_BOARD_ACCEPTANCE',
        known_cancel_race='FIXED_OFFLINE_START_STOP_SERIALIZED',
        continuation_mode='TARGETED_INTERACTION_CONTINUATION_21_FULL_SNAPSHOTS')
    # This is only the new WORK13 development lock; no old sealed files are edited.
    (ROOT/'CANDIDATE_LOCK.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(candidate_sha256=value['candidate_sha256'],files=len(value['files']),external_inputs=len(external))))

if __name__=='__main__':seal()
