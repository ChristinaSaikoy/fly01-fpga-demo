import {test} from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';
import {spawn} from 'node:child_process';import path from 'node:path';import {setTimeout as delay} from 'node:timers/promises';
test('R6 tail ignores backlog, split lines and duplicates; freezes on age and rejects old sessions',async()=>{
 const dir=path.resolve('verification/r6-tail-fixture');fs.mkdirSync(dir,{recursive:true});const log=path.join(dir,'events.jsonl');
 const row={event:'NEURAL_I2C_STATUS',time:100,session:15,model_step:1,source_seq:1,flags:39,yaw_q20:0,
  acked_left:-1200,acked_right:1200,last_acks:10,fault:false,fault_code:0,reserved_valid:true,zero_ack:true};
 fs.writeFileSync(log,JSON.stringify(row)+'\n');
 const p=spawn(process.execPath,['server.mjs','--r6-log',log],{env:{...process.env,PORT:'18879'},stdio:['ignore','pipe','pipe']});
 try{
  await new Promise((resolve,reject)=>{p.stdout.once('data',resolve);p.once('error',reject);p.once('exit',reject);});await delay(180);
  const snap=()=>fetch('http://127.0.0.1:18879/api/snapshot').then(r=>r.json());assert.equal((await snap()).event,null);
  const line=JSON.stringify({...row,time:101,model_step:2});fs.appendFileSync(log,line.slice(0,50));await delay(130);assert.equal((await snap()).event,null);
  fs.appendFileSync(log,line.slice(50)+'\n');await delay(130);let s=await snap();assert.equal(s.event.origin,'live_fpga');assert.equal(s.event.r6.model_step,2);const version=s.version;
  await delay(300);fs.appendFileSync(log,line+'\n');await delay(130);s=await snap();assert.equal(s.version,version);assert.ok(s.age_ms>=250);
  fs.appendFileSync(log,JSON.stringify({...row,time:102,session:16})+'\n');await delay(130);s=await snap();assert.equal(s.event.r6.session,16);
  fs.appendFileSync(log,JSON.stringify({...row,time:103,session:15})+'\n');await delay(130);assert.equal((await snap()).version,s.version);
  fs.appendFileSync(log,JSON.stringify({...row,time:104,session:16,flags:35,acked_left:0,acked_right:0})+'\n');await delay(130);assert.equal((await snap()).event.execution_yaw_ref,0);
  assert.equal((await fetch('http://127.0.0.1:18879/api/control',{method:'POST'})).status,403);
 }finally{p.kill();await new Promise(r=>p.once('exit',r));}
});
