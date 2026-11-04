"""All0..942 canonical lengths through actual Tcl codec + explicit mock primitives."""
import datetime,json
from pathlib import Path
from adapter import PersistentLabTransport,make_packet
ROOT=Path(__file__).resolve().parent
out=ROOT/'runs'/('all_codec_wire_'+datetime.datetime.now().strftime('%Y%m%dT%H%M%S'))
out.mkdir(parents=True,exist_ok=False)
class MockWire(PersistentLabTransport):origin='MOCK_ALL_LENGTHS_NOT_HARDWARE'
t=MockWire(['D:/Git/mingw64/bin/tclsh.exe',str(ROOT/'mock_o7_fixture.tcl'),str(out/'transactions.csv')],out/'native_raw.log')
try:
    t.reset(1)
    for count in range(943):
        events=list(range(min(count,471)))+[512+i for i in range(max(0,count-471))]
        enable=count%2;audit=count in (0,1,2,3,31,32,33,255,256,781,782,941,942)
        got=t._call(['FORMAL',1,count,enable,int(audit),*events])
        packet=make_packet(101,count,events,enable)
        assert got['accepted_events']==count and got['accepted_request_crc32']==packet[7]
        assert got['packet_words']==len(packet) and got['read_words']==(530 if audit else 59)
        assert got['transaction_count']==(len(packet)+255)//256+(3 if audit else 1)
    (out/'RESULT.json').write_text(json.dumps({'status':'PASS','origin':'MOCK_NOT_RTL_NOT_HARDWARE',
        'all_counts':943,'python_vs_Tcl_crc_and_payload':'PASS','zero_and_max_capacity':'PASS',
        'max_packet_words':304,'full_words':530,'minimal_words':59},indent=2)+'\n',encoding='utf-8')
    print('ALL_CODEC_WIRE_MOCK_PASS '+str(out))
finally:t.close()
