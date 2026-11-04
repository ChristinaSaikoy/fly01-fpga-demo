"""Portable, device-free checkout verification. Never creates device permissions."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tests', action='store_true')
    args = parser.parse_args()
    manifest = json.loads((REPO/'release-manifests/TEAM_SYNC_2026-10-26_SOURCES.json').read_text(encoding='utf-8'))
    for row in manifest['files']:
        path = (REPO/row['path']).resolve()
        if not path.is_relative_to(REPO):
            raise ValueError('Manifest path escapes checkout')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if path.stat().st_size != row['bytes'] or digest != row['sha256']:
            raise ValueError('Imported file changed: '+row['path'])
    subprocess.run([sys.executable, '-B', str(ROOT/'desktop/suite.py'), '--check'], check=True)
    print(json.dumps(dict(status='CHECKOUT_INPUTS_PASS', imported_files=len(manifest['files']), hardware='NONE')))
    if args.tests:
        with tempfile.TemporaryDirectory(prefix='fly01-team-check-') as temp:
            subprocess.run([sys.executable, '-B', str(ROOT/'desktop/offline_checks.py'),
                            '--output', str(Path(temp)/'checks')], check=True)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
