"""将视觉观测整理成供 Work 审核的接入提案，不控制 FPGA 或电机。

build_project_proposal(observation, target_neural_timestep_id=None) 接收
BY02_VISION_OBSERVATION_V1 观测，返回 BY02_PROJECT_FEEDBACK_PROPOSAL_V1。
冻结编码器使用 BODY-0A2D FeedbackFrame v0.1：机体 x 向前、y 向左，
azimuth_rad 正值表示左侧；图像 normalized_offset_xy 则右/下为正。
两种坐标不能直接互换。没有测距时不得把单位射线写成米制相对位置。

[接入Work时确认] target timestep 必须由 Work 的神经模型时钟分配。
显式提供 t 后，提案的反馈帧为 t-1，目标神经步为 t；视觉帧编号另存。
本模块不推算模型时间戳，不重用、排队或实际施加反馈，也不验证完整
BODY-0A2D 合同。feedback_frame 只包含冻结编码器读取的字段子集，仍需
Work 校验其时钟、会话、时效和完整合同后接受。

[装车后调整] 相机内参、镜像、机体安装外参、真实测距来源和采集时钟
需要实测确认。正常的单目演示默认全部阻塞，只能记录草案。
即使观察不到目标，也不能把“中性神经输入”等同于电机停止。
"""
from __future__ import annotations

import math
from copy import deepcopy
from typing import Any


SCHEMA = "BY02_PROJECT_FEEDBACK_PROPOSAL_V1"
_AZIMUTH_TOLERANCE_RAD = 1e-6


def _finite_number(value: Any) -> bool:
    if not isinstance(value, (float, int)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def _finite_vector(value: Any, length: int) -> bool:
    return isinstance(value, (list, tuple)) and len(value) == length and all(_finite_number(v) for v in value)


def _relation(azimuth: float) -> str:
    # 冻结合同阈值，只用于审核字段一致性；不能按演示效果调整。
    if azimuth > 1e-6:
        return "LEFT"
    if azimuth < -1e-6:
        return "RIGHT"
    return "CENTER"


def build_project_proposal(
    observation: dict, target_neural_timestep_id: int | None = None
) -> dict:
    """生成审核草案；缺标定、距离、时钟、在线来源或模型步号即 BLOCKED。

    即使返回 READY_FOR_INTEGRATION_REVIEW，也只表示提案字段可以交给
    Work 审核，不代表真板、串口或电机闭环已通过验收。
    """
    if not isinstance(observation, dict):
        raise TypeError("observation must be a dict")
    obs = observation
    source = obs.get("source") if isinstance(obs.get("source"), dict) else {}
    geometry = obs.get("geometry") if isinstance(obs.get("geometry"), dict) else {}
    reasons: list[str] = []

    if obs.get("schema_version", obs.get("schema")) != "BY02_VISION_OBSERVATION_V1":
        reasons.append("OBSERVATION_SCHEMA_MISMATCH")
    if obs.get("status") != "VALID":
        reasons.append("OBSERVATION_NOT_VALID")
    if not (
        isinstance(obs.get("session_id"), str) and bool(obs["session_id"].strip())
        and type(obs.get("frame_id")) is int and obs["frame_id"] >= 0
    ):
        reasons.append("OBSERVATION_IDENTITY_MISSING_OR_INVALID")
    count = obs.get("object_count")
    if type(count) is not int or count != 1:
        reasons.append("EXACTLY_ONE_TARGET_REQUIRED")

    center = obs.get("selected_center_xy")
    width, height = obs.get("width"), obs.get("height")
    center_ok = (
        type(width) is int and width > 0
        and type(height) is int and height > 0
        and _finite_vector(center, 2)
        and 0 <= center[0] < width and 0 <= center[1] < height
    )
    if not center_ok:
        reasons.append("TARGET_CENTER_OR_IMAGE_SIZE_INVALID")

    # [接入Work时确认] 文件回放是离线数据；JSONL 本身不能证明在线传输。
    live_source = source.get("kind") == "CAMERA" or (
        source.get("kind") == "K230_JSONL" and source.get("live_transport_verified") is True
    )
    if not live_source:
        reasons.append("LIVE_SOURCE_NOT_VERIFIED")
    if obs.get("eligible_for_live_control") is not True:
        reasons.append("OBSERVATION_NOT_ELIGIBLE_FOR_LIVE_CONTROL")
    captured = source.get("capture_time_ns", obs.get("capture_time_ns"))
    capture_domain = source.get("capture_clock_domain", obs.get("capture_clock_domain"))
    if not (
        source.get("capture_time_verified") is True
        and type(captured) is int and captured >= 0
        and isinstance(capture_domain, str) and bool(capture_domain.strip())
    ):
        reasons.append("CAPTURE_TIME_OR_CLOCK_NOT_VERIFIED")

    # [装车后调整] CALIBRATED 仅表示相机角度标定，不能代替米制距离验证。
    if geometry.get("calibration_status") != "CALIBRATED":
        reasons.append("CAMERA_CALIBRATION_NOT_CONFIRMED")
    if geometry.get("direction_calibrated") is not True:
        reasons.append("DIRECTION_CALIBRATION_NOT_VERIFIED")
    if geometry.get("mounting_verified") is not True:
        reasons.append("MOUNTING_NOT_VERIFIED")
    if geometry.get("metric_geometry_verified") is not True:
        reasons.append("METRIC_GEOMETRY_NOT_VERIFIED")

    relative = geometry.get("relative_position_body_m")
    relative_ok = _finite_vector(relative, 3) and relative[0] > 0
    if not relative_ok:
        reasons.append("FRONT_METRIC_POSITION_REQUIRED")
    azimuth = geometry.get("azimuth_rad")
    azimuth_ok = _finite_number(azimuth)
    if not azimuth_ok:
        reasons.append("CALIBRATED_AZIMUTH_REQUIRED")
    if relative_ok and azimuth_ok:
        expected_azimuth = math.atan2(relative[1], relative[0])
        if abs(azimuth - expected_azimuth) > _AZIMUTH_TOLERANCE_RAD:
            reasons.append("AZIMUTH_INCONSISTENT_WITH_BODY_POSITION")
    ray = geometry.get("unit_ray_body")
    if ray is not None:
        ray_ok = _finite_vector(ray, 3)
        ray_norm = math.hypot(*ray) if ray_ok else 0.0
        if not ray_ok or abs(ray_norm - 1.0) > 1e-6:
            reasons.append("UNIT_RAY_INVALID")
        elif relative_ok:
            position_norm = math.hypot(*relative)
            if any(abs(ray[i] - relative[i] / position_norm) > 1e-6 for i in range(3)):
                reasons.append("UNIT_RAY_INCONSISTENT_WITH_METRIC_POSITION")

    # 不从视觉 frame_id 推导神经步号，避免把摄像头频率冒充神经频率。
    target_ok = type(target_neural_timestep_id) is int and target_neural_timestep_id >= 1
    if not target_ok:
        reasons.append("WORK_TARGET_NEURAL_TIMESTEP_REQUIRED")
    target = target_neural_timestep_id if target_ok else None
    source_feedback_frame_id = target - 1 if target_ok else None

    # 未知值始终为 null；候选不满足冻结合同，必须先经 Work 审核。
    object_candidate = {
        "geometry_status": "VALID" if relative_ok and azimuth_ok else None,
        "environment_visible": obs.get("status") == "VALID" and count == 1,
        "in_front": bool(relative_ok) if relative is not None else None,
        "relative_position_body": list(relative) if _finite_vector(relative, 3) else None,
        "azimuth_rad": float(azimuth) if azimuth_ok else None,
        "left_right_relation": _relation(float(azimuth)) if azimuth_ok else None,
    }
    candidate = {
        "schema_version": "0.1",
        "frame_id": source_feedback_frame_id,
        "target_neural_timestep_id": target,
        "objects": [object_candidate] if count == 1 else [],
    }
    ready = not reasons
    return {
        "schema_version": SCHEMA,
        "status": "READY_FOR_INTEGRATION_REVIEW" if ready else "BLOCKED",
        "blocking_reasons": reasons,
        "source_observation": {
            "session_id": obs.get("session_id"),
            "frame_id": obs.get("frame_id"),
            "source": deepcopy(source),
            "capture_time_ns": captured,
            "capture_clock_domain": capture_domain,
            "received_monotonic_ns": obs.get("received_monotonic_ns"),
            "clock_domain": obs.get("clock_domain"),
        },
        "source_feedback_frame_id": source_feedback_frame_id,
        "target_neural_timestep_id": target,
        "model_clock_binding": "WORK_MUST_BIND_AND_VALIDATE_BEFORE_USE",
        "candidate_feedback_fields": candidate,
        "feedback_frame": deepcopy(candidate) if ready else None,
        "feedback_contract_scope": "ENCODER_INPUT_SUBSET_REQUIRES_WORK_FULL_CONTRACT_CHECK",
        "source_drive": None,
        "transport_performed": False,
        "actuator_command": None,
        "safety_note": "No target or neutral neural input does not guarantee motor stop.",
    }
