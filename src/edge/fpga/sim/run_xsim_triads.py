import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(r"D:\FPGA-AUTO\tasks\S5-FPGA-1C")
OUT = ROOT / "sim" / "xsim"
XVLOG = Path(r"D:\Xilinx\Vivado\2024.2\bin\xvlog.bat")
XELAB = Path(r"D:\Xilinx\Vivado\2024.2\bin\xelab.bat")
XSIM = Path(r"D:\Xilinx\Vivado\2024.2\bin\xsim.bat")
SOURCES = [
    ROOT / "src" / "core" / "fly01_round_shift.sv",
    ROOT / "src" / "core" / "fly01_source_drive.sv",
    ROOT / "src" / "core" / "fly01_accum_add.sv",
    ROOT / "src" / "core" / "fly01_neuron_update.sv",
    ROOT / "src" / "core" / "fly01_event_fifo.sv",
    ROOT / "src" / "core" / "fly01_synapse_banks.sv",
    ROOT / "src" / "core" / "fly01_engine_core.sv",
    ROOT / "src" / "core" / "fly01_formal_top.sv",
    ROOT / "src" / "wrapper" / "fly01_validation_axi.sv",
    ROOT / "sim" / "tb_wrapper_full.sv",
    ROOT / "sim" / "tb_wrapper_xsim_tops.sv",
]


def run(command, log_path, timeout):
    command = [str(item) for item in command]
    if command[0].lower().endswith(".bat"):
        command = ["cmd.exe", "/d", "/c", "call " + subprocess.list2cmdline(command)]
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        child_env = os.environ.copy()
        child_env.setdefault("PROCESSOR_ARCHITECTURE", "AMD64")
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=child_env,
        )
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            raise RuntimeError(f"timeout running {command[0]}")


OUT.mkdir(parents=True, exist_ok=True)
compile_start = time.time()
rc = run([XVLOG, "--sv", *SOURCES], OUT / "xvlog_console.txt", 300)
if rc:
    raise RuntimeError(f"xvlog failed rc={rc}")
results = []
for seed in range(6):
    start = time.time()
    top = f"tb_wrapper_xsim_seed{seed}"
    snapshot = f"s5_fpga1c_wrapper_seed{seed}_sim"
    rc = run([XELAB, top, "-s", snapshot], OUT / f"seed{seed}_xelab_console.txt", 600)
    if rc:
        raise RuntimeError(f"seed {seed} xelab failed rc={rc}")
    log_path = OUT / f"seed{seed}_xsim_console.txt"
    rc = run([XSIM, snapshot, "-runall"], log_path, 900)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    marker = f"S5_FPGA1C_SEED_PASS seed={seed} cases=3 timesteps=300"
    ok = rc == 0 and marker in text and "S5_FPGA1C_FAIL" not in text and "FATAL:" not in text
    match = re.search(rf"S5_FPGA1C_SEED_PASS seed={seed} cases=3 timesteps=300 max_cycles=(\d+)", text)
    item = {
        "seed": seed,
        "status": "PASS" if ok else "FAIL",
        "exit_code": rc,
        "timesteps": 300 if ok else 0,
        "max_cycles": int(match.group(1)) if match else None,
        "elapsed_seconds": round(time.time() - start, 3),
        "log": str(log_path),
    }
    results.append(item)
    (OUT / "summary_partial.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(item), flush=True)
    if not ok:
        raise RuntimeError(f"seed {seed} XSim gate failed")

summary = {
    "task_id": "S5-FPGA-1C",
    "engine": "XSim 2024.2 direct CLI",
    "profile": "VALIDATION_WRAPPER_MMIO_6_DETERMINISTIC_SEED_TRIADS",
    "compile_elapsed_seconds": round(time.time() - compile_start, 3),
    "coverage": {"seeds": 6, "conditions_per_seed": 3, "timesteps_per_condition": 100, "cases": 18, "timesteps": 1800},
    "results": results,
    "max_cycles": max(item["max_cycles"] for item in results),
    "state_readback": "BIT_EXACT",
    "dn_counters": "EXACT",
    "acc_sat_counter": "EXACT",
    "state_sat_counter": "EXACT",
    "fifo_overflow": 0,
    "event_drop": 0,
    "status": "PASS",
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print("S5_FPGA1C_XSIM_FULL_COVERAGE_PASS timesteps=1800", flush=True)
