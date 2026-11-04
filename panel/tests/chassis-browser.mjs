// Isolated browser API simulation; no serial hardware is accessed.
import fs from 'node:fs';import assert from 'node:assert/strict';import {spawn} from 'node:child_process';
import {chromium} from '../scripts/browser-runtime.mjs';
const out='D:/FPGA-AUTO/tasks/WORK-29-CHASSIS-LINK-20261104';
const origin='http://127.0.0.1:18888';
const server=spawn(process.execPath,['server.mjs'],{env:{...process.env,PORT:'18888'},windowsHide:true,stdio:['ignore','pipe','pipe']});
let browser;const commands=[],errors=[];
const s={token:'isolated-test',connected:true,fresh:true,can_arm:true,pending:false,enabled:false,
 zero_confirmed:true,i2c_fault:false,manual_retry_supported:true,pwm_adjust_supported:true,right_trim:500,right_cap:1800,
 wheel_left:0,wheel_right:0,chassis_testing:false,chassis_check:null,chassis_test:null,message:'已连接，保持停车'};
try{
 await new Promise((ok,fail)=>{server.stdout.once('data',ok);server.once('error',fail);server.once('exit',c=>fail(Error('server exit '+c)));});
 browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage({viewport:{width:1680,height:1050}});
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/control',async route=>{
  if(route.request().method()==='POST'){
   const b=route.request().postDataJSON();commands.push(b);
   if(b.cmd==='inspect_chassis')s.chassis_check={ok:true,battery_v:5.8,motor_type:4};
   if(b.cmd==='chassis_test'){s.chassis_testing=true;s.can_arm=false;s.chassis_test={level:b.level,acked:false};}
   if(b.cmd==='chassis_feedback')s.chassis_test.observation=b.observation;
   await route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true})});
  }else await route.fulfill({contentType:'application/json',body:JSON.stringify(s)});
 });
 await page.goto(origin);await page.waitForLoadState('domcontentloaded');
 assert.equal(await page.locator('#testChassis').isDisabled(),true);
 await page.locator('#raised').check();await page.waitForFunction(()=>!document.getElementById('inspectChassis').disabled);
 await page.locator('#inspectChassis').click();await page.waitForFunction(()=>document.getElementById('chassisPower').textContent.includes('5.8'));
 assert.equal(commands.some(x=>x.cmd==='chassis_test'),false);
 await page.locator('#testChassis').click();await page.waitForFunction(()=>document.getElementById('testChassis').disabled);
 assert.equal(commands.find(x=>x.cmd==='chassis_test').level,1800);assert.equal(await page.locator('#armDevice').isDisabled(),true);
 Object.assign(s,{chassis_testing:false,can_arm:true});Object.assign(s.chassis_test,{acked:true,left:-1800,right:1800});
 await page.waitForFunction(()=>document.getElementById('chassisResult').textContent.includes('-1800'));
 await page.locator('#chassisNoMotion').click();await page.waitForFunction(()=>document.getElementById('chassisResult').textContent.includes('没有转动'));
 await page.locator('#stopDevice').click();assert.equal(commands.at(-1).cmd,'stop');
 await page.screenshot({path:out+'/CHASSIS_PANEL.png'});
 assert.deepEqual(errors,[]);assert.equal(commands.some(x=>x.cmd==='arm'),false);
 fs.writeFileSync(out+'/BROWSER_RESULT.json',JSON.stringify({status:'PASS',hardware_accessed:false,checks:['explicit power inspection only','fixed pulse request forwards selected level','neural control blocked during pulse','physical feedback separate from ACK','stop remains available'],errors},null,2));
 console.log('CHASSIS_BROWSER_PASS');
}finally{if(browser)await browser.close();server.kill();await new Promise(ok=>server.once('exit',ok));}
