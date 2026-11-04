"""FLY-01视觉入口；默认运行随包图片，不打开摄像头/串口/FPGA。"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import platform
import sys
import time
import uuid
import numpy as np
import PIL
from fly01_vision.annotate import annotate
from fly01_vision.pipeline import VisionPipeline
from fly01_vision.project_adapter import build_project_proposal
from fly01_vision.settings import load_settings
from fly01_vision.sources import open_source

BASE = Path(__file__).resolve().parent


def dump_line(stream, value):
    stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
    stream.flush()


def write_preview(output, rows):
    cards = []
    for row in rows:
        image_name = row["image"]
        cards.append(f'<article><h3>Frame {row["frame_id"]}: {html.escape(row["status"])}</h3>'
                     f'<img src="annotated/{image_name}" alt="annotated observation">'
                     f'<p>{html.escape(row["source"])} / {html.escape(str(row["relation"]))}</p></article>')
    body = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>FLY-01 BY02视觉预览</title>'
            '<style>body{font:16px sans-serif;background:#edf1f5;margin:24px;color:#16243a}'
            '.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}'
            'article{background:white;padding:12px;border-radius:10px}img{width:100%;height:auto}</style>'
            '<h1>FLY-01 视觉观测预览</h1><p>输入来源见每帧标签。文件/GIF/K230 JSONL回放均不是实物闭环。'
            '本程序不连接神经计算、FPGA或电机；接入缺项见 project_proposals.jsonl。</p>'
            '<p>预览镜像不改变输出坐标；K230无原图时显示的是带明确标签的检测示意。</p>'
            '<div class="grid">' + ''.join(cards) + '</div></html>')
    (output / "preview.html").write_text(body, encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("images", "gif", "video", "camera", "k230-jsonl"), default="images")
    parser.add_argument("--input", type=Path, help="图片/目录、GIF、视频或K230 JSONL路径")
    parser.add_argument("--config", type=Path, help="覆盖settings.py的JSON配置")
    parser.add_argument("--output", type=Path, help="必须不存在的新目录")
    parser.add_argument("--max-frames", type=int, help="限制输入帧数；相机默认最多100帧")
    args = parser.parse_args(argv)
    if args.max_frames is not None and args.max_frames <= 0:
        parser.error("max-frames must be positive")
    try:
        config = load_settings(args.config)
        input_path = args.input or (BASE / "samples" / "images" if args.source == "images" else None)
        source = open_source(args.source, input_path, config)
    except (ValueError, OSError, TypeError) as exc:
        parser.error(str(exc))
    output = args.output or BASE / "runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if output.exists():
        parser.error("output already exists; choose a new directory to preserve previous results")
    output.mkdir(parents=True, exist_ok=False)
    (output / "annotated").mkdir()
    session = "BY02-" + uuid.uuid4().hex
    clock = "PC_MONOTONIC:" + session
    pipeline = VisionPipeline(config, session, clock)
    (output / "settings_used.json").write_text(json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    counts, cards = Counter(), []
    error = None
    start = time.monotonic_ns()
    limit = args.max_frames if args.max_frames is not None else config["camera"]["max_frames"] if args.source == "camera" else None
    frame_id = 0
    with (output / "observations.jsonl").open("x", encoding="utf-8") as obs_stream, \
         (output / "project_proposals.jsonl").open("x", encoding="utf-8") as proposal_stream:
        try:
            for item in source:
                if item.k230_record is None:
                    observation, frame = pipeline.process_rgb(item.rgb, frame_id=frame_id,
                        source=item.source, received_ns=item.received_ns)
                else:
                    observation = pipeline.process_k230(item.k230_record, frame_id=frame_id,
                        source=item.source, received_ns=item.received_ns)
                    width, height = observation["width"], observation["height"]
                    frame = np.full((height, width, 3), 40, dtype=np.uint8)
                dump_line(obs_stream, observation)
                # [接入Work时确认] 视觉frame_id不是神经步号，CLI不自动分配k/k+1。
                # 因此这里输出BLOCKED草案；host接手时显式调用适配器并绑定模型时钟。
                proposal = build_project_proposal(observation)
                dump_line(proposal_stream, proposal)
                image_name = f"frame_{frame_id:06d}.png"
                annotate(frame, observation, config["input"]["preview_mirror_x"]).save(output / "annotated" / image_name)
                counts[observation["status"]] += 1
                cards.append({"frame_id": frame_id, "status": observation["status"],
                              "source": observation["source"]["kind"],
                              "relation": observation["image_relation"], "image": image_name})
                frame_id += 1
                if limit is not None and frame_id >= limit:
                    break
            if not frame_id:
                raise ValueError("input contained no frames")
        except (Exception, KeyboardInterrupt) as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if hasattr(source, "close"):
                source.close()
            ended = pipeline.ended(error or "input ended or configured frame limit reached")
            dump_line(obs_stream, ended)
            dump_line(proposal_stream, build_project_proposal(ended))
    summary = {"schema": "BY02_VISION_RUN_V1", "status": "FAILED" if error else "PASS",
               "scope": "VISION_OBSERVATIONS_ONLY_NOT_NEURAL_OR_HARDWARE_ACCEPTANCE",
               "source_kind": args.source, "frames_processed": frame_id, "status_counts": dict(counts),
               "session_id": session, "clock_domain": clock,
               "elapsed_wall_ms": (time.monotonic_ns() - start) / 1e6,
               "environment": {"python": platform.python_version(), "numpy": np.__version__, "Pillow": PIL.__version__},
               "error": error, "hardware_access": "CAMERA_ONLY" if args.source == "camera" else "NONE",
               "fpga_access": False, "motor_access": False, "k230_board_tested": False,
               "calibration": "USER_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED" if config["calibration"]["intrinsics_verified"] else "UNCONFIRMED",
               "settings_sha256": hashlib.sha256((output / "settings_used.json").read_bytes()).hexdigest()}
    write_preview(output, cards)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(f"{summary['status']}: {frame_id} frames; output={output}")
    if error:
        print(error, file=sys.stderr)
    return 1 if error else 0


if __name__ == "__main__":
    raise SystemExit(main())
