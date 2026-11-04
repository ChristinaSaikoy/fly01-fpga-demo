"""Canonical runner with task-local post-route physical optimization and log gate.

Does not change the global runner or any design timing requirements.
"""
import importlib.util
from pathlib import Path
import re
import sys

canonical = Path('D:/FPGA-AUTO/workflow-v1/fpga_auto.py')
spec = importlib.util.spec_from_file_location('canonical_fpga_auto', canonical)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
original_build_tcl = runner.build_tcl
original_run_vivado = runner.run_vivado


def build_tcl(*args, **kwargs):
    text = original_build_tcl(*args, **kwargs)
    needle = 'route_design\nwrite_checkpoint -force "$out/post_route.dcp"'
    replacement = '\n'.join([
        'route_design',
        'report_timing_summary -file "$out/timing_before_postroute.rpt"',
        'phys_opt_design -directive Explore',
        'report_route_status -file "$out/route_status.rpt"',
        'write_checkpoint -force "$out/post_route.dcp"',
    ])
    if text.count(needle) != 1:
        raise RuntimeError('Canonical Tcl changed; review task adapter')
    return text.replace(needle, replacement)


def run_vivado(*args, **kwargs):
    result = original_run_vivado(*args, **kwargs)
    out_dir = Path(args[-1])
    text = (out_dir / 'vivado_build.log').read_text(encoding='utf-8', errors='replace')
    errors = re.findall(r'^\s*ERROR:.*$', text, flags=re.MULTILINE)
    if errors:
        raise RuntimeError('Vivado emitted ERROR despite process/marker: ' + errors[0])
    result['physical_policy'] = 'canonical flow + post-route phys_opt_design -directive Explore'
    result['error_log_gate'] = 'PASS'
    return result


if __name__ == '__main__':
    runner.build_tcl = build_tcl
    runner.run_vivado = run_vivado
    raise SystemExit(runner.main())
