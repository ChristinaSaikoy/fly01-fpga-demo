"""观测处理与可重复调用的失效/超时接口；不发送运动命令。"""
from copy import deepcopy
import math
import numpy as np
from .detector import detect_rgb, detection_from_components


def empty_geometry(reason="UNCALIBRATED"):
    return {"calibration_status": reason, "mounting_verified": False, "direction_calibrated": False,
            "azimuth_rad": None, "elevation_rad": None,
            "unit_ray_body": None, "relative_position_body_m": None,
            "metric_geometry_verified": False, "distance_m": None}


def clear_selection(observation, status, reason):
    result = deepcopy(observation)
    result.update(status=status, reason=reason, selected_center_xy=None,
                  normalized_offset_xy=None, image_relation=None, environment_visible=False,
                  preview_center_xy=None, eligible_for_live_control=False,
                  stop_required=True, stop_mechanism="EXTERNAL_WATCHDOG_REQUIRED",
                  geometry=empty_geometry("INELIGIBLE"))
    return result


def transform_rgb(rgb, settings):
    if rgb.shape[0] * rgb.shape[1] > settings["max_image_pixels"]:
        raise ValueError("image exceeds configured max_image_pixels")
    # [装车后调整] 旋转是顺时针；随后纠正传感器镜像，最后才检测。
    frame = np.rot90(rgb, -(settings["rotation_deg"] // 90))
    return np.ascontiguousarray(frame[:, ::-1] if settings["sensor_mirror_x"] else frame)


def calibrated_geometry(detected, cal):
    if detected["status"] != "VALID":
        return empty_geometry("INELIGIBLE")
    ready = all(cal[k] for k in ("intrinsics_verified", "rectified_input_verified",
                                 "level_mount_verified", "mounting_verified"))
    if not ready:
        return empty_geometry()
    if (detected["width"], detected["height"]) != (cal["width_px"], cal["height_px"]):
        return empty_geometry("RESOLUTION_MISMATCH")
    u, v = detected["selected_center_xy"]
    # 仅供已去畸变、水平安装、参数经实测确认的针孔相机使用。
    ray = np.array([1.0, (cal["cx_px"] - u) / cal["fx_px"],
                    (cal["cy_px"] - v) / cal["fy_px"]])
    yaw = cal["mount_yaw_rad"]
    x, y, z = ray
    ray = np.array([math.cos(yaw) * x - math.sin(yaw) * y,
                    math.sin(yaw) * x + math.cos(yaw) * y, z])
    ray /= np.linalg.norm(ray)
    return {"calibration_status": "CALIBRATED", "mounting_verified": True, "direction_calibrated": True,
            "azimuth_rad": math.atan2(float(ray[1]), float(ray[0])),
            "elevation_rad": math.atan2(float(ray[2]), math.hypot(float(ray[0]), float(ray[1]))),
            "unit_ray_body": ray.tolist(),
            # [接入Work时确认] 单目观测不自动提供米制深度；单位射线不能冒充位置。
            "relative_position_body_m": None, "metric_geometry_verified": False,
            "distance_m": None}


class VisionPipeline:
    def __init__(self, settings, session_id, clock_domain):
        self.settings = settings
        self.session_id, self.clock_domain = session_id, clock_domain
        self._last_frame_id = -1
        self._last = None

    def process_rgb(self, rgb, *, frame_id, source, received_ns, processed_ns=None):
        try:
            frame = transform_rgb(rgb, self.settings["input"])
            detected = detect_rgb(frame, self.settings["detector"])
            obs = self.process_detection(detected, frame_id=frame_id, source=source,
                                         received_ns=received_ns, processed_ns=processed_ns)
            return obs, frame
        except Exception as exc:
            self._invalidate_error(f"RGB frame rejected: {type(exc).__name__}: {exc}")
            raise

    def process_k230(self, record, *, frame_id, source, received_ns, processed_ns=None):
        """[K230到位后接入] 合格接收器把解析后的实际报文交给这个接口。

        source必须如实记录采集时钟和实际传输来源；本函数不创建串口/USB连接。
        """
        try:
            from .k230_protocol import validate_message, transformed_components
            validate_message(record, self.settings["input"]["max_image_pixels"])
            comps, width, height = transformed_components(record, self.settings["input"], self.settings["detector"])
            detected = detection_from_components(comps, width, height, self.settings["detector"])
            obs = self.process_detection(detected, frame_id=frame_id, source=source,
                                         received_ns=received_ns, processed_ns=processed_ns)
            obs["detector_version"] = "K230_IMPORTED_COMPONENTS_UNVERIFIED"
            self._last = deepcopy(obs)
            return obs
        except Exception as exc:
            self._invalidate_error(f"K230 frame rejected: {type(exc).__name__}: {exc}")
            raise

    def _invalidate_error(self, reason):
        base = self._last or {"schema": "BY02_VISION_OBSERVATION_V1", "session_id": self.session_id,
                              "frame_id": None, "source": {}, "motion_interface": "NOT_CONNECTED"}
        self._last = clear_selection(base, "ERROR", reason)

    def process_detection(self, detected, *, frame_id, source, received_ns, processed_ns=None):
        import time
        end = time.monotonic_ns() if processed_ns is None else processed_ns
        obs = deepcopy(detected)
        obs.update(schema="BY02_VISION_OBSERVATION_V1", detector_version="BY01_RED_CARD_ARRAY_2",
                   session_id=self.session_id, frame_id=frame_id, source=deepcopy(source),
                   received_monotonic_ns=received_ns, processed_monotonic_ns=end,
                   clock_domain=self.clock_domain, eligible_for_live_control=False,
                   coordinate_system="IMAGE_X_RIGHT_Y_DOWN_PIXEL_CENTERS",
                   geometry=empty_geometry(), motion_interface="NOT_CONNECTED",
                   stop_required=True, stop_mechanism="EXTERNAL_WATCHDOG_REQUIRED")
        if isinstance(frame_id, bool) or not isinstance(frame_id, int) or frame_id < 0:
            self._invalidate_error("invalid frame_id")
            raise ValueError("frame_id must be nonnegative integer")
        for label, value in (("received_ns", received_ns), ("processed_ns", end)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                self._invalidate_error(f"invalid {label}")
                raise ValueError(f"{label} must be a nonnegative integer")
        if frame_id <= self._last_frame_id:
            self._last = clear_selection(obs, "REJECTED", "duplicate or out-of-order frame_id")
            return deepcopy(self._last)
        self._last_frame_id = frame_id
        if end < received_ns:
            obs = clear_selection(obs, "ERROR", "monotonic time moved backwards")
        elif (end - received_ns) / 1e6 >= self.settings["freshness"]["max_processing_age_ms"]:
            obs = clear_selection(obs, "STALE", "processing age exceeds draft threshold")
        else:
            obs["geometry"] = calibrated_geometry(obs, self.settings["calibration"])
            center = obs["selected_center_xy"]
            obs["preview_center_xy"] = (None if center is None else
                [obs["width"] - 1 - center[0], center[1]]
                if self.settings["input"]["preview_mirror_x"] else list(center))
        # 视觉识别不代表电机使能；完整相机时钟/3D位置/看门狗交Work接续。
        self._last = deepcopy(obs)
        return obs

    def poll(self, now_ns, clock_domain):
        """调用者须周期调用；本函数本身不是后台定时器或实体电机停机。"""
        if isinstance(now_ns, bool) or not isinstance(now_ns, int) or now_ns < 0:
            self._invalidate_error("invalid poll timestamp")
            raise ValueError("poll timestamp must be a nonnegative integer")
        if self._last is None:
            return {"status": "NO_FRESH_OBSERVATION", "selected_center_xy": None,
                    "eligible_for_live_control": False, "stop_required": True,
                    "motion_interface": "NOT_CONNECTED"}
        if self._last["status"] == "INPUT_ENDED" or "received_monotonic_ns" not in self._last:
            return deepcopy(self._last)
        obs = deepcopy(self._last)
        if clock_domain != self.clock_domain:
            obs = clear_selection(obs, "ERROR", "different monotonic clock domains")
        elif now_ns < obs["received_monotonic_ns"]:
            obs = clear_selection(obs, "ERROR", "poll clock moved backwards")
        elif (now_ns - obs["received_monotonic_ns"]) / 1e6 >= self.settings["freshness"]["max_processing_age_ms"]:
            obs = clear_selection(obs, "STALE", "no new observation within threshold")
        self._last = deepcopy(obs)
        return obs

    def ended(self, reason="input ended"):
        base = self._last or {"schema": "BY02_VISION_OBSERVATION_V1", "session_id": self.session_id,
                              "frame_id": None, "source": {}, "motion_interface": "NOT_CONNECTED"}
        self._last = clear_selection(base, "INPUT_ENDED", reason)
        return deepcopy(self._last)
