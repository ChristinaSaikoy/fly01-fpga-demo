"""当前可用：Pillow图片/GIF、K230 JSONL文件；OpenCV为延迟加载的可选项。"""
from dataclasses import dataclass
from pathlib import Path
import json
import time
import numpy as np
from PIL import Image, ImageSequence
from .k230_protocol import validate_message


def _reject_nonfinite(value):
    raise ValueError("nonfinite JSON constant: " + value)


@dataclass
class InputFrame:
    rgb: np.ndarray | None
    source: dict
    received_ns: int
    k230_record: dict | None = None


def metadata(kind, path):
    return {"kind": kind, "input": str(path), "capture_time_ns": None,
            "capture_clock_domain": None, "capture_time_verified": False,
            "live_transport_verified": False, "original_capture_time_status": "UNKNOWN",
            "time_note": "receive/decode time is not sensor exposure time"}


def image_frames(path, max_pixels):
    paths = ([path] if path.is_file() else sorted(p for p in path.iterdir()
             if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".webp")))
    if not paths:
        raise ValueError("no supported images found")
    for item in paths:
        received = time.monotonic_ns()
        with Image.open(item) as image:
            if image.width * image.height > max_pixels:
                raise ValueError("image exceeds max_image_pixels")
            rgb = np.array(image.convert("RGB"))
        yield InputFrame(rgb, metadata("IMAGE_FILE", item), received)


def gif_frames(path, max_pixels):
    with Image.open(path) as image:
        if image.width * image.height > max_pixels:
            raise ValueError("GIF exceeds max_image_pixels")
        media_ms = 0
        for frame in ImageSequence.Iterator(image):
            received = time.monotonic_ns()
            info = metadata("GIF_REPLAY", path)
            info.update(media_time_ms=media_ms, media_duration_ms=int(frame.info.get("duration", 0)))
            media_ms += info["media_duration_ms"]
            yield InputFrame(np.array(frame.convert("RGB")), info, received)


def opencv_frames(path, kind, config):
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is not installed. Use images/gif/k230-jsonl now; camera/video is optional.") from exc
    camera = kind == "camera"
    cap = cv2.VideoCapture(config["index"] if camera else str(path))
    try:
        if not cap.isOpened():
            raise RuntimeError("cannot open camera/video input")
        if camera:
            for prop, key in ((cv2.CAP_PROP_FRAME_WIDTH, "requested_width"),
                              (cv2.CAP_PROP_FRAME_HEIGHT, "requested_height"),
                              (cv2.CAP_PROP_FPS, "requested_fps")):
                cap.set(prop, config[key])
        while True:
            # 这是read调用前的主机时间。相机曝光/缓存延迟仍未知，不能当曝光时间。
            received = time.monotonic_ns()
            ok, bgr = cap.read()
            if not ok:
                if camera:
                    raise RuntimeError("camera read failed/disconnected")
                break
            info = metadata("CAMERA" if camera else "VIDEO_REPLAY", config["index"] if camera else path)
            pos = cap.get(cv2.CAP_PROP_POS_MSEC)
            info.update(media_time_ms=None if camera or not np.isfinite(pos) else float(pos),
                        reported_fps=float(cap.get(cv2.CAP_PROP_FPS)) if np.isfinite(cap.get(cv2.CAP_PROP_FPS)) else None)
            yield InputFrame(np.ascontiguousarray(bgr[:, :, ::-1]), info, received)
    finally:
        cap.release()


def k230_frames(path, max_pixels):
    last_by_session = {}
    with path.open(encoding="utf-8-sig") as stream:
        for lineno, line in enumerate(stream, 1):
            if not line.strip():
                continue
            received = time.monotonic_ns()
            if len(line) > 65536:
                raise ValueError(f"K230 line {lineno} too long")
            record = validate_message(json.loads(line, parse_constant=_reject_nonfinite), max_pixels=max_pixels)
            session, remote_frame = record["session_id"], record["frame_id"]
            if remote_frame <= last_by_session.get(session, -1):
                raise ValueError(f"K230 duplicate/out-of-order frame on line {lineno}")
            last_by_session[session] = remote_frame
            info = metadata("K230_JSONL", path)
            raw_us = record.get("capture_time_us")
            info.update(remote_session_id=session, remote_frame_id=remote_frame,
                        capture_time_ns=None if raw_us is None else raw_us * 1000,
                        capture_clock_domain="UNSYNCHRONIZED_K230_TICKS_US:" + session,
                        original_capture_time_status="REMOTE_UNVERIFIED",
                        transport="JSONL_FILE_REPLAY", image_available=False,
                        data_origin=record.get("origin", "UNVERIFIED_IMPORTED_DETECTIONS"))
            yield InputFrame(None, info, received, record)


def open_source(kind, path, settings):
    if kind != "camera" and (path is None or not path.exists()):
        raise ValueError("input path does not exist")
    max_pixels = settings["input"]["max_image_pixels"]
    if kind == "images":
        return image_frames(path, max_pixels)
    if kind == "gif":
        return gif_frames(path, max_pixels)
    if kind in ("video", "camera"):
        return opencv_frames(path, kind, settings["camera"])
    if kind == "k230-jsonl":
        return k230_frames(path, max_pixels)
    raise ValueError("unknown source kind")
