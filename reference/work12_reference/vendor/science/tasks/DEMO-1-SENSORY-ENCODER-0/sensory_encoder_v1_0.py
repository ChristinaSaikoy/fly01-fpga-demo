from __future__ import annotations
import csv, json, math
from pathlib import Path

ROOT=Path(__file__).resolve().parent
CONTRACT=json.loads((ROOT/"DEMO-1_SENSORY_ENCODER_V1_0.json").read_text(encoding="utf-8"))
ROSTER=list(csv.DictReader((ROOT/"SENSORY_INPUT_POPULATION_311.csv").open(encoding="utf-8")))
Q=int(CONTRACT["drive_intensity"]["nominal_q"])
AZ_EPS=float(CONTRACT["geometry_rules"]["azimuth"]["threshold_rad"])

class ProtocolInvalid(ValueError):
    pass

def _classify_azimuth(a: float) -> str:
    if not math.isfinite(float(a)):
        raise ProtocolInvalid("nonfinite azimuth")
    if a > AZ_EPS: return "LEFT"
    if a < -AZ_EPS: return "RIGHT"
    return "CENTER"

def encode_feedback_frame(frame: dict) -> dict:
    if frame.get("schema_version") != "0.1":
        raise ProtocolInvalid("feedback schema mismatch")
    objects=frame.get("objects")
    if not isinstance(objects,list):
        raise ProtocolInvalid("objects missing")
    if len(objects)>1:
        raise ProtocolInvalid("multiple object records unsupported in V1_0")
    qvec=[0]*311
    group="NONE"
    if len(objects)==1:
        o=objects[0]
        if o.get("geometry_status") not in ("VALID","INVALID_OVERLAP"):
            raise ProtocolInvalid("unknown geometry status")
        if o.get("geometry_status")=="VALID" and bool(o.get("environment_visible")) and bool(o.get("in_front")):
            rel=o.get("relative_position_body")
            if not (isinstance(rel,list) and len(rel)==3 and all(math.isfinite(float(x)) for x in rel)):
                raise ProtocolInvalid("invalid relative_position_body")
            if not (float(rel[0])>0.0):
                raise ProtocolInvalid("in_front inconsistent with relative_position_body")
            a=float(o["azimuth_rad"])
            derived=_classify_azimuth(a)
            supplied=o.get("left_right_relation")
            if supplied is not None and supplied != derived:
                raise ProtocolInvalid("left_right_relation inconsistent with azimuth")
            group=derived if derived!="CENTER" else "BILATERAL"
            for i,row in enumerate(ROSTER):
                s=row["side"]
                if derived=="LEFT" and s=="L": qvec[i]=Q
                elif derived=="RIGHT" and s=="R": qvec[i]=Q
                elif derived=="CENTER": qvec[i]=Q
        elif o.get("geometry_status")=="VALID":
            # Explicitly ineligible/invisible valid object -> neutral.
            group="NONE"
        else:
            # BODY-0A2D INVALID_OVERLAP object is excluded -> neutral for max-one-object V1_0.
            group="NONE"
    active=[i for i,q in enumerate(qvec) if q]
    sparse=[{"input_ordinal":i,"candidate_local_index":int(ROSTER[i]["candidate_local_index"]),"q":Q} for i in active]
    return {
      "encoder_version":CONTRACT["encoder_version"],
      "source_feedback_frame_id":frame.get("frame_id"),
      "target_neural_timestep_id":frame.get("target_neural_timestep_id"),
      "status":"PASS",
      "active_group":group,
      "drive_q_by_input_ordinal":qvec,
      "active_sparse":sparse
    }
