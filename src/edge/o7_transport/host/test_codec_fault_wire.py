"""Exercise real fault RPC Tcl against explicit MOCK primitives, no hardware."""
import datetime,json
from pathlib import Path
from adapter import PersistentLabTransport
ROOT=Path(__file__).resolve().parent
out=ROOT/'runs'/('fault_wire_'+datetime.datetime.now().strftime('%Y%m%dT%H%M%S'))
out.mkdir(parents=True,exist_ok=False)
class MockWire(PersistentLabTransport):origin='MOCK_CODEC_FAULT_NOT_HARDWARE'
t=MockWire(['D:/Git/mingw64/bin/tclsh.exe',str(ROOT/'mock_o7_fixture.tcl'),str(out/'transactions.csv')],out/'native_raw.log')
try:
    checked=[]
    for generation,kind in enumerate(('PAD','FLAGS','DUPLICATE','NODE','LEGACY','CRC','HALF'),1):
        t.reset(generation);reply=t._call(['CODEC_FAULT',kind]);assert reply['PASS'];checked.append(reply)
    t.reset(8)
    recovered=t._call(['FORMAL',8,0,1,1]);assert recovered['hardware_commits']==1 and recovered['read_words']==530
    (out/'RESULT.json').write_text(json.dumps({'status':'PASS','origin':'MOCK_NOT_HARDWARE','checks':checked,'reset_recovery':True},indent=2)+'\n',encoding='utf-8')
    print('O7_FAULT_WIRE_MOCK_PASS '+str(out))
finally:t.close()
