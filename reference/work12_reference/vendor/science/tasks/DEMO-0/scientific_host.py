from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
import csv, hashlib, importlib.util, json, math, sys
from pathlib import Path
from typing import Optional, Tuple, List

ROOT = Path(r"D:\FPGA-AUTO")
TASK = ROOT / "tasks" / "DEMO-0"
MAPPING_PATH = TASK / "FINAL_DN_MOTOR_MAPPING_V1_0.json"
MAPPING_RECEIPT = TASK / "FINAL_DN_MOTOR_MAPPING_V1_0_SHA256.txt"
DEPENDENCY_PATH = TASK / "FROZEN_PIPELINE_DEPENDENCIES_V1_0.json"
DT = 0.02
PREROLL_STEPS = 25

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

@dataclass(frozen=True)
class DNFrame:
    frame_id: int
    timestamp_s: float
    dt_s: float
    slots: Tuple[int, ...]
    source_id: str
    replay_id: Optional[str]
    stimulus_state: str
    source_timestep: int
    schema_version: str = "demo.dnframe.v1"

@dataclass(frozen=True)
class DemoFrame:
    frame_id: int
    timestamp_s: float
    source_timestep: int
    replay_id: str
    stimulus_state: str
    mapping_id: str
    dn_slots: Tuple[int, ...]
    a12: float
    a22: float
    a23: float
    h_p03: float
    p03_contribution: float
    p06R_contribution: float
    yaw_pre: float
    motor_drive: dict
    body_state: dict
    schema_version: str = "demo.demoframe.v1"
    def to_dict(self):
        return asdict(self)

class DNSource(ABC):
    @abstractmethod
    def reset(self) -> None: ...
    @abstractmethod
    def next_frame(self) -> Optional[DNFrame]: ...

class ReplayDNSource(DNSource):
    REPLAYS = {
        "LEFT": {
            "replay_id": "D1_TRAIN_L_ONOFF_seed16",
            "path": ROOT / "tasks" / "BODY-0A2F-DATA-1" / "raw" / "D1_TRAIN_L_ONOFF_seed16" / "dn32_per_step.csv",
            "side": "LEFT",
        },
        "RIGHT": {
            "replay_id": "D1_TRAIN_R_ONOFF_seed17",
            "path": ROOT / "tasks" / "BODY-0A2F-DATA-1" / "raw" / "D1_TRAIN_R_ONOFF_seed17" / "dn32_per_step.csv",
            "side": "RIGHT",
        },
    }
    def __init__(self, replay_key: str):
        if replay_key not in self.REPLAYS:
            raise ValueError(f"unsupported replay {replay_key}")
        self.replay_key = replay_key
        self.meta = self.REPLAYS[replay_key]
        self.rows = self._load(self.meta["path"])
        self._i = 0

    @staticmethod
    def _load(path: Path):
        rows = []
        with path.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                t = int(r["timestep_id"])
                slots = tuple(int(r[f"slot{i}"]) for i in range(32))
                rows.append((t, slots))
        if [t for t, _ in rows] != list(range(200)):
            raise ValueError("replay must contain exact timesteps 0..199")
        return rows

    def reset(self) -> None:
        self._i = 0

    def _stimulus(self, t: int) -> str:
        if 50 <= t <= 124:
            return self.meta["side"]
        return "OFF"

    def next_frame(self) -> Optional[DNFrame]:
        if self._i >= len(self.rows):
            return None
        t, slots = self.rows[self._i]
        self._i += 1
        return DNFrame(
            frame_id=t,
            timestamp_s=t * DT,
            dt_s=DT,
            slots=slots,
            source_id="ReplayDNSource",
            replay_id=self.meta["replay_id"],
            stimulus_state=self._stimulus(t),
            source_timestep=t,
        )

class FpgaDNSource(DNSource):
    """Future adapter contract. Transport is intentionally not implemented in DEMO-0."""
    def reset(self) -> None:
        raise NotImplementedError("FPGA transport belongs to a later stage")
    def next_frame(self) -> Optional[DNFrame]:
        raise NotImplementedError("FPGA transport belongs to a later stage")

class FrozenArtifacts:
    def __init__(self):
        self.mapping = self._load_mapping()
        self.dependencies = load_json(DEPENDENCY_PATH)
        self._verify_dependencies()
        self.stage1 = load_json(Path(self.dependencies["STAGE1"]["path"]))
        self.stage2 = load_json(Path(self.dependencies["STAGE2"]["path"]))
        self.body_config = load_json(Path(self.dependencies["BODY_CONFIG"]["path"]))
        self.bodyrt = self._load_body_runtime(Path(self.dependencies["BODY_RUNTIME"]["path"]))

    def _load_mapping(self):
        expected = MAPPING_RECEIPT.read_text(encoding="utf-8").split()[0]
        actual = sha256(MAPPING_PATH)
        if actual != expected:
            raise RuntimeError(f"FINAL mapping SHA mismatch: {actual} != {expected}")
        m = load_json(MAPPING_PATH)
        if m["mapping_id"] != "FINAL_DN_MOTOR_MAPPING_V1_0" or m["status"] != "PASS_FROZEN":
            raise RuntimeError("unexpected final mapping identity/status")
        return m

    def _verify_dependencies(self):
        for name, item in self.dependencies.items():
            p = Path(item["path"])
            if sha256(p) != item["sha256"]:
                raise RuntimeError(f"frozen dependency mismatch: {name}")

    @staticmethod
    def _load_body_runtime(path: Path):
        spec = importlib.util.spec_from_file_location("demo0_body_runtime", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod

class FrozenPreprocessorV1_0:
    def __init__(self, artifacts: FrozenArtifacts):
        self.a = artifacts
        m = artifacts.mapping
        self.tau = float(m["FILTER_TAU"])
        self.alpha = 1.0 - math.exp(-DT / self.tau)
        s1 = artifacts.stage1
        self.baseline = {
            12: float(s1["baseline"]["b_12"]),
            22: float(s1["baseline"]["b_22"]),
            23: float(s1["baseline"]["b_23"]),
        }
        self.scale = {
            12: float(s1["normalization"]["s_p03"]),
            23: float(s1["normalization"]["s_p03"]),
            22: float(s1["normalization"]["s_p06R"]),
        }
        report = next(x for x in artifacts.stage2["tau_reports"] if float(x["tau_s"]) == self.tau)
        self.theta = {int(k): float(v) for k, v in report["theta"].items()}
        self.reset()

    def reset(self):
        # Frozen semantics: ZERO_BASELINE_STATE_PLUS_CAUSAL_PRE_ROLL.
        self.y = {12: 0.0, 22: 0.0, 23: 0.0}

    def step(self, frame: DNFrame) -> dict:
        out = {}
        for slot in (12, 22, 23):
            z = (frame.slots[slot] / frame.dt_s - self.baseline[slot]) / self.scale[slot]
            self.y[slot] += self.alpha * (z - self.y[slot])
            out[f"z{slot}"] = z
            out[f"y{slot}"] = self.y[slot]
            out[f"a{slot}"] = max(0.0, self.y[slot] - self.theta[slot])
        return out

class FinalDNMotorMapperV1_0:
    def __init__(self, artifacts: FrozenArtifacts):
        self.a = artifacts
        self.m = artifacts.mapping

    def map(self, dn: DNFrame, pp: dict, drive_frame_id: int):
        a12, a22, a23 = pp["a12"], pp["a22"], pp["a23"]
        h_p03 = a23 - a12
        p03 = float(self.m["g_p03"]) * h_p03
        p06 = float(self.m["g_p06R"]) * a22
        yaw_pre = p03 + p06
        yaw_ref = min(max(yaw_pre, -20.0), 20.0)
        z = self.m["other_five_MotorDrive_references"]
        drive = self.a.bodyrt.MotorDrive(
            frame_id=drive_frame_id,
            timestamp=drive_frame_id * dn.dt_s,
            dt=dn.dt_s,
            v_forward_ref=float(z["v_forward_ref"]),
            v_lateral_ref=float(z["v_lateral_ref"]),
            v_vertical_ref=float(z["v_vertical_ref"]),
            roll_rate_ref=float(z["roll_rate_ref"]),
            pitch_rate_ref=float(z["pitch_rate_ref"]),
            yaw_rate_ref=float(yaw_ref),
        )
        return drive, {
            "a12": a12, "a22": a22, "a23": a23,
            "h_p03": h_p03,
            "p03_contribution": p03,
            "p06R_contribution": p06,
            "yaw_pre": yaw_pre,
            "yaw_rate_ref": yaw_ref,
        }

class ScientificReplayPipeline:
    def __init__(self, artifacts: FrozenArtifacts):
        self.artifacts = artifacts

    @staticmethod
    def _body_dict(state):
        return {
            "frame_id": state.frame_id,
            "simulation_time": state.simulation_time,
            "position_xyz": list(state.position_xyz),
            "orientation_wxyz": list(state.orientation),
            "linear_velocity_xyz": list(state.linear_velocity_xyz),
            "angular_velocity_xyz": list(state.angular_velocity_xyz),
            "valid": bool(state.valid),
            "wing_state_left": state.wing_state_left,
            "wing_state_right": state.wing_state_right,
            "body_mode": state.body_mode,
            "schema_version": state.schema_version,
        }

    @staticmethod
    def _drive_dict(drive):
        return {
            "frame_id": drive.frame_id, "timestamp": drive.timestamp, "dt": drive.dt,
            "v_forward_ref": drive.v_forward_ref,
            "v_lateral_ref": drive.v_lateral_ref,
            "v_vertical_ref": drive.v_vertical_ref,
            "roll_rate_ref": drive.roll_rate_ref,
            "pitch_rate_ref": drive.pitch_rate_ref,
            "yaw_rate_ref": drive.yaw_rate_ref,
            "schema_version": drive.schema_version,
        }

    def build_replay(self, replay_key: str) -> List[DemoFrame]:
        src = ReplayDNSource(replay_key)
        pre = FrozenPreprocessorV1_0(self.artifacts)
        mapper = FinalDNMotorMapperV1_0(self.artifacts)
        runtime = self.artifacts.bodyrt.BodyRuntime(self.artifacts.body_config)
        state = self.artifacts.bodyrt.BodyState.zero()
        output = []
        drive_frame = 0
        while True:
            dn = src.next_frame()
            if dn is None:
                break
            pp = pre.step(dn)
            if dn.source_timestep < PREROLL_STEPS:
                continue
            drive, vals = mapper.map(dn, pp, drive_frame)
            state, _, _ = runtime.step(drive, state)
            output.append(DemoFrame(
                frame_id=drive_frame,
                timestamp_s=drive_frame * DT,
                source_timestep=dn.source_timestep,
                replay_id=dn.replay_id or replay_key,
                stimulus_state=dn.stimulus_state,
                mapping_id=self.artifacts.mapping["mapping_id"],
                dn_slots=dn.slots,
                a12=vals["a12"], a22=vals["a22"], a23=vals["a23"],
                h_p03=vals["h_p03"],
                p03_contribution=vals["p03_contribution"],
                p06R_contribution=vals["p06R_contribution"],
                yaw_pre=vals["yaw_pre"],
                motor_drive=self._drive_dict(drive),
                body_state=self._body_dict(state),
            ))
            drive_frame += 1
        if len(output) != 175:
            raise RuntimeError(f"expected 175 demo frames, got {len(output)}")
        return output

def build_all_replays():
    artifacts = FrozenArtifacts()
    pipeline = ScientificReplayPipeline(artifacts)
    return artifacts, {"LEFT": pipeline.build_replay("LEFT"), "RIGHT": pipeline.build_replay("RIGHT")}
