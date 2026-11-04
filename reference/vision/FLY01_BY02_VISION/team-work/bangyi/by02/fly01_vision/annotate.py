"""Pillow标注预览；数值结果始终保留传感器纠正后的坐标。"""
from PIL import Image, ImageDraw
import numpy as np


def annotate(rgb, observation, preview_mirror=False):
    mirrored = np.ascontiguousarray(rgb[:, ::-1]) if preview_mirror else rgb
    image = Image.fromarray(mirrored)
    draw = ImageDraw.Draw(image)
    width, height = image.size
    good = observation["status"] == "VALID"
    color = (0, 180, 0) if good else (255, 170, 0)
    for x0, y0, x1, y1 in observation.get("bounding_boxes_xyxy_exclusive", []):
        if preview_mirror:
            x0, x1 = width - x1, width - x0
        draw.rectangle((x0, y0, x1 - 1, y1 - 1), outline=color, width=2)
    center = observation.get("preview_center_xy")
    if center is not None:
        x, y = center
        draw.line((x - 6, y, x + 6, y), fill=color, width=2)
        draw.line((x, y - 6, x, y + 6), fill=color, width=2)
    draw.line(((width - 1) / 2, 0, (width - 1) / 2, height - 1), fill=(0, 140, 255))
    kind = observation["source"]["kind"]
    text = f"{observation['status']} | {kind} | {observation.get('image_relation')}\nNO MOTOR OUTPUT | preview mirror={preview_mirror}"
    if not observation["source"].get("image_available", True):
        text += "\nDETECTION DIAGRAM ONLY - NO CAMERA IMAGE"
    draw.rectangle((0, 0, width - 1, min(height - 1, 50)), fill=(20, 20, 20))
    draw.multiline_text((5, 4), text, fill=(255, 255, 255))
    return image
