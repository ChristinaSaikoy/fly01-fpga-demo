"""Host candidate closure; no device access or authority creation."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BIT = ROOT.parent/'hardware/artifacts/production_o8.bit'
BIT_SHA = '93399a70892ece88300af96cd2dd27566b683f9eeecc41f394465182b5786eb4'
OLD = ROOT.parent/'work12_reference'
FORMAL_ROOT = ROOT.parent/'formal_reference'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def files():
    paths = list(ROOT.glob('*.py')) + list(ROOT.glob('*.tcl')) + [ROOT/'index.html', ROOT/'BUILD_READY.json']
    paths += [p for p in (ROOT/'vendor').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths)}

def candidate():
    return hashlib.sha256(json.dumps(files(), sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def verify():
    lock = json.loads((ROOT/'CANDIDATE_LOCK.json').read_text(encoding='utf-8'))
    if lock.get('files') != files() or lock.get('candidate_sha256') != candidate():
        raise RuntimeError('WORK13 candidate closure changed')
    if sha(BIT) != BIT_SHA:
        raise RuntimeError('Historical production bit changed')
    for name, digest in lock['external_inputs'].items():
        if sha(ROOT.parent/name) != digest:
            raise RuntimeError('Frozen external dependency changed: '+name)
    return lock

if __name__ == '__main__':
    print(json.dumps(dict(status='OFFLINE_IDENTITY_PASS', candidate_sha256=verify()['candidate_sha256'], bit_sha256=BIT_SHA)))
