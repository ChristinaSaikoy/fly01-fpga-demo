"""Independent client: targets are generated only after server startup."""
import argparse
import json
from pathlib import Path
import random
import time
import urllib.request

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--url',required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    def request(path,obj=None):
        req=urllib.request.Request(a.url+path,data=json.dumps(obj).encode() if obj is not None else None,
                                   headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=120) as response:return json.load(response)
    rng=random.Random();sent=[];deadline=time.monotonic()+1700
    while len(sent)<2:
        status=request('/status')
        if status.get('failure'):raise RuntimeError(status['failure'])
        if status['finished']:raise RuntimeError('clock stopped before independent updates')
        threshold=10 if not sent else 60
        if status['frame']>=threshold:
            # World-frame targets are fresh, not selected from archived traces.
            target=[10+rng.uniform(.2,1),(-1 if not sent else 1)*(3+rng.uniform(.1,.8)),rng.uniform(.1,.4)]
            payload={'generation':status['generation'],'request_seq':len(sent),'position_xyz_world_m':target}
            start=time.perf_counter();receipt=request('/target',payload)
            sent.append({'request':payload,'receipt':receipt,'client_rtt_ms':(time.perf_counter()-start)*1000})
        if time.monotonic()>deadline:raise TimeoutError('two target updates')
        time.sleep(.01)
    a.output.write_text(json.dumps(sent,indent=2)+'\n',encoding='utf-8')
    print('WORK02_INDEPENDENT_TARGET_CLIENT_PASS updates=2')
if __name__=='__main__':main()
