"""Build the same RTL with explicit manual-bench capability after real zero ACK.

No JTAG, serial commands or automatic motor movement are performed here.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('zero_build_adapter', root / 'run_zero_local.py')
zero = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zero)
runner = zero.runner


def build_tcl(name, part, top, *args, **kwargs):
    text = zero.build_tcl(name, part, top, *args, **kwargs)
    needle = 'synth_design -top %s -part %s' % (top, part)
    if text.count(needle) != 1:
        raise RuntimeError('Canonical synthesis command changed')
    return text.replace(needle, needle + ' -generic {I2C_MOTION_ENABLE=1}')


if __name__ == '__main__':
    evidence = json.loads((root / 'ZERO_ACK_ACCEPTANCE.json').read_text())
    if not (evidence['status'] == 'PASS_ZERO_PWM_I2C_ACK_ONLY' and
            evidence['status_rows'] >= 10 and evidence['all_last_acks'] == 10 and
            evidence['zero_ack'] and not evidence['fault'] and
            evidence['fault_code'] == 0 and evidence['uart_crc_errors'] == 0):
        raise RuntimeError('Real zero-frame ACK evidence missing')
    status_log = Path(evidence['status_log'])
    if hashlib.sha256((status_log.parent / 'uart_rx.bin').read_bytes()).hexdigest() != evidence['raw_uart_sha256']:
        raise RuntimeError('Zero ACK raw evidence changed')
    runner.build_tcl = build_tcl
    runner.run_vivado = zero.run_vivado
    raise SystemExit(runner.main())
