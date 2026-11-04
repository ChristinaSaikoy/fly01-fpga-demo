"""集中设置。搜索“装车后调整”查看实物到位后需要修改的参数。

这些是视觉工程参数；不修改 FLY-01 冻结神经编码器、DN 或运动映射。
JSON 覆盖文件使用相同字段；启动时会检查类型与范围。
"""
from copy import deepcopy
import json
import math
from pathlib import Path

DEFAULTS = {
    "detector": {
        # [装车后调整] 在现场光照、曝光和白平衡下重新检查红色阈值。
        # 初值逐项沿用 BY-01-R1 的红色目标检测，不是训练出的通用识别模型。
        "red_min": 150, "green_max": 110, "blue_max": 110,
        "red_margin": 70,
        # [装车后调整] 目标远近/分辨率改变后检查最小面积；不改神经 q 值。
        "minimum_area_px": 64,
        "image_center_deadband_px": 2.0,
    },
    "input": {
        # [装车后调整] 安装方向先用左/右测试图确认，再设 0/90/180/270。
        "rotation_deg": 0,
        # [装车后调整] 用于纠正原始相机镜像；会影响坐标与识别。
        "sensor_mirror_x": False,
        # [装车后调整] 仅翻转预览，不改变用于项目接洽的观测坐标。
        "preview_mirror_x": False,
        "max_image_pixels": 2073600,
    },
    "camera": {
        # [装车后调整] OpenCV 可选入口的设备号；不假定 K230 USB 就是摄像头。
        "index": 0,
        # [装车后调整] 640x480/20fps 只是请求值；实际输出按读到的帧记录。
        "requested_width": 640, "requested_height": 480, "requested_fps": 20.0,
        "max_frames": 100,
    },
    "freshness": {
        # [装车后调整/由Work验收] 250ms 是视觉处理时长草案，不是电机看门狗。
        # 它只能约束本进程收到帧后的处理时间，不能证明曝光到控制的完整时延。
        "max_processing_age_ms": 250.0,
    },
    "calibration": {
        # [装车后调整] 必须用实际镜头/分辨率的标定结果填写；None 禁止编造角度。
        "intrinsics_verified": False,
        "width_px": None, "height_px": None,
        "fx_px": None, "fy_px": None, "cx_px": None, "cy_px": None,
        # [装车后调整] 当前仅支持已去畸变、光轴水平的简化模型。
        "rectified_input_verified": False,
        "level_mount_verified": False,
        # [装车后调整] 相机光轴相对车头的偏航角：左转为正，单位rad。
        "mount_yaw_rad": None,
        "mounting_verified": False,
    },
    "k230": {
        # [实物到位后调整] 来自此前照片的系列线索，不是本次硬件探测结果。
        "board_hint": "Yahboom K230 / YB-KA02 family; verify PCB label",
        "firmware": "UNCONFIRMED",
        "camera_model": "UNCONFIRMED",
        "usb_application_mode": "UNCONFIRMED",
        # [实物到位后调整] JSONL目前只是文件回放适配；真正传输由后续固件接入。
        "transport": "JSONL_FILE_REPLAY",
    },
}


def _merge(base, override, prefix=""):
    if not isinstance(override, dict):
        raise ValueError(f"{prefix or 'settings'} must be an object")
    for key, value in override.items():
        if key not in base:
            raise ValueError(f"unknown setting: {prefix}{key}")
        if isinstance(base[key], dict):
            _merge(base[key], value, f"{prefix}{key}.")
        else:
            base[key] = value


def _number(value, name, minimum=None, maximum=None, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    if not math.isfinite(value) or (integer and not isinstance(value, int)):
        raise ValueError(f"{name} must be finite" + (" integer" if integer else ""))
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError(f"{name} outside allowed range")


def validate(config):
    d, i, c, cal = (config[x] for x in ("detector", "input", "camera", "calibration"))
    for key in ("red_min", "green_max", "blue_max", "red_margin"):
        _number(d[key], key, 0, 255, integer=True)
    _number(d["minimum_area_px"], "minimum_area_px", 1, integer=True)
    _number(d["image_center_deadband_px"], "image_center_deadband_px", 0)
    _number(i["rotation_deg"], "rotation_deg", integer=True)
    if i["rotation_deg"] not in (0, 90, 180, 270):
        raise ValueError("rotation_deg must be 0/90/180/270")
    _number(i["max_image_pixels"], "max_image_pixels", 1, integer=True)
    for section, keys in ((i, ("sensor_mirror_x", "preview_mirror_x")),
                          (cal, ("intrinsics_verified", "rectified_input_verified",
                                 "level_mount_verified", "mounting_verified"))):
        for key in keys:
            if not isinstance(section[key], bool):
                raise ValueError(f"{key} must be boolean")
    for key in ("index", "requested_width", "requested_height", "max_frames"):
        _number(c[key], key, 0 if key == "index" else 1, integer=True)
    _number(c["requested_fps"], "requested_fps", 0.1, 240)
    _number(config["freshness"]["max_processing_age_ms"], "max_processing_age_ms", 0.001)
    for key in ("fx_px", "fy_px", "cx_px", "cy_px", "mount_yaw_rad"):
        if cal[key] is not None:
            _number(cal[key], key, 0.000001 if key in ("fx_px", "fy_px") else None)
    for key in ("width_px", "height_px"):
        if cal[key] is not None:
            _number(cal[key], key, 2, integer=True)
    if cal["intrinsics_verified"] and any(cal[k] is None for k in
            ("width_px", "height_px", "fx_px", "fy_px", "cx_px", "cy_px")):
        raise ValueError("verified intrinsics require measured resolution/fx/fy/cx/cy")
    if cal["mounting_verified"] and cal["mount_yaw_rad"] is None:
        raise ValueError("verified mounting requires mount_yaw_rad")
    for key, value in config["k230"].items():
        if not isinstance(value, str) or not value:
            raise ValueError(f"k230.{key} must be a nonempty string")
    return config


def load_settings(path: Path | None = None):
    config = deepcopy(DEFAULTS)
    if path is not None:
        override = json.loads(path.read_text(encoding="utf-8-sig"),
                              parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"nonfinite {x}")))
        _merge(config, override)
    return validate(config)
