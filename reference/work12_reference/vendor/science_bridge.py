"""Portable host science integration. Byte-identical source; plumbing-only AST cuts."""
import ast
import hashlib
import json
from pathlib import Path
import sys
import types
import numpy as np
from packed10 import make_packet
from science_loader import BUNDLE, load, reference

C = reference()


def load_live():
    path = BUNDLE/'tasks/WORK-01/edge_live/runtime.py'
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    tree.body = [node for node in tree.body if not
                 (isinstance(node, ast.ImportFrom) and node.module == 'work_utils') and not
                 (isinstance(node, ast.FunctionDef) and node.name == 'load_reference') and not
                 (isinstance(node, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == 'dont_write_bytecode' for t in node.targets)) and not
                 (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and
                  isinstance(node.value.func, ast.Attribute) and node.value.func.attr == 'insert')]
    module = types.ModuleType('o8_portable_live')
    module.__file__ = str(path)
    module.load_reference = lambda: C
    sys.modules[module.__name__] = module
    exec(compile(tree, str(path), 'exec'), module.__dict__)
    return module


reference_live = load_live()


def o7_classes():
    """Keep exact validated scientific class bodies; do not import old device stack."""
    path = BUNDLE/'tasks/WORK-04/o7_transport/host/adapter.py'
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    names = {'Rejected', 'BackendFault', 'integer', 'encode_inputs', 'CounterDifferencer',
             'MockNeuralTransport', 'FpgaAdapter', 'EdgeFpgaRuntime'}
    tree.body = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names]
    namespace = dict(C=C, reference=reference_live, np=np, hashlib=hashlib, Path=Path, json=json,
                     make_packet=make_packet, time=__import__('time'), math=__import__('math'), BIT_SHA='UNBUILT_NOT_AUTHORIZED')
    ready = Path(__file__).resolve().parent.parent/'BUILD_READY.json'
    if ready.exists():
        namespace['BIT_SHA'] = json.loads(ready.read_text(encoding='utf-8'))['bit_sha256']
    exec(compile(tree, str(path), 'exec'), namespace)
    return namespace


_classes = o7_classes()
FpgaAdapter = _classes['FpgaAdapter']
EdgeFpgaRuntime = _classes['EdgeFpgaRuntime']
MockNeuralTransport = _classes['MockNeuralTransport']
encode_inputs = _classes['encode_inputs']


class UartNeuralTransport:
    origin = 'FPGA_UART_HARDWARE_CANDIDATE_UNACCEPTED'
    def __init__(self, client):
        self.client = client

    def reset(self, logical_generation):
        physical = self.client.reset()
        self.logical_generation = logical_generation
        return dict(ok=True, generation=logical_generation, hardware_generation=physical, status=2,
                    error_status=0, completed_id=0xFFFFFFFF, reset_guard_complete=True)

    def step(self, generation, frame, q, noise, events, input_sha, noise_sha, audit):
        return self.formal(generation, frame, events, 1, audit, input_sha, noise_sha)

    def formal(self, generation, frame, events, enable=1, audit=True, input_sha=None, noise_sha=None):
        import time
        if generation != self.logical_generation or frame != self.client.next_frame:
            raise ValueError('logical generation/frame mismatch')
        started = time.monotonic_ns()
        from host_diagnostics import measured_packet
        packet = measured_packet(self.client.port.evidence,
            lambda: make_packet(self.client.generation, frame, events, enable))
        got = self.client.frame(packet, 0 if audit else 1)
        validated = time.monotonic_ns()
        self.client.ack()
        finished = time.monotonic_ns()
        got.update(ok=True, generation=generation, interface_version='F1070001',
                   input_sha256=input_sha, noise_sha256=noise_sha,
                   timings_ms={'frame_response_validation':(validated-started)/1e6,
                               'ack_confirmation':(finished-validated)/1e6},
                   uart_timestamps_ns={'started':started, 'response_validated':validated, 'ack_confirmed':finished})
        return got

    def close(self):
        self.client.port.close()

    def abort(self):
        self.client.port.close()


def harness():
    """Reuse exact audit / fixed-epoch online / mode comparison functions."""
    path = BUNDLE/'tasks/WORK-04/o7_transport/host/run_candidate.py'
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    names = {'dump', 'audit', 'live', 'modes_equivalent', 'bounded_fault_checks'}
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    # The old bounded helper's one import resolves to this module's exact same class.
    for node in tree.body:
        if node.name == 'bounded_fault_checks':
            node.body = [item for item in node.body if not isinstance(item, ast.ImportFrom) or item.module != 'adapter']
        if node.name == 'live':
            # Evidence-only instrumentation, no change to science or scheduling math.
            class Instrument(ast.NodeTransformer):
                def visit_ClassDef(self, item):
                    return item  # Target HTTP handler is not the model frame clock.
                def visit_Assign(self, item):
                    if any(isinstance(target, ast.Name) and target.id == 'start' for target in item.targets):
                        extra = ast.parse("record_online_begin(adapter, k, start, scheduled, deadline)").body[0]
                        return [item, ast.copy_location(extra, item)]
                    return item
                def visit_Expr(self, item):
                    if isinstance(item.value, ast.Call) and isinstance(item.value.func, ast.Attribute) and isinstance(item.value.func.value, ast.Name) and item.value.func.value.id == 'timings' and item.value.func.attr == 'append':
                        extra = ast.parse("record_online_publication(adapter, k, timing)").body[0]
                        return [ast.copy_location(extra, item), item]
                    return item
            Instrument().visit(node)
    namespace = dict(_classes, reference=reference_live, np=np, json=json, Path=Path,
                     sys=sys, subprocess=__import__('subprocess'), threading=__import__('threading'),
                     __file__=str(Path(__file__).resolve().parent/'science_bridge.py'),
                     BaseHTTPRequestHandler=__import__('http.server', fromlist=['BaseHTTPRequestHandler']).BaseHTTPRequestHandler,
                     ThreadingHTTPServer=__import__('http.server', fromlist=['ThreadingHTTPServer']).ThreadingHTTPServer,
                     record_online_begin=record_online_begin, record_online_publication=record_online_publication)
    ast.fix_missing_locations(tree)
    exec(compile(tree, str(path), 'exec'), namespace)
    return namespace


def record_online_begin(adapter, frame, start, scheduled, deadline):
    if hasattr(adapter.transport, 'client'):
        client = adapter.transport.client
        client.port.evidence.record('ONLINE_FRAME_BEGIN', session=client.session, generation=client.generation,
                                    frame=frame, start_perf_counter=start, scheduled_perf_counter=scheduled,
                                    deadline_perf_counter=deadline)


def record_online_publication(adapter, frame, timing):
    if hasattr(adapter.transport, 'client'):
        client = adapter.transport.client
        client.port.evidence.record('ONLINE_PUBLICATION', session=client.session, generation=client.generation,
                                    frame=frame, timing=timing)
