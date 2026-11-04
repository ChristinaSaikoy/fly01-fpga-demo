from pathlib import Path
import json,sys
import numpy as np
BASE=Path(r"D:\FPGA-AUTO\tasks\FLY-01-FULL-CNS")
F3=BASE/"FULL-3"
sys.path.insert(0,str(F3))
from FULL_DN_ADAPTER_V1 import FullDNAdapterV1

dn=json.loads((BASE/"FULL-1/DN_32_INDEX_MAP.json").read_text(encoding="utf-8"))["entries"]
idx=np.asarray([int(x["runtime_index"]) for x in sorted(dn,key=lambda x:int(x["slot_index"]))],np.int32)
a=FullDNAdapterV1(idx)
j=int(idx[0])

tests=[]
def check(name,events,frame,expected_slot0,expected_count0):
    f=a.aggregate_window(np.asarray(events,dtype=np.int32).reshape((-1,2)) if events else np.empty((0,2),np.int32),frame)
    ok=f["slots"][0]==expected_slot0 and f["telemetry_spike_counts"][0]==expected_count0 and all(x in (0,1) for x in f["slots"])
    tests.append({"name":name,"frame":frame,"events":events,"observed_slot0":f["slots"][0],
                  "observed_count0":f["telemetry_spike_counts"][0],"PASS":ok})

check("first_full_tick",[(0,j)],0,1,1)
check("last_full_tick",[(199,j)],0,1,1)
check("no_spike",[],0,0,0)
check("multiple_spikes_same_window",[(0,j),(50,j),(199,j)],0,1,3)
check("next_window_not_double_counted_frame0",[(200,j)],0,0,0)
check("next_window_counted_frame1",[(200,j)],1,1,1)
check("mixed_boundary_frame0",[(199,j),(200,j)],0,1,1)
check("mixed_boundary_frame1",[(199,j),(200,j)],1,1,1)

result={"adapter":"FULL_DN_ADAPTER_V1","window_definition":"[frame*200, frame*200+199] inclusive",
        "tests":tests,"PASS":all(x["PASS"] for x in tests)}
(F3/"WINDOW_BOUNDARY_TESTS.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
print(json.dumps(result,indent=2))
raise SystemExit(0 if result["PASS"] else 1)
