import {test} from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';
import {Motion,gate,parseReplay,poseAt,validate} from '../app/motion.js';
const base={schema:'FLY01_VIEW_TELEMETRY_V1',origin:'synthetic',session_id:'A',seq:0,t_ms:0,yaw_ref:20,pwm_left:-500,pwm_right:500,execution_state:'ACTIVE',command_status:'sent',stop_reason:null};
test('bounded hold and no multi-second extrapolation',()=>{const m=new Motion();m.receive(base,0);assert.equal(m.value(100),.1);assert.equal(m.value(5000),.25);assert.match(m.status(5000),/冻结/);});
test('STOP preserves raw yaw and stops rotation',()=>{const m=new Motion();m.receive(base,0);m.receive({...base,seq:1,t_ms:100,execution_state:'STOP_LATCHED'},100);assert.equal(m.value(1000),.1);assert.equal(m.last.yaw_ref,20);});
test('duplicates and reordered events cannot change pose',()=>{const m=new Motion();m.receive(base,0);assert.equal(m.receive({...base,yaw_ref:-20},100),false);assert.equal(m.value(200),.2);});
test('new session resets and retired session cannot return',()=>{const m=new Motion();m.receive(base,0);m.receive({...base,session_id:'B'},100);assert.equal(m.angle,0);assert.equal(m.receive({...base,seq:5},150),false);});
test('requested, disabled, invalid and contradictory commands do not drive',()=>{for(const change of [{command_status:'requested'},{execution_state:'DISABLED'},{stop_reason:'timeout'},{pwm_left:500,pwm_right:-500},{pwm_left:0,pwm_right:0}])assert.notEqual(gate({...base,...change}),'运行');});
test('negative yaw and freeze',()=>{const m=new Motion();m.receive({...base,yaw_ref:-20,pwm_left:500,pwm_right:-500},0);m.freeze(100);assert.equal(m.value(9999),-.1);assert.equal(m.last.yaw_ref,-20);});
test('invalid payloads rejected',()=>{for(const change of [{yaw_ref:NaN},{yaw_ref:21},{seq:-1},{origin:'fake'},{t_ms:1.5}])assert.throws(()=>validate({...base,...change}));});
test('replay seeks are deterministic and duplicate fixture is filtered',()=>{const r=parseReplay(fs.readFileSync(new URL('../samples/telemetry_synthetic.jsonl',import.meta.url),'utf8'));assert.equal(r.discarded,2);assert.equal(poseAt(r,450).value(450),poseAt(r,450).value(450));assert.equal(poseAt(r,450).value(450),.065);});

test('indexed seek equals sequential integration across gaps, reversal and sessions',()=>{
 const rows=[];for(let i=0;i<2000;i++){const sign=i%100<50?1:-1;rows.push({...base,session_id:i<1000?'A':'B',seq:i%1000,t_ms:(i%1000)*100,yaw_ref:20*sign,pwm_left:-500*sign,pwm_right:500*sign});}
 const r=parseReplay(rows.map(e=>JSON.stringify(e)).join('\n'));
 for(const time of [0,125,4999,5123,99999,100100,130099,199999,300000]){
  const sequential=new Motion();for(const p of r.events){if(p.at>time)break;sequential.receive(p.event,p.at);}
  const indexed=poseAt(r,time);assert.equal(indexed.value(time),sequential.value(time));assert.equal(indexed.distance(time),sequential.distance(time));
 }
});
test('demo stops explicitly and a deliberate outage cannot accumulate hidden motion',()=>{
 const r=parseReplay(fs.readFileSync(new URL('../samples/demo_synthetic.jsonl',import.meta.url),'utf8'));
 assert.equal(r.duration,30000);assert.equal(r.events.at(-1).event.execution_state,'STOP_LATCHED');
 assert.equal(poseAt(r,22300).value(22300),poseAt(r,23999).value(23999));
 assert.equal(poseAt(r,28000).value(28000),poseAt(r,30000).value(30000));
});
test('explicit freeze status is immediate and travel accumulates through reversal',()=>{
 const m=new Motion();m.receive(base,0);m.receive({...base,seq:1,t_ms:100,yaw_ref:-20,pwm_left:500,pwm_right:-500},100);
 assert.equal(m.value(200),0);assert.equal(m.distance(200),.2);m.freeze(200);assert.match(m.status(200),/冻结/);assert.equal(m.distance(9999),.2);
});
