"""仅检查当前交付文件清单，不运行相机/串口/FPGA/电机。"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parent


def ignored(path):
    return path.name == 'PACKAGE_MANIFEST.json' or '__pycache__' in path.parts or path.suffix == '.pyc' or path.parts[0] == 'runs'


def main():
    try:
        manifest = json.loads((ROOT/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
        paths = set()
        for row in manifest['files']:
            relative = PurePosixPath(row['path'])
            if relative.is_absolute() or '..' in relative.parts or ':' in row['path'] or '\\' in row['path']:
                raise ValueError('invalid manifest path')
            path = ROOT.joinpath(*relative.parts)
            if not path.resolve().is_relative_to(ROOT) or row['path'] in paths:
                raise ValueError('escaping or duplicate manifest path')
            paths.add(row['path'])
            data = path.read_bytes()
            if len(data) != row['size_bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
                raise ValueError('file mismatch: '+row['path'])
        actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and not ignored(p.relative_to(ROOT))}
        if paths != actual:
            raise ValueError('extra/missing files: '+str(sorted(paths.symmetric_difference(actual))))
        print('PASS: '+str(len(paths))+' delivery files verified; no hardware accessed')
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print('FAIL: '+str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
