"""BY01 red-card connected components, refactored to accept RGB arrays.

阈值/4邻域/质心/半开边框沿用 BY-01-R1；不读取样例的 expected 标签。
识别范围是红色目标块，不是任意物体或已训练神经目标检测器。
"""
from collections import deque
import numpy as np


def detect_rgb(rgb, config):
    data = np.asarray(rgb)
    if data.ndim != 3 or data.shape[2] != 3 or data.dtype != np.uint8:
        raise ValueError("detector requires HxWx3 uint8 RGB")
    height, width = data.shape[:2]
    if width < 2 or height < 2:
        raise ValueError("frame must be at least 2x2")
    pixels = data.astype(np.int16)
    red, green, blue = (pixels[:, :, n] for n in range(3))
    remaining = ((red >= config["red_min"]) & (green <= config["green_max"])
                 & (blue <= config["blue_max"])
                 & (red - green >= config["red_margin"])
                 & (red - blue >= config["red_margin"]))
    components = []
    for y, x in np.argwhere(remaining):
        x, y = int(x), int(y)
        if not remaining[y, x]:
            continue
        remaining[y, x] = False
        queue = deque([(x, y)])
        area = sx = sy = 0
        x0 = x1 = x
        y0 = y1 = y
        while queue:
            px, py = queue.popleft()
            area += 1
            sx += px
            sy += py
            x0, x1 = min(x0, px), max(x1, px)
            y0, y1 = min(y0, py), max(y1, py)
            for nx, ny in ((px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)):
                if 0 <= nx < width and 0 <= ny < height and remaining[ny, nx]:
                    remaining[ny, nx] = False
                    queue.append((nx, ny))
        if area >= config["minimum_area_px"]:
            components.append({"bbox_xyxy_exclusive": [x0, y0, x1 + 1, y1 + 1],
                               "center_xy": [sx / area, sy / area], "area_px": area})
    return detection_from_components(components, width, height, config)


def detection_from_components(components, width, height, config):
    components = sorted(components, key=lambda v: v["bbox_xyxy_exclusive"][:2])
    count = len(components)
    center = components[0]["center_xy"] if count == 1 else None
    relation = None
    offset = None
    if center is not None:
        dx = center[0] - (width - 1) / 2
        relation = ("IMAGE_CENTER" if abs(dx) <= config["image_center_deadband_px"]
                    else "IMAGE_LEFT" if dx < 0 else "IMAGE_RIGHT")
        # 图像坐标 x右正、y下正；与冻结编码器“左正rad”不是同一字段。
        offset = [2 * center[0] / (width - 1) - 1,
                  2 * center[1] / (height - 1) - 1]
    return {"status": "VALID" if count == 1 else "NO_TARGET" if count == 0 else "AMBIGUOUS",
            "width": width, "height": height, "object_count": count,
            "components": components,
            "bounding_boxes_xyxy_exclusive": [v["bbox_xyxy_exclusive"] for v in components],
            "centers_xy": [v["center_xy"] for v in components],
            "selected_center_xy": center, "normalized_offset_xy": offset,
            "environment_visible": count == 1, "image_relation": relation}
