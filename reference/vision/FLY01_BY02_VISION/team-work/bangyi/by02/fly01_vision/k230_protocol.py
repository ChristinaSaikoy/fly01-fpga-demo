"""K230结果报文草案：本模块也可由后续板端固件复用（无硬件导入）。

此处不配置Sensor/FPIOA/USB/UART。固件型号确认后，板端将自己的检测结果
传给make_message，再通过已确认的数据通道发送JSON+换行。不是FPGA F108协议。
"""
import json
import math

SCHEMA = "FLY01_K230_DETECTION_V1"


def _integer(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(label + " must be a valid integer")
    return value


def validate_message(record, max_pixels=2073600):
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        raise ValueError("K230 message schema mismatch")
    if not isinstance(record.get("session_id"), str) or not record["session_id"]:
        raise ValueError("K230 session_id missing")
    _integer(record.get("frame_id"), "frame_id")
    width = _integer(record.get("width"), "width", 2)
    height = _integer(record.get("height"), "height", 2)
    if width * height > max_pixels:
        raise ValueError("K230 image size exceeds max_image_pixels")
    if record.get("capture_time_us") is not None:
        _integer(record["capture_time_us"], "capture_time_us")
    objects = record.get("objects")
    if not isinstance(objects, list) or len(objects) > 64:
        raise ValueError("K230 objects must be a list of at most 64 detections")
    for item in objects:
        if not isinstance(item, dict):
            raise ValueError("K230 object must be an object")
        box = item.get("bbox_xyxy_exclusive")
        center = item.get("center_xy")
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError("K230 bounding box needs four integers")
        for value in box:
            _integer(value, "bbox")
        x0, y0, x1, y1 = box
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError("K230 bbox outside image")
        if (not isinstance(center, list) or len(center) != 2 or
                any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in center)):
            raise ValueError("K230 center must be finite XY")
        if not (x0 <= center[0] <= x1 - 1 and y0 <= center[1] <= y1 - 1):
            raise ValueError("K230 center outside bounding box")
        area = _integer(item.get("area_px"), "area_px", 1)
        if area > (x1 - x0) * (y1 - y0):
            raise ValueError("K230 foreground area exceeds bounding box")
    return record


def make_message(session_id, frame_id, width, height, objects, capture_time_us=None):
    """[固件接入后调整] objects来自实际相机检测，禁止从预期标签制造检测结果。"""
    return validate_message({"schema": SCHEMA, "session_id": session_id,
                             "frame_id": frame_id, "width": width, "height": height,
                             "capture_time_us": capture_time_us, "objects": objects})


def encode_line(record):
    validate_message(record)
    return (json.dumps(record) + "\n").encode("utf-8")


def transformed_components(record, settings, detector_config):
    """按与RGB入口相同的顺序纠正板端坐标；不把镜像预览混入数值输出。"""
    from copy import deepcopy
    width, height = record["width"], record["height"]
    items = deepcopy(record["objects"])
    for _ in range(settings["rotation_deg"] // 90):
        for item in items:
            x0, y0, x1, y1 = item["bbox_xyxy_exclusive"]
            x, y = item["center_xy"]
            item["bbox_xyxy_exclusive"] = [height - y1, x0, height - y0, x1]
            item["center_xy"] = [height - 1 - y, x]
        width, height = height, width
    if settings["sensor_mirror_x"]:
        for item in items:
            x0, y0, x1, y1 = item["bbox_xyxy_exclusive"]
            item["bbox_xyxy_exclusive"] = [width - x1, y0, width - x0, y1]
            item["center_xy"][0] = width - 1 - item["center_xy"][0]
    # 红色阈值在K230检测器侧执行；这里只复用最小面积和多目标政策。
    return [v for v in items if v["area_px"] >= detector_config["minimum_area_px"]], width, height
