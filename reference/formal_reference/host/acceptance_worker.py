"""Prepared full UART worker. MUST run under approved whole-suite watchdog.

No programming here. Parent timer includes earlier exact programming/opening and
this worker, reports and cleanup. Standalone execution without scope token fails.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import time
import traceback

from uart_host import Client, EvidenceLog, LinuxPort
from host_diagnostics import DiagnosticEvidenceLog, MeasuredClient
from science_bridge import C, FpgaAdapter, UartNeuralTransport, harness


def dump(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def formal(adapter, output):
    inputs = Path(__file__).resolve().parent.parent/'formal_inputs'
    identities = json.loads((inputs/'INPUT_IDENTITY.json').read_text(encoding='utf-8'))
    for name, digest in identities.items():
        if hashlib.sha256((inputs/name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('formal input identity '+name)
    completed = 0
    started = time.monotonic()
    with (output/'formal_capture.jsonl').open('x', encoding='utf-8') as log:
        for scope, repeat, name in [('PREFIX1', 0, 'single'), ('PREFIX20', 0, 'sequence20')]+[('FORMAL', i, 'formal') for i in range(1, 4)]:
            expected = iter(csv.reader((inputs/(name+'_expected.csv')).open(encoding='utf-8')))
            seed = condition = None
            for row in csv.reader((inputs/(name+'_plan.csv')).open(encoding='utf-8')):
                if row[0] == 'CASE':
                    seed, condition = map(int, row[1:3])
                    adapter.reset()
                    continue
                if row[0] != 'STEP' or seed is None:
                    raise RuntimeError('formal plan syntax')
                frame, enable, count = map(int, row[1:4])
                events = [int(x, 16) for x in row[4:]]
                if len(events) != count:
                    raise RuntimeError('formal plan count')
                got = adapter.transport.formal(adapter.generation, frame, events, enable, True)
                golden = next(expected)
                actual = ['STEP', str(seed), str(condition), str(frame), str(got['completed_id'])]
                actual += [str(got[key]) for key in ('acc_sat', 'state_sat', 'overflow', 'drop', 'cycles')]
                actual += [f'{int(value)&0xFFFFFFFF:08X}' for value in got['states']+got['counts']]
                if len(actual) != 513 or len(golden) != 513:
                    raise RuntimeError('formal complete read count')
                for index, (a, b) in enumerate(zip(actual, golden)):
                    if index != 9 and a.upper() != b.upper():
                        raise RuntimeError(f'FIRST_DIVERGENCE {scope}/{repeat}/{seed}/{condition}/{frame}/{index}')
                log.write(json.dumps(dict(scope=scope, repeat=repeat, seed=seed, condition=condition,
                                          frame=frame, dn_enable=enable, events=events, snapshot=got), separators=(',', ':'))+'\n')
                log.flush()
                completed += 1
            if next(expected, None) is not None:
                raise RuntimeError('formal missing expected rows')
    if completed != 5421:
        raise RuntimeError('formal frame coverage')
    result = dict(origin='ACTUAL_FPGA_UART', status='PASS', formal_steps=5400, prefix_steps=21,
                  full_words=530, steps=completed, wall_seconds=time.monotonic()-started)
    dump(output/'FORMAL_RESULT.json', result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--approval', type=Path, required=True)
    parser.add_argument('--load-receipt', type=Path, required=True)
    parser.add_argument('--identity', type=Path, required=True)
    parser.add_argument('--baud', type=int, choices=[1000000, 2000000], default=2000000)
    parser.add_argument('--session', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    auth = json.loads(args.approval.read_text(encoding='utf-8'))
    if not os.environ.get('FLY01_UART_SUITE_ID') or auth.get('suite_id') != os.environ['FLY01_UART_SUITE_ID']:
        raise RuntimeError('owned whole-suite watchdog scope token missing')
    args.output.mkdir(parents=True, exist_ok=False)
    evidence = DiagnosticEvidenceLog(args.output/'wire', 'ACTUAL_FPGA_UART')
    port = None
    result = dict(status='PARTIAL_WITH_BLOCKERS', actual_origin='ACTUAL_FPGA_UART', controller_review='PENDING')
    started = time.monotonic()
    try:
        port_class = LinuxPort
        if os.name == 'nt':
            from uart_windows import WindowsPort
            port_class = WindowsPort
        port = port_class.open_approved(json.loads(args.identity.read_text(encoding='utf-8')), args.baud,
                                       args.approval, args.load_receipt, evidence)
        client = MeasuredClient(port, args.session)
        info = client.claim()
        if info['baud'] != args.baud:
            raise RuntimeError('board and host baud mismatch')
        result['capabilities'] = info
        transport = UartNeuralTransport(client)
        adapter_receipt=args.load_receipt
        current_load=json.loads(args.load_receipt.read_text(encoding='utf-8'))
        if current_load.get('programming_status')=='REUSED_AFTER_READONLY_IDENTITY':
            # The frozen adapter still checks the ACTUAL prior programming receipt,
            # not a newly invented programming PASS. Fresh reuse scope is checked above.
            adapter_receipt=Path(auth['prior_load_receipt_path'])
            if hashlib.sha256(adapter_receipt.read_bytes()).hexdigest()!=auth['prior_receipt_sha256']:
                raise RuntimeError('PRIOR_ACTUAL_PROGRAM_RECEIPT_CHANGED')
        adapter = FpgaAdapter(transport, loaded_sha=auth['bit_sha256'], load_receipt=adapter_receipt)
        result['formal'] = formal(adapter, args.output)
        adapter.reset()
        helpers = harness()
        result['audit'] = helpers['audit'](adapter, args.output)
        result['modes'] = helpers['modes_equivalent'](adapter, args.output)
        result['online'] = []
        for index in range(3):
            directory = args.output/f'online_{index+1}'
            directory.mkdir()
            result['online'].append(helpers['live'](adapter, directory, 1000))
        from board_faults import run as uart_faults
        result['uart_specific_board_faults'] = uart_faults(adapter, args.output)
        result['host_and_connection_faults'] = helpers['bounded_fault_checks'](adapter, args.output)
        result['status'] = 'SUBMITTED_FOR_REVIEW'
        result['functionality'] = 'PASS'
        result['observed_50Hz'] = 'PASS' if all(row['candidate_observed_50Hz_PASS'] and row['drop'] == 0 for row in result['online']) else 'FAIL'
    except BaseException as error:
        result['first_error'] = repr(error)
        with (args.output/'first_error.log').open('x', encoding='utf-8') as stream:
            stream.write(traceback.format_exc())
        raise
    finally:
        cleanup_errors=[]
        if port:
            try:
                port.close()
            except BaseException as error:
                cleanup_errors.append(repr(error))
        try:
            evidence.close()
        except BaseException as error:
            cleanup_errors.append(repr(error))
        if cleanup_errors:
            result.update(status='PARTIAL_WITH_BLOCKERS',functionality='FAIL',cleanup_errors=cleanup_errors)
        result['worker_wall_seconds_not_whole_suite'] = time.monotonic()-started
        dump(args.output/'RESULT.json', result)
        if cleanup_errors and __import__('sys').exc_info()[0] is None:
            raise RuntimeError('WORKER_CLEANUP_FAILED '+repr(cleanup_errors))


if __name__ == '__main__':
    main()
