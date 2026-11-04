"""Load byte-identical frozen science with path relocation, not model changes."""
import ast
import hashlib
import json
from pathlib import Path as NativePath
import sys
import types

BUNDLE = NativePath(__file__).resolve().parent/'science'


def relocated_path(value='', *args):
    if isinstance(value, str):
        normalized = value.replace('\\', '/')
        prefix = 'D:/FPGA-AUTO'
        bundle_prefix = str(BUNDLE).replace('\\', '/')
        if normalized.startswith(bundle_prefix+'/') or normalized == bundle_prefix:
            return NativePath(value, *args)
        if normalized == prefix or normalized.startswith(prefix+'/'):
            value = BUNDLE/normalized[len(prefix):].lstrip('/')
    return NativePath(value, *args)


def verify_bundle():
    manifest = json.loads((BUNDLE/'BUNDLE_03.json').read_text(encoding='utf-8'))
    for row in manifest['files']:
        path = BUNDLE/row['path']
        if path.stat().st_size != row['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise RuntimeError('portable frozen identity mismatch: '+row['path'])
    return manifest


def load(name, path, *, geometry=False, skip_geometry_assignment=False):
    path = NativePath(path)
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    # Replace only path resolution/import driver plumbing. Function math stays intact.
    body = []
    for node in tree.body:
        if geometry and not isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)):
            continue
        if skip_geometry_assignment and isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'BG' for t in node.targets):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == 'pathlib':
            node.names = [item for item in node.names if item.name != 'Path']
            if not node.names:
                continue
        body.append(node)
    tree.body = body
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.Path = relocated_path
    module.load_module = load
    sys.modules[name] = module
    if skip_geometry_assignment:
        module.BG = load('portable_geometry', BUNDLE/'tasks/BODY-0A2D/validate_body_0a2d.py', geometry=True)
        # The original function declaration is plumbing, overridden before module imports.
        tree.body = [node for node in tree.body if not isinstance(node, ast.FunctionDef) or node.name != 'load_module']
    exec(compile(tree, str(path), 'exec'), module.__dict__)
    return module


def reference():
    verify_bundle()
    return load('o8_portable_frozen_reference', BUNDLE/'tasks/DEMO-1-IMPLEMENTATION/closed_loop_execute.py',
                skip_geometry_assignment=True)
