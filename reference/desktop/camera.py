"""Exact visible-light DirectShow binding, no trial opens and no image files."""
import json
import socket
import time
from pathlib import Path
from enumerate_dshow import enumerate_devices

def bind(devices, *, name, symbolic_link):
    if name != 'HD Webcam' or 'vid_04f2&pid_b7dd&mi_00' not in symbolic_link.lower():
        raise PermissionError('Only consented HD Webcam visible-light identity allowed')
    matches = [d for d in devices if d.get('name') == name and d.get('symbolic_link') == symbolic_link and d.get('backend') == 'DSHOW']
    if len(matches) != 1:
        raise PermissionError('Exact camera absent or ambiguous; no device opened')
    return matches[0]

def permission(config):
    auth = json.loads(Path(config['camera_approval']).read_text(encoding='utf-8'))
    if (auth.get('status') != 'APPROVED_CAMERA_PREVIEW' or auth.get('execution_host') != socket.gethostname()
        or auth.get('scope') != 'LOCAL_PREVIEW_NO_RAW_RECORDING' or auth.get('camera_index') != config['camera_index']
        or auth.get('work13_confirmed') is not True or not auth.get('user_confirmation_source')):
        raise PermissionError('Fresh WORK13 camera confirmation required')
    return auth

def frames(config, cancel, *, enumerate_fn=None, capture_factory=None):
    auth = permission(config)
    chosen = bind((enumerate_fn or enumerate_devices)(), name=auth['device_name'], symbolic_link=auth['symbolic_link'])
    if chosen['index'] != config['camera_index']:
        raise PermissionError('Index mapping changed; no trial open')
    import cv2
    import numpy as np
    if not cv2.videoio_registry.hasBackend(cv2.CAP_DSHOW):
        raise RuntimeError('DirectShow unavailable; no implicit fallback')
    cap = (capture_factory or cv2.VideoCapture)(chosen['index'], cv2.CAP_DSHOW)
    try:
        if not cap.isOpened() or cap.getBackendName() != 'DSHOW':
            raise RuntimeError('Approved DirectShow camera unavailable')
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # request only; not a latency guarantee
        while not cancel.is_set():
            begin = time.monotonic_ns()
            ok, bgr = cap.read()
            received = time.monotonic_ns()
            if not ok:
                raise RuntimeError('Camera read failed / disconnected')
            if bgr.shape[0]*bgr.shape[1] > 2073600:
                raise RuntimeError('Camera frame too large')
            yield np.ascontiguousarray(bgr[:, :, ::-1]), dict(kind='REAL_CAMERA', input=chosen['index'],
                device_name=chosen['name'], device_path=chosen['symbolic_link'], backend='DSHOW',
                capture_time_ns=None, capture_time_verified=False, exposure='UNKNOWN_EXPOSURE',
                host_read_begin_ns=begin, host_decode_done_ns=received, camera_buffer_age_verified=False), received
    finally:
        cap.release()
        if cap.isOpened():
            raise RuntimeError('Camera release unconfirmed')
