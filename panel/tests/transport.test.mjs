import {test} from 'node:test';import assert from 'node:assert/strict';
import {SnapshotReceiver} from '../app/transport.js';
const event={schema:'FLY01_VIEW_TELEMETRY_V1',origin:'live_fpga',session_id:'A',seq:1,t_ms:100,yaw_ref:20,pwm_left:-500,pwm_right:500,execution_state:'ACTIVE',command_status:'sent',stop_reason:null};
const snap={connected:true,epoch:1,version:1,event,age_ms:0,error:null};
test('stale, disconnected and malformed snapshots freeze the observer',()=>{
 for(const change of [{connected:false},{age_ms:250},{age_ms:-1},{age_ms:NaN},{error:'bad line'},{event:null},{epoch:NaN}]){
  const r=new SnapshotReceiver();r.accept(snap,0);r.accept({...snap,...change},100);assert.equal(r.frozen,true);assert.equal(r.motion.value(9999),.1);
 }
});
test('duplicate or older snapshots cannot revive a frozen pose; a new packet can',()=>{
 const r=new SnapshotReceiver();r.accept(snap,0);r.freeze(100,'hidden');
 r.accept({...snap,age_ms:0},200);assert.equal(r.frozen,true);assert.equal(r.motion.value(1000),.1);
 r.accept({...snap,version:2,event:{...event,seq:2,t_ms:200}},300);assert.equal(r.frozen,false);assert.equal(r.motion.value(400),.2);
 r.accept(snap,450);assert.equal(r.version,2);
});
test('old epochs and reused sequence numbers cannot replace accepted data',()=>{
 const r=new SnapshotReceiver();r.accept({...snap,epoch:2},0);assert.equal(r.accept(snap,100),false);
 assert.equal(r.accept({...snap,epoch:2,version:2},100),false);assert.equal(r.version,1);
});
