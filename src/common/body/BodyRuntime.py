from __future__ import annotations
from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

Vec3 = Tuple[float, float, float]
Quat = Tuple[float, float, float, float]

def _finite(values: Iterable[float]) -> bool:
    return all(math.isfinite(float(v)) for v in values)

def _clamp(x: float, lo: float, hi: float) -> float:
    return min(max(float(x), lo), hi)

def _vadd(a: Vec3, b: Vec3) -> Vec3:
    return tuple(a[i] + b[i] for i in range(3))

def _vsub(a: Vec3, b: Vec3) -> Vec3:
    return tuple(a[i] - b[i] for i in range(3))

def _vscale(a: Vec3, s: float) -> Vec3:
    return tuple(x * s for x in a)

def _qmul(a: Quat, b: Quat) -> Quat:
    w1,x1,y1,z1=a; w2,x2,y2,z2=b
    return (w1*w2-x1*x2-y1*y2-z1*z2,
            w1*x2+x1*w2+y1*z2-z1*y2,
            w1*y2-x1*z2+y1*w2+z1*x2,
            w1*z2+x1*y2-y1*x2+z1*w2)

def _qnorm(q: Quat) -> Quat:
    n = math.sqrt(sum(x*x for x in q))
    if not math.isfinite(n) or n <= 1e-15:
        raise ValueError("invalid quaternion")
    return tuple(x/n for x in q)

def _qrotate(q: Quat, v: Vec3) -> Vec3:
    qc=(q[0],-q[1],-q[2],-q[3])
    r=_qmul(_qmul(q,(0.0,*v)),qc)
    return (r[1],r[2],r[3])

def _heading_yaw(q: Quat) -> float:
    f=_qrotate(q,(1.0,0.0,0.0))
    return math.atan2(f[1],f[0])

def _roll_pitch(q: Quat) -> Tuple[float,float]:
    w,x,y,z=q
    r20=2.0*(x*z-w*y)
    r21=2.0*(y*z+w*x)
    r22=1.0-2.0*(x*x+y*y)
    roll=math.atan2(r21,r22)
    pitch=math.asin(_clamp(-r20,-1.0,1.0))
    return roll,pitch
@dataclass(frozen=True)
class MotorDrive:
    frame_id: int
    timestamp: float
    dt: float
    v_forward_ref: float = 0.0
    v_lateral_ref: float = 0.0
    v_vertical_ref: float = 0.0
    roll_rate_ref: float = 0.0
    pitch_rate_ref: float = 0.0
    yaw_rate_ref: float = 0.0
    schema_version: str = "0.2"

    @staticmethod
    def neutral(frame_id:int, timestamp:float, dt:float) -> "MotorDrive":
        return MotorDrive(frame_id=frame_id,timestamp=timestamp,dt=dt)

@dataclass(frozen=True)
class BodyState:
    frame_id: int
    simulation_time: float
    position_xyz: Vec3
    orientation: Quat
    linear_velocity_xyz: Vec3
    angular_velocity_xyz: Vec3
    valid: bool = True
    wing_state_left: float = 0.0
    wing_state_right: float = 0.0
    body_mode: str = "HOVER"
    schema_version: str = "0.1"

    @staticmethod
    def zero(position:Vec3=(0.0,0.0,0.0), orientation:Quat=(1.0,0.0,0.0,0.0)) -> "BodyState":
        return BodyState(0,0.0,position,_qnorm(orientation),(0.0,0.0,0.0),(0.0,0.0,0.0),True)

@dataclass(frozen=True)
class ControlOutput:
    control_accel_world_xyz: Vec3
    angular_accel_body_xyz: Vec3
    saturated_linear_axes: Tuple[bool,bool,bool]
    saturated_angular_axes: Tuple[bool,bool,bool]

def load_config(path: str | Path) -> Dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))

def validate_and_saturate_drive(d: MotorDrive, cfg: Dict) -> Tuple[MotorDrive, Dict]:
    vals=[d.timestamp,d.dt,d.v_forward_ref,d.v_lateral_ref,d.v_vertical_ref,
          d.roll_rate_ref,d.pitch_rate_ref,d.yaw_rate_ref]
    if d.schema_version != "0.2":
        raise ValueError("unsupported MotorDrive schema")
    if d.frame_id < 0 or not _finite(vals) or d.dt <= 0:
        raise ValueError("invalid MotorDrive")
    lim=cfg["motor_drive_ranges"]
    names=[("v_forward_ref","v_forward_ref_mps"),("v_lateral_ref","v_lateral_ref_mps"),
           ("v_vertical_ref","v_vertical_ref_mps"),("roll_rate_ref","roll_rate_ref_radps"),
           ("pitch_rate_ref","pitch_rate_ref_radps"),("yaw_rate_ref","yaw_rate_ref_radps")]
    out=d
    saturated=[]
    for field,key in names:
        lo,hi=lim[key]; old=getattr(out,field); new=_clamp(old,lo,hi)
        saturated.append(new != old)
        out=replace(out,**{field:new})
    dtc=cfg["dt"]
    if not (dtc["min_s"] <= out.dt <= dtc["max_s"]):
        raise ValueError("dt outside runtime contract")
    return out,{"saturated":any(saturated),"saturated_fields":[names[i][0] for i,v in enumerate(saturated) if v]}

class VelocityRateHoverStabilizerV0_1:
    def __init__(self,cfg:Dict):
        self.cfg=cfg

    def step(self,d:MotorDrive,s:BodyState) -> ControlOutput:
        kp_v=self.cfg["controller"]["linear_velocity_kp_per_s"]
        kp_w=self.cfg["controller"]["angular_rate_kp_per_s"]
        level=self.cfg["controller"]["roll_pitch_level_kp_radps2_per_rad"]
        gravity=tuple(self.cfg["gravity_world_mps2"])
        yaw=_heading_yaw(s.orientation)
        cy,sy=math.cos(yaw),math.sin(yaw)
        vref=(cy*d.v_forward_ref-sy*d.v_lateral_ref,
              sy*d.v_forward_ref+cy*d.v_lateral_ref,
              d.v_vertical_ref)
        err=_vsub(vref,s.linear_velocity_xyz)
        accel=tuple(kp_v[i]*err[i]-gravity[i] for i in range(3))
        alim=self.cfg["limits"]["control_accel_world_abs_mps2"]
        sat_l=tuple(abs(accel[i])>alim[i] for i in range(3))
        accel=tuple(_clamp(accel[i],-alim[i],alim[i]) for i in range(3))

        wref=(d.roll_rate_ref,d.pitch_rate_ref,d.yaw_rate_ref)
        werr=_vsub(wref,s.angular_velocity_xyz)
        aang=[kp_w[i]*werr[i] for i in range(3)]
        roll,pitch=_roll_pitch(s.orientation)
        if d.roll_rate_ref == 0.0:
            aang[0] -= level[0]*roll
        if d.pitch_rate_ref == 0.0:
            aang[1] -= level[1]*pitch
        wlim=self.cfg["limits"]["angular_accel_body_abs_radps2"]
        sat_a=tuple(abs(aang[i])>wlim[i] for i in range(3))
        aang=tuple(_clamp(aang[i],-wlim[i],wlim[i]) for i in range(3))
        return ControlOutput(accel,aang,sat_l,sat_a)
class Simple6DOFHoverFlightV0_1:
    def __init__(self,cfg:Dict):
        self.cfg=cfg
        self.gravity=tuple(cfg["gravity_world_mps2"])

    def step(self,s:BodyState,u:ControlOutput,dt:float) -> BodyState:
        total_accel=_vadd(u.control_accel_world_xyz,self.gravity)
        v=_vadd(s.linear_velocity_xyz,_vscale(total_accel,dt))
        p=_vadd(s.position_xyz,_vscale(v,dt))
        w=_vadd(s.angular_velocity_xyz,_vscale(u.angular_accel_body_xyz,dt))
        omega=(0.0,*w)
        qdot=_qmul(s.orientation,omega)
        q=_qnorm(tuple(s.orientation[i] + 0.5*qdot[i]*dt for i in range(4)))
        values=[*p,*q,*v,*w,s.simulation_time+dt]
        valid=_finite(values)
        moving=max(max(abs(x) for x in v),max(abs(x) for x in w)) > 1e-4
        mode="FLIGHT" if moving else "HOVER"
        return BodyState(
            frame_id=s.frame_id+1,
            simulation_time=s.simulation_time+dt,
            position_xyz=p,
            orientation=q,
            linear_velocity_xyz=v,
            angular_velocity_xyz=w,
            valid=valid,
            wing_state_left=s.wing_state_left,
            wing_state_right=s.wing_state_right,
            body_mode=mode,
            schema_version="0.1",
        )

class BodyRuntime:
    def __init__(self,cfg:Dict):
        self.cfg=cfg
        self.stabilizer=VelocityRateHoverStabilizerV0_1(cfg)
        self.plant=Simple6DOFHoverFlightV0_1(cfg)
        self._last_drive_frame=-1
        self._last_drive_time=-math.inf

    def step(self,d:MotorDrive,s:BodyState) -> Tuple[BodyState,ControlOutput,Dict]:
        d,diag=validate_and_saturate_drive(d,self.cfg)
        if d.frame_id <= self._last_drive_frame or d.timestamp <= self._last_drive_time:
            raise ValueError("duplicate/out-of-order MotorDrive")
        u=self.stabilizer.step(d,s)
        ns=self.plant.step(s,u,d.dt)
        self._last_drive_frame=d.frame_id
        self._last_drive_time=d.timestamp
        return ns,u,diag

def run_sequence(cfg:Dict, drives:List[MotorDrive], initial:BodyState|None=None) -> List[BodyState]:
    runtime=BodyRuntime(cfg)
    state=initial or BodyState.zero()
    out=[state]
    for d in drives:
        state,_,_=runtime.step(d,state)
        out.append(state)
    return out
