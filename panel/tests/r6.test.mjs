import {test} from 'node:test';import assert from 'node:assert/strict';
import fs from 'node:fs';import {R6Adapter} from '../r6.mjs';import {Motion,gate,parseReplay,poseAt} from '../app/motion.js';
const row=(fields={})=>({event:'NEURAL_I2C_STATUS',time:10,session:15,model_step:100,source_seq:90,
 flags:39,yaw_q20:0,acked_left:-1200,acked_right:1200,last_acks:10,fault:false,fault_code:0,reserved_valid:true,zero_ack:true,...fields});
test('R6 ACKed hold drives the illustration while raw neural yaw stays zero',()=>{
 const e=new R6Adapter().accept(row());assert.equal(e.yaw_ref,0);assert.equal(e.execution_yaw_ref,15);
 assert.equal(gate(e),'运行');const m=new Motion();m.receive(e,0);assert.equal(m.value(100),.075);
});
test('R6 raw yaw cannot animate zero, disarmed, bench, stop or failed commands',()=>{
 for(const f of [{acked_left:0,acked_right:0},{flags:35},{flags:47},{flags:39|16384},{fault:true},{last_acks:9},{reserved_valid:false},{zero_ack:false}]){
  const e=new R6Adapter().accept(row({...f,yaw_q20:1048576}));assert.notEqual(gate(e),'运行');const m=new Motion();m.receive(e,0);assert.equal(m.value(100),0);
 }
});
test('R6 malformed/unknown fields, repeats, reordering and retired sessions',()=>{
 const a=new R6Adapter();assert.equal(a.accept({event:'CONTROL_WRITE',ascii:'E'}),null);
 assert.throws(()=>a.accept(row({acked_left:undefined})));assert.throws(()=>a.accept(row({session:0})));
 assert.ok(a.accept(row()));assert.equal(a.accept(row()),null);assert.equal(a.accept(row({time:9})),null);
 assert.equal(a.accept(row({time:11,model_step:99})),null);
 assert.ok(a.accept(row({time:12,session:16})));assert.equal(a.accept(row({time:13,session:15})),null);
});
test('R6 recorded source preserves raw output, execution directions and final stop',()=>{
 const r=parseReplay(fs.readFileSync(new URL('../samples/r6_recorded.jsonl',import.meta.url),'utf8'));
 assert.equal(r.events.length,1062);assert.ok(r.events.every(x=>x.event.origin==='recorded_fpga'));
 const moving=r.events.filter(x=>gate(x.event)==='运行');assert.ok(moving.length>0);
 assert.ok(moving.some(x=>x.event.execution_yaw_ref<0));assert.ok(moving.some(x=>x.event.execution_yaw_ref>0));
 const last=r.events.at(-1);assert.equal(last.event.execution_state,'DISABLED');assert.notEqual(gate(last.event),'运行');
 assert.equal(poseAt(r,r.duration).value(r.duration),poseAt(r,r.duration-200).value(r.duration-200));
});
