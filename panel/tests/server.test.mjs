import {test} from 'node:test';import assert from 'node:assert/strict';import {spawn} from 'node:child_process';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
const delay=ms=>new Promise(r=>setTimeout(r,ms));
test('read-only bridge rejects writes and old backlog, handles partial lines and timeout',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'fly01-test-')),log=path.join(dir,'events.jsonl');
 const e={schema:'FLY01_VIEW_TELEMETRY_V1',origin:'synthetic',session_id:'test',seq:0,t_ms:0,yaw_ref:10,pwm_left:-500,pwm_right:500,execution_state:'ACTIVE',command_status:'sent',stop_reason:null};
 fs.writeFileSync(log,JSON.stringify(e)+'\n');const p=spawn(process.execPath,['server.mjs','--log',log],{cwd:new URL('..',import.meta.url),env:{...process.env,PORT:'18765'},stdio:['ignore','pipe','pipe']});
 try{await new Promise((resolve,reject)=>{p.stdout.once('data',resolve);p.once('error',reject);p.once('exit',c=>reject(Error('server exit '+c)));});await delay(180);
 const snap=()=>fetch('http://127.0.0.1:18765/api/snapshot').then(r=>r.json());assert.equal((await snap()).event,null);
 assert.equal((await fetch('http://127.0.0.1:18765/api/control',{method:'POST'})).status,403);
 assert.equal((await fetch('http://127.0.0.1:18765/%ZZ')).status,400);
 const line=JSON.stringify({...e,seq:1,t_ms:100});fs.appendFileSync(log,line.slice(0,50));await delay(120);assert.equal((await snap()).event,null);fs.appendFileSync(log,line.slice(50)+'\n');await delay(120);assert.equal((await snap()).event.seq,1);
 await delay(300);assert.ok((await snap()).age_ms>=250);fs.appendFileSync(log,JSON.stringify(e)+'\n');await delay(120);assert.equal((await snap()).event.seq,1);
 const unicode=Buffer.from(JSON.stringify({...e,seq:2,t_ms:200,demo_phase:'关节测试'})+'\n');const cut=unicode.indexOf(Buffer.from('关'))+1;
 fs.appendFileSync(log,unicode.subarray(0,cut));await delay(120);assert.equal((await snap()).event.seq,1);
 fs.appendFileSync(log,unicode.subarray(cut));await delay(120);assert.equal((await snap()).event.demo_phase,'关节测试');
 fs.appendFileSync(log,'{"bad":true}\n');await delay(120);assert.equal((await snap()).event,null);assert.ok((await snap()).error);
 }finally{p.kill();await new Promise(r=>p.once('exit',r));fs.rmSync(dir,{recursive:true});}
});
