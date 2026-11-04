"""Operator-labelled input checks; never asserts correct neural turning."""
import copy
import time

CONVENTION = 'CAMERA_FACING_SCENE_LEFT_RIGHT_NOT_OPERATOR_FACING_SCREEN'
PHASES = ('LEFT', 'RIGHT', 'CENTER', 'REMOVED')

def marker(status, phase, operator, confirmed, mirror, now_ns=None):
    if phase not in PHASES or not isinstance(operator, str) or not operator.strip() or len(operator)>80 or confirmed is not True:
        raise ValueError('Explicit operator/phase confirmation required')
    if status.get('phase') != 'RUNNING':
        raise ValueError('Only a running session can be marked')
    now = time.monotonic_ns() if now_ns is None else now_ns
    obs = copy.deepcopy(status.get('observation'))
    age = (now-obs['received_monotonic_ns'])/1e6 if obs else None
    result = 'UNVERIFIED'
    group = None
    if obs and age is not None and 0 <= age < 250:
        if phase == 'REMOVED':
            result = 'INPUT_MATCH' if obs['status'] == 'NO_TARGET' else 'INPUT_MISMATCH'
        elif obs['status'] == 'VALID' and obs.get('selected_center_xy'):
            offset = obs['selected_center_xy'][0]-(obs['width']-1)/2
            group = 'CENTER' if abs(offset)<=2 else 'LEFT' if offset<0 else 'RIGHT'
            result = 'INPUT_MATCH' if group == phase else 'INPUT_MISMATCH'
    return dict(kind='OPERATOR_STAGE', phase=phase, operator=operator.strip(), operator_confirmed=True,
        coordinate_convention=CONVENTION, sensor_mirror_x=mirror, marker_ns=now, receive_age_ms=age,
        observation=obs, processed_group=group, input_check=result,
        model_step=status.get('model_step'), applied_stimulus=copy.deepcopy(status.get('stimulus')),
        neural_output_turning_validated=False, physical_output=False)
