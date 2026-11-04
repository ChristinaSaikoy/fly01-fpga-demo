import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VIVADO = Path(os.environ.get('FLY01_VIVADO', shutil.which('vivado') or 'vivado'))
XVLOG = Path(os.environ.get('FLY01_XVLOG', shutil.which('xvlog') or 'xvlog'))
XELAB = Path(os.environ.get('FLY01_XELAB', shutil.which('xelab') or 'xelab'))
XSIM = Path(os.environ.get('FLY01_XSIM', shutil.which('xsim') or 'xsim'))
IVERILOG = Path(os.environ.get('FLY01_IVERILOG', shutil.which('iverilog') or 'iverilog'))
VVP = Path(os.environ.get('FLY01_VVP', shutil.which('vvp') or 'vvp'))

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def run(cmd, cwd, log):
    log = Path(log)
    with open(log, 'w', encoding='utf-8', errors='replace') as fh:
        p = subprocess.run(cmd, cwd=cwd, stdout=fh,
                           stderr=subprocess.STDOUT, text=True)
    text = log.read_text(encoding='utf-8', errors='replace')
    return p.returncode, text
def resolve_all(base, items):
    return [(base / x).resolve() for x in items]

def stage_extra_files(base, items, out_dir):
    staged = []
    for item in items:
        rel = Path(item)
        src = (base / rel).resolve()
        require(src.is_file(), f'extra file missing: {src}')
        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        staged.append((src, rel))
    return staged

def tcl_path(path):
    return Path(path).as_posix()

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def run_icarus(rtl, tb, tb_top, out_dir, marker):
    vvp_file = out_dir / 'sim_icarus.vvp'
    rc, _ = run([str(IVERILOG), '-g2012', '-s', tb_top, '-o', str(vvp_file),
                 *map(str, rtl + tb)], out_dir, out_dir / 'icarus_compile.log')
    require(rc == 0, 'Icarus compile failed')
    rc, text = run([str(VVP), str(vvp_file)], out_dir, out_dir / 'icarus_run.log')
    require(rc == 0 and marker in text, 'Icarus simulation gate failed')
    return {'status': 'PASS', 'marker': marker}

def run_xsim(rtl, tb, tb_top, out_dir, marker, extra_rel=()):
    xdir = out_dir / 'xsim'
    if xdir.exists():
        shutil.rmtree(xdir)
    xdir.mkdir(parents=True)
    for rel in extra_rel:
        src = out_dir / rel
        dst = xdir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    rc, _ = run([str(XVLOG), '--sv', *map(str, rtl + tb)], xdir, xdir / 'xvlog_console.txt')
    require(rc == 0, 'XSim xvlog failed')
    snapshot = 'sim_top'
    rc, _ = run([str(XELAB), tb_top, '-s', snapshot], xdir, xdir / 'xelab_console.txt')
    require(rc == 0, 'XSim xelab failed')
    rc, text = run([str(XSIM), snapshot, '-runall'], xdir, xdir / 'xsim_console.txt')
    require(rc == 0 and marker in text, 'XSim simulation gate failed')
    return {'status': 'PASS', 'marker': marker}

def build_tcl(name, part, top, rtl, xdc, out_dir):
    lines = [
        f'set out {{{tcl_path(out_dir)}}}',
        'file mkdir $out',
        f'set bit "$out/{name}.bit"',
    ]
    for f in rtl:
        if f.suffix.lower() == '.sv':
            lines.append(f'read_verilog -sv {{{tcl_path(f)}}}')
        else:
            lines.append(f'read_verilog {{{tcl_path(f)}}}')
    for f in xdc:
        lines.append(f'read_xdc {{{tcl_path(f)}}}')
    lines += [
        f'synth_design -top {top} -part {part}',
        'write_checkpoint -force "$out/post_synth.dcp"',
        'report_utilization -file "$out/utilization_synth.rpt"',
        'opt_design',
        'place_design',
        'phys_opt_design',
        'route_design',
        'write_checkpoint -force "$out/post_route.dcp"',
        'report_utilization -file "$out/utilization_route.rpt"',
        'report_timing_summary -file "$out/timing_summary.rpt"',
        'report_drc -file "$out/drc.rpt"',
        'report_methodology -file "$out/methodology.rpt"',
        'check_timing -verbose -file "$out/check_timing.rpt"',
        'set pmax [get_timing_paths -delay_type max -max_paths 1 -nworst 1]',
        'set pmin [get_timing_paths -delay_type min -max_paths 1 -nworst 1]',
        'if {[llength $pmax] == 0} { error "FPGA_AUTO_NO_SETUP_PATH" }',
        'if {[llength $pmin] == 0} { error "FPGA_AUTO_NO_HOLD_PATH" }',
        'set wns [get_property SLACK [lindex $pmax 0]]',
        'set whs [get_property SLACK [lindex $pmin 0]]',
        'puts "FPGA_AUTO_TIMING WNS=$wns WHS=$whs"',
        'if {$wns < 0.0} { error "FPGA_AUTO_SETUP_FAIL WNS=$wns" }',
        'if {$whs < 0.0} { error "FPGA_AUTO_HOLD_FAIL WHS=$whs" }',
        'write_bitstream -force $bit',
        'if {![file exists $bit]} { error "FPGA_AUTO_BIT_MISSING $bit" }',
        'puts "FPGA_AUTO_BUILD_PASS WNS=$wns WHS=$whs BIT=$bit"',
        'exit',
    ]
    return '\n'.join(lines) + '\n'

def run_vivado(name, part, top, rtl, xdc, out_dir):
    bit = out_dir / f'{name}.bit'
    if bit.exists():
        bit.unlink()
    tcl = out_dir / 'build.tcl'
    tcl.write_text(build_tcl(name, part, top, rtl, xdc, out_dir), encoding='utf-8')
    log_path = out_dir / 'vivado_build.log'
    with open(log_path, 'w', encoding='utf-8', errors='replace') as fh:
        p = subprocess.run([str(VIVADO), '-mode', 'batch', '-source', str(tcl)],
                           cwd=out_dir, stdout=fh,
                           stderr=subprocess.STDOUT, text=True)
    text = log_path.read_text(encoding='utf-8', errors='replace')
    require(p.returncode == 0, 'Vivado build process failed')
    m = re.search(r'FPGA_AUTO_BUILD_PASS WNS=([-+0-9.]+) WHS=([-+0-9.]+)', text)
    require(m is not None, 'Vivado PASS marker missing')
    require(bit.exists(), 'Bitstream file missing after Vivado PASS')
    drc_text = (out_dir / 'drc.rpt').read_text(encoding='utf-8', errors='replace')
    drc_blockers = [line.strip() for line in drc_text.splitlines()
                    if re.search(r'\|\s*(Error|Critical Warning)\s*\|', line)]
    drc_warnings = [line.strip() for line in drc_text.splitlines()
                    if re.search(r'\|\s*Warning\s*\|', line)]
    require(not drc_blockers, 'DRC blocking violations found')
    ver = re.search(r'Vivado v([^\s]+)', text)
    return {
        'status': 'PASS',
        'wns_ns': float(m.group(1)),
        'whs_ns': float(m.group(2)),
        'bitstream': str(bit),
        'bitstream_sha256': sha256(bit),
        'bitstream_bytes': bit.stat().st_size,
        'vivado_version': ver.group(1) if ver else 'unknown',
        'drc_blockers': drc_blockers,
        'drc_warnings': drc_warnings,
    }

def source_manifest(paths):
    return [{'path': str(p), 'sha256': sha256(p)} for p in paths]

def verify_external_xsim(base, relpath):
    p = (base / relpath).resolve()
    require(p.is_file(), f'external XSim summary missing: {p}')
    data = json.loads(p.read_text(encoding='utf-8'))
    require(data.get('status') == 'PASS', 'external XSim summary status is not PASS')
    coverage = data.get('coverage', {})
    require(coverage.get('cases') == 18, 'external XSim coverage must contain 18 cases')
    require(coverage.get('timesteps') == 1800, 'external XSim coverage must contain 1800 timesteps')
    results = data.get('results', [])
    require(len(results) == 6 and all(x.get('status') == 'PASS' for x in results),
            'external XSim per-seed coverage is incomplete')
    return {
        'status': 'PASS_EXTERNAL',
        'summary': str(p),
        'summary_sha256': sha256(p),
        'coverage': coverage,
        'max_cycles': data.get('max_cycles'),
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    args = ap.parse_args()
    config_path = Path(args.config).resolve()
    base = config_path.parent
    cfg = json.loads(config_path.read_text(encoding='utf-8'))
    rtl = resolve_all(base, cfg['rtl'])
    tb = resolve_all(base, cfg['tb'])
    xdc = resolve_all(base, cfg['xdc'])
    output_base = (base / cfg['output_dir']).resolve()
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    out_dir = output_base / run_id
    out_dir.mkdir(parents=True, exist_ok=False)
    staged_extra = stage_extra_files(base, cfg.get('extra_files', []), out_dir)
    extra_rel = [rel for _, rel in staged_extra]
    manifest_path = out_dir / 'run_manifest.json'
    latest_path = output_base / 'latest_manifest.json'
    manifest = {
        'schema_version': 1,
        'run_id': run_id,
        'run_dir': str(out_dir),
        'name': cfg['name'],
        'started_at_utc': datetime.now(timezone.utc).isoformat(),
        'part': cfg['part'],
        'top': cfg['top'],
        'tb_top': cfg['tb_top'],
        'pass_marker': cfg['pass_marker'],
        'sources': source_manifest(rtl + tb + xdc + [src for src, _ in staged_extra]),
        'extra_files': [str(rel).replace('\\', '/') for rel in extra_rel],
        'stages': {},
        'status': 'RUNNING',
    }
    try:
        manifest['stages']['icarus'] = run_icarus(
            rtl, tb, cfg['tb_top'], out_dir, cfg['pass_marker'])
        if cfg.get('xsim_external_summary'):
            manifest['stages']['xsim'] = verify_external_xsim(
                base, cfg['xsim_external_summary'])
        else:
            manifest['stages']['xsim'] = run_xsim(
                rtl, tb, cfg['tb_top'], out_dir, cfg['pass_marker'], extra_rel)
        manifest['stages']['vivado'] = run_vivado(
            cfg['name'], cfg['part'], cfg['top'], rtl, xdc, out_dir)
        manifest['status'] = 'PASS'
        manifest['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(manifest, indent=2)
        manifest_path.write_text(payload, encoding='utf-8')
        latest_path.write_text(payload, encoding='utf-8')
        print(payload)
        return 0
    except Exception as e:
        manifest['status'] = 'FAIL'
        manifest['failure'] = str(e)
        manifest['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(manifest, indent=2)
        manifest_path.write_text(payload, encoding='utf-8')
        latest_path.write_text(payload, encoding='utf-8')
        print(payload, file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
