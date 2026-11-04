// Software append fixtures only. This test does not claim a fresh hardware run.
import fs from 'node:fs';import path from 'node:path';import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';import {setTimeout as delay} from 'node:timers/promises';import {chromium} from '../scripts/browser-runtime.mjs';
const base=path.resolve('verification/live-browser-fixture-'+Date.now()),dir=path.join(base,'manual_fixture'),log=path.join(dir,'events.jsonl');fs.mkdirSync(dir,{recursive:true});fs.writeFileSync(log,'');
const server=spawn(process.execPath,['server.mjs','--r6-dir',base],{env:{...process.env,PORT:'18880'},stdio:['ignore','pipe','pipe']});
let browser;const checks=[];let time=100;
const append=(extra={},duplicate=false)=>{const row={event:'NEURAL_I2C_STATUS',time:duplicate?time:++time,session:15,model_step:Math.floor(time),source_seq:Math.floor(time),flags:39,yaw_q20:0,acked_left:-1400,acked_right:1400,last_acks:10,fault:false,fault_code:0,reserved_valid:true,zero_ack:true,...extra};fs.appendFileSync(log,JSON.stringify(row)+'\n');return row;};
try{
 await new Promise((resolve,reject)=>{server.stdout.once('data',resolve);server.once('error',reject);});
 browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage({viewport:{width:1280,height:900}});
 await page.goto('http://127.0.0.1:18880');await page.waitForLoadState('networkidle');await page.locator('#live').click();await delay(200);
 const angle=async()=>Number(await page.locator('#scene').getAttribute('data-angle'));
 for(let i=0;i<6;i++){append();await delay(140);}assert.ok(Math.abs(await angle())>.1);checks.push('R6 append stream animates ACKed command even with zero neural yaw');
 await delay(500);const a=await angle();await delay(300);assert.equal(await angle(),a);checks.push('source outage freezes without synthetic substitution');
 append({},true);await delay(300);assert.equal(await angle(),a);checks.push('duplicate status cannot revive stale motion');
 append();await delay(160);assert.notEqual(await angle(),a);checks.push('new status resumes observer');
 await page.evaluate(()=>{Object.defineProperty(document,'hidden',{value:true,configurable:true});document.dispatchEvent(new Event('visibilitychange'));});
 await delay(80);const hidden=await angle();append();await delay(500);assert.equal(await angle(),hidden);
 await page.evaluate(()=>{Object.defineProperty(document,'hidden',{value:false,configurable:true});document.dispatchEvent(new Event('visibilitychange'));});
 append();await delay(180);assert.ok(Math.abs(await angle()-hidden)<.3);checks.push('background restore has no accumulated large angle jump');
 append({acked_left:0,acked_right:0,flags:35});await delay(250);const z=await angle();await delay(250);assert.equal(await angle(),z);checks.push('ACKed zero/disarm stops observer');
 fs.writeFileSync('verification/LIVE_SOFTWARE_BROWSER.json',JSON.stringify({source:'software append fixtures; NOT a hardware test',hardware_opened:false,checks},null,2));console.log(JSON.stringify({checks},null,2));
}finally{if(browser)await browser.close();server.kill();await new Promise(r=>server.once('exit',r));}
