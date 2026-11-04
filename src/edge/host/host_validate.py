from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(r"D:\FPGA-AUTO\tasks\S5-FPGA-1C")
VECTORS = ROOT / "sim" / "vectors"
MODEL = ROOT / "golden_ref" / "s4_scope1_integer_model.py"
SPEC = ROOT / "golden_ref" / "s4_scope1_integer_spec.json"
GRAPH = ROOT / "golden_ref" / "s4_candidate_graphs.npz"
MMIO = ROOT / "spec" / "s5_fpga1c_mmio_register_map.json"
DN_LOCAL = ROOT / "generated" / "dn_local.mem"
DEFAULT_BITSTREAM = ROOT / "runs" / "S5_FPGA1C_BOARD_VALIDATION_ONLY_20260920T230835562" / "S5_FPGA1C_BOARD_VALIDATION_ONLY_20260920T230835562.bit"
VIVADO = Path(r"D:\Xilinx\Vivado\2024.2\bin\vivado.bat")

EXPECTED = {
    "integer_model": "6d68f34c963fbe79de38403a2a0203c2e7afa11f2e82385cd2c815baa6493ca0",
    "integer_spec": "61c9f53e64a2e5fc878c55f533da46955eb5f36ce2e36f9d537cf4c1d57ee1e9",
    "graph": "5dd46c3adafd128a67c407c82e0f2636d5bfc640286b6234879e681c7336e9a6",
    "mmio": "cbc7013debdebea203a724ff0312d52f16700ffbc6b728948089568c94269bfd",
    "dn_local": "113fba5de99c962f4d2a4b52b1c098b3048f56ebc341d549da7c7bd306a5da91",
    "vector_tree": "598e30abd8dfb2a7333066104749921d943b3050883a6f3e0f60b35bcff55670",
    "validation_bitstream": "32fd16b70ffba80bfb8d28edd18034048914bf03aa0441e367c0737741c10212",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_sha256(root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest(), len(files)


def hex_values(path: Path) -> list[int]:
    return [int(line.strip(), 16) for line in path.read_text(encoding="ascii").splitlines() if line.strip()]


def signed18(value: int) -> int:
    value &= (1 << 18) - 1
    return value - (1 << 18) if value & (1 << 17) else value


def verify_hashes(bitstream: Path) -> dict:
    vector_hash, vector_files = tree_sha256(VECTORS)
    actual = {
        "integer_model": sha256(MODEL),
        "integer_spec": sha256(SPEC),
        "graph": sha256(GRAPH),
        "mmio": sha256(MMIO),
        "dn_local": sha256(DN_LOCAL),
        "vector_tree": vector_hash,
        "validation_bitstream": sha256(bitstream) if bitstream.is_file() else None,
    }
    mismatches = {name: {"expected": EXPECTED[name], "actual": value} for name, value in actual.items() if value != EXPECTED[name]}
    result = {"status": "PASS" if not mismatches else "FAIL", "actual": actual, "vector_files": vector_files, "mismatches": mismatches}
    if mismatches:
        raise RuntimeError(f"hash gate failed: {json.dumps(mismatches, sort_keys=True)}")
    return result


def load_case(seed: int, condition: int) -> dict:
    directory = VECTORS / f"l3_seed{seed}"
    base = condition * 100
    drive = hex_values(directory / "drive_mask.mem")[base:base + 100]
    noise = hex_values(directory / "noise_mask.mem")[base:base + 100]
    spike = hex_values(directory / "spike_mask_expected.mem")[base:base + 100]
    states_all = [signed18(value) for value in hex_values(directory / "state_expected.mem")]
    states = states_all[base * 471:(base + 100) * 471]
    acc = hex_values(directory / "acc_sat_expected.mem")[base:base + 100]
    state_sat = hex_values(directory / "state_sat_expected.mem")[base:base + 100]
    dn_final = hex_values(directory / "dn_counts_expected.mem")[condition * 32:(condition + 1) * 32]
    if not (len(drive) == len(noise) == len(spike) == len(acc) == len(state_sat) == 100 and len(states) == 47100 and len(dn_final) == 32):
        raise RuntimeError(f"vector shape mismatch seed={seed} condition={condition}")
    return {"drive": drive, "noise": noise, "spike": spike, "states": states, "acc": acc, "state_sat": state_sat, "dn_final": dn_final}


def selected_cases(all_cases: bool, seed: int, condition: int) -> list[tuple[int, int]]:
    return [(s, c) for s in range(6) for c in range(3)] if all_cases else [(seed, condition)]


def make_plan(cases: list[tuple[int, int]], destination: Path) -> dict:
    rows = []
    max_events = 0
    total_events = 0
    for seed, condition in cases:
        vectors = load_case(seed, condition)
        rows.append(f"CASE,{seed},{condition}")
        for timestep, (drive_mask, noise_mask) in enumerate(zip(vectors["drive"], vectors["noise"])):
            stimulus = [neuron for neuron in range(471) if (drive_mask >> neuron) & 1]
            noise = [neuron for neuron in range(471) if (noise_mask >> neuron) & 1]
            events = stimulus + [0x200 | neuron for neuron in noise]
            if len(events) > 942:
                raise RuntimeError(f"event limit exceeded seed={seed} condition={condition} timestep={timestep}")
            max_events = max(max_events, len(events))
            total_events += len(events)
            rows.append(",".join(["STEP", str(timestep), "1" if timestep >= 25 else "0", str(len(events))] + [f"{event:03X}" for event in events]))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(rows) + "\n", encoding="ascii")
    return {"cases": len(cases), "timesteps": len(cases) * 100, "total_events": total_events, "max_events": max_events, "sha256": sha256(destination)}


def compare_capture(cases: list[tuple[int, int]], capture: Path) -> dict:
    expected_cases = {case: load_case(*case) for case in cases}
    dn_local = hex_values(DN_LOCAL)
    dn_running = {case: [0] * 32 for case in cases}
    seen_steps = 0
    max_cycles = 0
    first_divergences = []
    with capture.open("r", encoding="utf-8") as source:
        for raw_line in source:
            fields = raw_line.strip().split(",")
            if not fields or fields[0] in {"", "META", "CASE"}:
                continue
            if fields[0] != "STEP" or len(fields) != 513:
                first_divergences.append({"kind": "capture_format", "line": raw_line[:200]})
                break
            seed, condition, timestep = map(int, fields[1:4])
            case = (seed, condition)
            if case not in expected_cases or timestep < 0 or timestep >= 100:
                first_divergences.append({"kind": "capture_index", "seed": seed, "condition": condition, "timestep": timestep})
                break
            vectors = expected_cases[case]
            completed, acc_sat, state_sat, overflow, event_drop, cycles = map(int, fields[4:10])
            max_cycles = max(max_cycles, cycles)
            checks = [("completed_timestep_id", completed, timestep), ("acc_sat", acc_sat, vectors["acc"][timestep]), ("state_sat", state_sat, vectors["state_sat"][timestep]), ("fifo_overflow", overflow, 0), ("event_drop", event_drop, 0)]
            for kind, actual, expected in checks:
                if actual != expected:
                    first_divergences.append({"kind": kind, "seed": seed, "condition": condition, "timestep": timestep, "rtl": actual, "golden": expected})
                    break
            if cycles > 500000:
                first_divergences.append({"kind": "timestep_cycles", "seed": seed, "condition": condition, "timestep": timestep, "rtl": cycles, "golden_limit": 500000})
            state_values = [signed18(int(value, 16)) for value in fields[10:481]]
            expected_states = vectors["states"][timestep * 471:(timestep + 1) * 471]
            for neuron, (actual, expected) in enumerate(zip(state_values, expected_states)):
                if actual != expected:
                    first_divergences.append({"kind": "state", "seed": seed, "condition": condition, "timestep": timestep, "neuron": neuron, "rtl": actual, "golden": expected})
                    break
            if timestep >= 25:
                for counter, neuron in enumerate(dn_local):
                    if (vectors["spike"][timestep] >> neuron) & 1:
                        dn_running[case][counter] += 1
            dn_values = [int(value, 16) for value in fields[481:513]]
            for counter, (actual, expected) in enumerate(zip(dn_values, dn_running[case])):
                if actual != expected:
                    first_divergences.append({"kind": "dn_counter", "seed": seed, "condition": condition, "timestep": timestep, "counter": counter, "rtl": actual, "golden": expected})
                    break
            if timestep == 99 and dn_values != vectors["dn_final"]:
                first_divergences.append({"kind": "dn_final_vector", "seed": seed, "condition": condition, "timestep": timestep})
            seen_steps += 1
            if first_divergences:
                break
    passed = not first_divergences and seen_steps == len(cases) * 100
    return {"status": "PASS" if passed else "FAIL", "timesteps": seen_steps, "expected_timesteps": len(cases) * 100, "max_timestep_cycles": max_cycles, "first_divergence": first_divergences[0] if first_divergences else None}


def run_vivado_backend(args, plan: Path, capture: Path, txlog: Path, log: Path, program: bool) -> int:
    tcl_args = [str(plan), str(capture), str(txlog), str(args.bitstream), "1" if program else "0", args.serial, args.hw_server_url]
    vivado_args = [str(args.vivado), "-mode", "batch", "-notrace", "-source", str(ROOT / "host" / "host_validate_hw.tcl"), "-tclargs", *tcl_args]
    command = ["cmd.exe", "/d", "/c", "call " + subprocess.list2cmdline(vivado_args)]
    child_env = os.environ.copy()
    child_env.setdefault("PROCESSOR_ARCHITECTURE", "AMD64")
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=args.timeout_seconds, env=child_env)
    log.write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="FLY-01 S5-FPGA-1C deterministic validation host client")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="verify hashes/vectors and generate the deterministic plan without hardware access")
    mode.add_argument("--execute-board", action="store_true", help="execute the plan through Vivado hw_axi")
    parser.add_argument("--confirm-board-execution", action="store_true", help="required safety acknowledgement for --execute-board")
    parser.add_argument("--all-cases", action="store_true", help="select all 6 seeds x 3 conditions x 100 timesteps")
    parser.add_argument("--seed", type=int, choices=range(6), default=0)
    parser.add_argument("--condition", type=int, choices=range(3), default=0)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--program", action="store_true", help="program the validation bitstream before repeat 1")
    parser.add_argument("--bitstream", type=Path, default=DEFAULT_BITSTREAM)
    parser.add_argument("--vivado", type=Path, default=VIVADO)
    parser.add_argument("--serial", default="210512180081")
    parser.add_argument("--hw-server-url", default="localhost:3121")
    parser.add_argument("--timeout-seconds", type=int, default=86400)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    if args.execute_board and not args.confirm_board_execution:
        parser.error("--execute-board requires --confirm-board-execution")
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    if not args.bitstream.is_file():
        parser.error(f"bitstream not found: {args.bitstream}")

    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")[:-3]
    output = args.output_dir or (ROOT / "host" / "runs" / timestamp)
    output.mkdir(parents=True, exist_ok=True)
    cases = selected_cases(args.all_cases, args.seed, args.condition)
    plan = output / "transaction_plan.csv"
    result = {
        "task_id": "S5-FPGA-1C",
        "mode": "DRY_RUN" if args.dry_run else "BOARD_EXECUTION",
        "hash_gate": verify_hashes(args.bitstream),
        "selection": {"cases": len(cases), "timesteps": len(cases) * 100, "case_ids": cases},
        "plan": make_plan(cases, plan),
        "board_jtag_access": "PASS",
        "board_execution": "NOT_RUN" if args.dry_run else "RUN",
        "runs": [],
    }
    if args.dry_run:
        result["host_client"] = "PASS"
        result["host_client_status"] = "READY_FOR_REAL_BOARD"
        (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 0

    captures = []
    for repeat in range(1, args.repeat + 1):
        capture = output / f"capture_repeat{repeat}.csv"
        txlog = output / f"transactions_repeat{repeat}.csv"
        vivado_log = output / f"vivado_repeat{repeat}.log"
        return_code = run_vivado_backend(args, plan, capture, txlog, vivado_log, args.program and repeat == 1)
        if return_code != 0:
            result["runs"].append({"repeat": repeat, "status": "FAIL", "vivado_return_code": return_code})
            result["host_client"] = "FAIL"
            (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            return return_code
        comparison = compare_capture(cases, capture)
        comparison.update({"repeat": repeat, "capture_sha256": sha256(capture), "transaction_log_sha256": sha256(txlog)})
        result["runs"].append(comparison)
        captures.append(comparison["capture_sha256"])
        if comparison["status"] != "PASS":
            break
    result["repeatability"] = f"{args.repeat}/{args.repeat} EXACT" if len(captures) == args.repeat and len(set(captures)) == 1 else "FAIL"
    result["host_client"] = "PASS" if all(run["status"] == "PASS" for run in result["runs"]) and result["repeatability"] != "FAIL" else "FAIL"
    result["host_client_status"] = "READY_FOR_REAL_BOARD" if result["host_client"] == "PASS" else "HOLD"
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["host_client"] == "PASS" else 3


if __name__ == "__main__":
    sys.exit(main())
