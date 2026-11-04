"""Dry-run only. No guessed driver bytes and no physical motion capability."""
import math,time
class DryRunActuator:
    def __init__(self,emit=lambda row:None):
        self.emit=emit;self.enabled=False;self.fault='STARTUP_DISABLED';self.last=None
    def stop(self,reason='OPERATOR_STOP'):
        self.enabled=False;self.fault=reason;self.last=None
        row=dict(kind='DRY_RUN_STOP',reason=reason,physical_output=False,v=0,yaw=0);self.emit(row);return row
    def enable(self):
        self.enabled=True;self.fault=None;self.last=time.monotonic_ns()
        self.emit(dict(kind='DRY_RUN_ENABLE',physical_output=False,independent_watchdog_verified=False))
    def update(self,record,now_ns):
        age=(now_ns-record['validated_ns'])/1e6
        if not self.enabled:return None
        if not 0<=age<250 or record['sampling']['applied']['observation_id'] is None:return self.stop('STALE_OR_NO_TARGET')
        d=record['motor_drive_simulated'];v=d['v_forward_ref'];yaw=d['yaw_rate_ref']
        if not all(math.isfinite(x) for x in (v,yaw)):return self.stop('INVALID_NEURAL_DRIVE')
        self.last=record['validated_ns']
        row=dict(kind='DRY_RUN_NEURAL_DRIVE',model_step=record['model_step'],v=max(-.1,min(.1,v)),
                 yaw=max(-.5,min(.5,yaw)),physical_output=False,
                 limits_scope='SOFTWARE_EXAMPLE_NOT_APPROVED_MOTOR_LIMITS')
        self.emit(row);return row
    def poll(self,now_ns):
        if self.enabled and (self.last is None or now_ns-self.last>=250_000_000):return self.stop('DRY_RUN_WATCHDOG')
