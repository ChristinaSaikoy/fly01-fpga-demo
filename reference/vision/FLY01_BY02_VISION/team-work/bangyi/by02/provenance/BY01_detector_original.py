"""Draft red-card observation. Image coordinates only; no neural or motor calls."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from pathlib import Path

import numpy as np
from PIL import Image


VERSION = 'BY01_RED_CARD_DRAFT_1'
CONFIG = {
    'red_min': 150, 'green_max': 110, 'blue_max': 110,
    'red_margin': 70, 'minimum_area_px': 64, 'connectivity': 4,
    'image_center_deadband_px': 2.0,
    'multiple_targets': 'AMBIGUOUS_SELECT_NONE',
}


def detect_image(path: Path) -> dict:
    """Compute connected components from pixels without accessing expected labels."""
    with Image.open(path) as image:
        pixels = np.asarray(image.convert('RGB'), dtype=np.int16)
    height, width = pixels.shape[:2]
    red, green, blue = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    remaining = ((red >= CONFIG['red_min']) & (green <= CONFIG['green_max'])
                 & (blue <= CONFIG['blue_max'])
                 & (red - green >= CONFIG['red_margin'])
                 & (red - blue >= CONFIG['red_margin']))
    components = []
    # Fixed seed order keeps the result reproducible; visited pixels are consumed.
    for y, x in np.argwhere(remaining):
        x, y = int(x), int(y)
        if not remaining[y, x]:
            continue
        queue = deque([(x, y)])
        remaining[y, x] = False
        area = total_x = total_y = 0
        min_x = max_x = x
        min_y = max_y = y
        while queue:
            px, py = queue.popleft()
            area += 1
            total_x += px
            total_y += py
            min_x, max_x = min(min_x, px), max(max_x, px)
            min_y, max_y = min(min_y, py), max(max_y, py)
            for nx, ny in ((px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)):
                if 0 <= nx < width and 0 <= ny < height and remaining[ny, nx]:
                    remaining[ny, nx] = False
                    queue.append((nx, ny))
        if area >= CONFIG['minimum_area_px']:
            components.append({'bbox_xyxy_exclusive': [min_x, min_y, max_x + 1, max_y + 1],
                               'center_xy': [total_x / area, total_y / area], 'area_px': area})
    components.sort(key=lambda item: (item['bbox_xyxy_exclusive'][0], item['bbox_xyxy_exclusive'][1]))
    count = len(components)
    center = components[0]['center_xy'] if count == 1 else None
    relation = None
    if center is not None:
        offset = center[0] - (width - 1) / 2
        relation = ('IMAGE_CENTER' if abs(offset) <= CONFIG['image_center_deadband_px']
                    else 'IMAGE_LEFT' if offset < 0 else 'IMAGE_RIGHT')
    return {
        'status': 'NO_TARGET' if count == 0 else 'VALID' if count == 1 else 'AMBIGUOUS',
        'width': width, 'height': height, 'object_count': count,
        'bounding_boxes_xyxy_exclusive': [item['bbox_xyxy_exclusive'] for item in components],
        'centers_xy': [item['center_xy'] for item in components],
        'components': components, 'selected_center_xy': center,
        'environment_visible': count == 1, 'image_relation': relation,
        'body_side': 'NOT_CALIBRATED', 'azimuth_rad': 'NOT_MEASURED',
        'distance_m': 'NOT_MEASURED', 'schema': 'DRAFT_IMAGE_OBSERVATION_V1',
    }


def preview_center(raw_center: list | None, width: int, mirrored: bool) -> list | None:
    if raw_center is None:
        return None
    return [width - 1 - raw_center[0], raw_center[1]] if mirrored else list(raw_center)


def clear_selection(observation: dict, status: str, reason: str) -> dict:
    output = deepcopy(observation)
    output.update(status=status, reason=reason, selected_center_xy=None,
                  preview_center_xy=None, environment_visible=False, image_relation=None)
    return output


class ObservationStream:
    """Reject replayed frames and expire data without inventing capture timestamps.

    All age checks require a known shared clock. Synthetic tests use a synthetic
    clock; real camera capture-time mapping remains a future integration task.
    """
    def __init__(self, max_age_ns: int = 250_000_000):
        if isinstance(max_age_ns, bool) or not isinstance(max_age_ns, int) or max_age_ns <= 0:
            raise ValueError('max_age_ns must be a positive integer')
        self.max_age_ns = max_age_ns
        self.session = None
        self.last_frame_id = -1
        self.last = None
        self.rearm_required = True

    def accept(self, detected: dict, *, session_id: str, frame_id: int,
               capture_time_ns: int, now_ns: int, clock_domain: str,
               now_clock_domain: str, source: str, raw_mirrored: bool,
               preview_mirrored: bool = False) -> dict:
        observation = deepcopy(detected)
        observation.update(session_id=session_id, frame_id=frame_id,
                           capture_time_ns=capture_time_ns, clock_domain=clock_domain,
                           receive_time_ns=now_ns, receive_clock_domain=now_clock_domain,
                           source=source, raw_mirrored=raw_mirrored,
                           preview_mirrored=preview_mirrored)
        valid_integer = lambda value: isinstance(value, int) and not isinstance(value, bool) and value >= 0
        if (not isinstance(session_id, str) or not session_id or
                not all(valid_integer(value) for value in (frame_id, capture_time_ns, now_ns)) or
                not isinstance(clock_domain, str) or not clock_domain or
                not isinstance(now_clock_domain, str) or not now_clock_domain or
                source not in ('SYNTHETIC', 'CAMERA') or
                not isinstance(raw_mirrored, bool) or not isinstance(preview_mirrored, bool)):
            self.last = None
            self.rearm_required = True
            return clear_selection(observation, 'ERROR', 'invalid frame metadata')
        session_changed = session_id != self.session
        if session_changed:
            self.session, self.last_frame_id = session_id, -1
            self.rearm_required = True
        if frame_id <= self.last_frame_id:
            self.last = None
            self.rearm_required = True
            return clear_selection(observation, 'REJECTED', 'duplicate or out-of-order frame_id')
        self.last_frame_id = frame_id
        if clock_domain != now_clock_domain:
            observation = clear_selection(observation, 'TIMEBASE_UNVERIFIED', 'different clock domains')
        elif capture_time_ns > now_ns:
            observation = clear_selection(observation, 'ERROR', 'capture timestamp is in the future')
        elif now_ns - capture_time_ns >= self.max_age_ns:
            observation = clear_selection(observation, 'STALE', 'capture age exceeds draft limit')
        else:
            observation['preview_center_xy'] = preview_center(
                observation['selected_center_xy'], observation['width'], preview_mirrored)
        # This flag is a future motion-gate requirement, not an implemented motor enable.
        if observation['status'] != 'VALID':
            self.rearm_required = True
        observation.update(session_changed=session_changed,
                           motion_rearm_required=self.rearm_required,
                           motion_interface='NOT_CONNECTED')
        self.last = deepcopy(observation)
        return observation

    def poll(self, now_ns: int, clock_domain: str) -> dict:
        if self.last is None:
            return {'status': 'NO_FRESH_OBSERVATION', 'selected_center_xy': None,
                    'environment_visible': False, 'motion_interface': 'NOT_CONNECTED'}
        if not isinstance(now_ns, int) or isinstance(now_ns, bool) or now_ns < 0:
            self.rearm_required = True
            self.last = clear_selection(self.last, 'ERROR', 'invalid poll timestamp')
        elif clock_domain != self.last['clock_domain']:
            self.rearm_required = True
            self.last = clear_selection(self.last, 'TIMEBASE_UNVERIFIED', 'different clock domains')
        elif now_ns < self.last['capture_time_ns']:
            self.rearm_required = True
            self.last = clear_selection(self.last, 'ERROR', 'clock moved before capture')
        elif now_ns - self.last['capture_time_ns'] >= self.max_age_ns:
            self.rearm_required = True
            self.last = clear_selection(self.last, 'STALE', 'no newer capture within draft limit')
        return deepcopy(self.last)
