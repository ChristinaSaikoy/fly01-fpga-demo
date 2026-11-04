"""Verify a retained manifest without executing or changing delivery files."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat


def linked(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def verify(root, manifest):
    root = Path(root).absolute()
    manifest = Path(manifest).absolute()
    if linked(root) or not root.is_dir():
        raise ValueError('Root is not an ordinary directory')
    data = json.loads(manifest.read_text(encoding='utf-8'))
    rows = data.get('files') if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError('Empty or unsupported manifest')
    expected = set()
    for row in rows:
        name = row.get('path') if isinstance(row, dict) else None
        if not isinstance(name, str) or not name or '\\' in name or ':' in name:
            raise ValueError('Invalid manifest path')
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or relative.as_posix() != name:
            raise ValueError('Escaping or non-canonical path: ' + name)
        if name in expected:
            raise ValueError('Repeated path: ' + name)
        expected.add(name)
        if type(row.get('bytes')) is not int or row['bytes'] < 0:
            raise ValueError('Invalid byte count')
        if not isinstance(row.get('sha256'), str) or not re.fullmatch('[a-f0-9]{64}', row['sha256']):
            raise ValueError('Invalid SHA256')
        path = root.joinpath(*relative.parts)
        for parent in [path, *path.parents]:
            if parent == root:
                break
            if linked(parent):
                raise ValueError('Link or reparse point: ' + name)
        if not path.resolve().is_relative_to(root.resolve()) or not path.is_file() or path == manifest:
            raise ValueError('Missing or invalid file: ' + name)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if path.stat().st_size != row['bytes'] or digest != row['sha256']:
            raise ValueError('Size/hash mismatch: ' + name)
    actual = set()
    for path in root.rglob('*'):
        if linked(path):
            raise ValueError('Unexpected link or reparse point')
        if path.is_file() and path != manifest:
            actual.add(path.relative_to(root).as_posix())
    if actual != expected:
        raise ValueError('File set differs: missing=' + str(len(expected - actual)) + ', extra=' + str(len(actual - expected)))
    return dict(status='MANIFEST_MATCH', files=len(expected), hardware='NONE', authenticity='NOT_PROVEN')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.root, args.manifest)
    except (ValueError, OSError) as error:
        print(json.dumps(dict(status='REJECTED', reason=str(error)), ensure_ascii=True))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
