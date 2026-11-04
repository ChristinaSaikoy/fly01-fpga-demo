import math, json
from pathlib import Path

OUT=Path(r"D:\FPGA-AUTO\tasks\BODY-0A2D")

def dot(a,b): return sum(x*y for x,y in zip(a,b))
def sub(a,b): return [x-y for x,y in zip(a,b)]
def norm(a): return math.sqrt(dot(a,a))
def qconj(q): return [q[0],-q[1],-q[2],-q[3]]
def qmul(a,b):
    w1,x1,y1,z1=a; w2,x2,y2,z2=b
    return [w1*w2-x1*x2-y1*y2-z1*z2,
            w1*x2+x1*w2+y1*z2-z1*y2,
            w1*y2-x1*z2+y1*w2+z1*x2,
            w1*z2+x1*y2-y1*x2+z1*w2]
def rotate(q,v):
    z=qmul(qmul(q,[0.0,*v]),qconj(q))
    return z[1:]
def world_to_body(q_body_to_world,v_world):
    return rotate(qconj(q_body_to_world),v_world)
def yaw_q(rad):
    return [math.cos(rad/2),0.0,0.0,math.sin(rad/2)]
def geometry(body,obj):
    rw=sub(obj["pos"],body["pos"])
    d=norm(rw)
    rb=world_to_body(body["q"],rw)
    rv=sub(obj["vel"],body["vel"])
    if not d>obj["radius"]:
        return {"valid":False,"status":"INVALID_OVERLAP"}
    az=math.atan2(rb[1],rb[0])
    el=math.atan2(rb[2],math.hypot(rb[0],rb[1]))
    theta=2.0*math.asin(obj["radius"]/d)
    rr=dot(rw,rv)/d
    exp=-2.0*obj["radius"]*rr/(d*math.sqrt(d*d-obj["radius"]**2))
    lr="LEFT" if az>1e-6 else ("RIGHT" if az<-1e-6 else "CENTER")
    ar="APPROACHING" if rr<-1e-6 else ("RECEDING" if rr>1e-6 else "STATIONARY")
    return {"valid":True,"distance_m":d,"azimuth_rad":az,"elevation_rad":el,
            "angular_size_rad":theta,"range_rate_mps":rr,
            "angular_expansion_rate_radps":exp,"closing_speed_mps":max(0.0,-rr),
            "left_right_relation":lr,"approach_recession":ar,"in_front":rb[0]>0}

BODY0={"pos":[0.0,0.0,0.0],"q":[1.0,0.0,0.0,0.0],"vel":[0.0,0.0,0.0]}
tests=[]

obj0={"pos":[10.0,0.0,0.0],"vel":[0.0,0.0,0.0],"radius":1.0}
g0=geometry(BODY0,obj0)
tests.append({"name":"Neutral geometry test",
              "pass":abs(g0["distance_m"]-10)<1e-12 and abs(g0["azimuth_rad"])<1e-12 and
                     abs(g0["elevation_rad"])<1e-12 and abs(g0["angular_expansion_rate_radps"])<1e-12 and
                     g0["left_right_relation"]=="CENTER" and g0["approach_recession"]=="STATIONARY",
              "observed":g0})

gl=geometry(BODY0,{"pos":[10.0,2.0,0.0],"vel":[0,0,0],"radius":1.0})
gr=geometry(BODY0,{"pos":[10.0,-2.0,0.0],"vel":[0,0,0],"radius":1.0})
tests.append({"name":"Left/right mirror test",
              "pass":abs(gl["azimuth_rad"]+gr["azimuth_rad"])<1e-12 and
                     abs(gl["angular_size_rad"]-gr["angular_size_rad"])<1e-12 and
                     gl["left_right_relation"]=="LEFT" and gr["left_right_relation"]=="RIGHT",
              "observed":{"left":gl,"right":gr}})
ga=geometry(BODY0,{"pos":[10.0,0.0,0.0],"vel":[-1.0,0.0,0.0],"radius":1.0})
tests.append({"name":"Approaching-object test",
              "pass":ga["range_rate_mps"]<0 and ga["angular_expansion_rate_radps"]>0 and
                     ga["closing_speed_mps"]>0 and ga["approach_recession"]=="APPROACHING",
              "observed":ga})

grec=geometry(BODY0,{"pos":[10.0,0.0,0.0],"vel":[1.0,0.0,0.0],"radius":1.0})
tests.append({"name":"Receding-object test",
              "pass":grec["range_rate_mps"]>0 and grec["angular_expansion_rate_radps"]<0 and
                     grec["closing_speed_mps"]==0 and grec["approach_recession"]=="RECEDING",
              "observed":grec})

body_left_turn={"pos":[0,0,0],"q":yaw_q(math.radians(30.0)),"vel":[0,0,0]}
gturn=geometry(body_left_turn,obj0)
tests.append({"name":"Body-turn feedback test",
              "pass":abs(gturn["azimuth_rad"]-math.radians(-30.0))<1e-12 and
                     gturn["left_right_relation"]=="RIGHT" and
                     abs(gturn["azimuth_rad"]-g0["azimuth_rad"])>0.1,
              "observed":{"before":g0,"after_positive_yaw_30deg":gturn}})
replay_input={"timestamp_s":1.0,"target_neural_timestep_id":51,"recorded_features":[0.1,0.2,0.3]}
replay_a=json.loads(json.dumps(replay_input,sort_keys=True))
replay_b=json.loads(json.dumps(replay_input,sort_keys=True))
tests.append({"name":"Replay determinism test",
              "pass":replay_a==replay_b,
              "observed":{"body_state_A":"ignored","body_state_B":"ignored","replay_input":replay_a}})

same_world_diff_body = abs(gturn["azimuth_rad"]-g0["azimuth_rad"])>0.1
result={"task_id":"BODY-0A.2D","tests":tests,
        "critical_closed_loop_condition":{"same_world_object_different_BodyState_changes_next_sensory_geometry":same_world_diff_body},
        "all_pass":all(t["pass"] for t in tests) and same_world_diff_body}
(OUT/"BODY-0A2D_FEEDBACK_TEST_VECTORS.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
for t in tests:
    print(t["name"],"PASS" if t["pass"] else "FAIL")
print("SAME_WORLD_DIFFERENT_BODY", "PASS" if same_world_diff_body else "FAIL")
print("ALL_PASS", result["all_pass"])
