"""Explicit MOCK of FORMAL command framing; not frozen-state/FPGA evidence."""
import datetime,json,struct,sys,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT/'host'))
from adapter import PersistentLabTransport,BackendFault,make_packet
class MockWire(PersistentLabTransport):origin='MOCK_FORMAL_WIRE_NOT_HARDWARE'
out=ROOT/'diagnostics'/('formal_wire_'+datetime.datetime.now().strftime('%Y%m%dT%H%M%S'))
out.mkdir(parents=True,exist_ok=False)
t=MockWire(['D:/Git/mingw64/bin/tclsh.exe',str(ROOT/'host/mock_o7_fixture.tcl'),str(out/'transactions.csv')],out/'raw.log')
try:
    reset=t.reset(1);events=[0,470,512,982]
    got=t._call(['FORMAL',1,0,0,1,*events])
    expected=make_packet(101,0,events,0)[7]
    assert got['accepted_request_crc32']==expected and got['accepted_events']==4 and got['counts']==[0]*32
    assert got['read_words']==530 and got['hardware_commits']==1
    got=t._call(['FORMAL',1,1,1,0]);assert got['completed_id']==1 and got['read_words']==59
    t.reset(2)
    try:t._call(['FORMAL',2,1,1,1])
    except BackendFault:rejected=True
    else:raise RuntimeError('FORMAL_FRAME_GAP_ACCEPTED')
    result={'status':'PASS','origin':'MOCK_NOT_HARDWARE','FORMAL_flags_and_crc':'PASS','strict_frame_gap_rejection':rejected}
    (out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('FORMAL_WIRE_MOCK_PASS '+str(out))
finally:t.close()
