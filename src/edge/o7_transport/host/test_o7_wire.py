"""Exercise real O7 Tcl codec with explicit fake hardware, including real IP queue cap."""
import datetime,hashlib,json,struct,zlib
from pathlib import Path
from adapter import C,PersistentLabTransport,FpgaAdapter,make_packet
from test_adapter import noise_hash
ROOT=Path(__file__).resolve().parent
out=ROOT/'runs'/('wire_'+datetime.datetime.now().strftime('%Y%m%dT%H%M%S'))
out.mkdir(parents=True,exist_ok=False)
class MockWire(PersistentLabTransport):origin='MOCK_O7_WIRE_NOT_HARDWARE'
t=MockWire(['D:/Git/mingw64/bin/tclsh.exe',str(ROOT/'mock_o7_fixture.tcl'),str(out/'transactions.csv')],out/'raw.log')
try:
    q=[0]*311;ih=C.canonical_hash(q);nh=noise_hash([]);a=FpgaAdapter(t)
    one=a.transact(1,0,q,[],ih,nh,True)
    assert one['states']==[0]*471 and one['read_words']==530 and one['counts'][3]==1
    expected=make_packet(101,0,[],1)[7]
    assert one['accepted_request_crc32']==expected and one['transaction_count']==4 and one['Vivado_execution_calls']==3
    two=a.transact(1,1,q,[],ih,nh,False)
    assert two['states']==[] and two['read_words']==59 and two['transaction_count']==2 and two['Vivado_execution_calls']==2
    assert a.transact(1,1,q,[],ih,nh,False)['cached']
    a.reset();three=a.transact(2,0,q,[],ih,nh,False)
    assert three['hardware_generation']==102 and three['hardware_commits']==1
    result={'status':'PASS','origin':'MOCK_NOT_RTL_NOT_HARDWARE','frames':3,
        'physical_generations':[101,102],'full_words':530,'minimal_words':59,
        'CRC32_Tcl_matches_Python':True,'IP_queue_capacity_modeled':[2,2],
        'tcl_sha256':hashlib.sha256((ROOT/'persistent_o7.tcl').read_bytes()).hexdigest()}
    (out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('O7_WIRE_MOCK_PASS '+str(out))
finally:t.close()
