// Synthetic API only. No hardware is opened or motion commanded.
import fs from 'node:fs';import path from 'node:path';import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';import {chromium} from '../scripts/browser-runtime.mjs';
const output=path.resolve('D:/FPGA-AUTO/tasks/WORK-26-R11-PWM-RETRY-20261103/verification');fs.mkdirSync(output,{recursive:true});
const server=spawn(process.execPath,['server.mjs'],{env:{...process.env,PORT:'18887'},stdio:['ignore','pipe','pipe'],windowsHide:true});
let browser;const checks=[],commands=[],errors=[];
let state={token:'synthetic-browser-token',connected:true,fresh:true,can_arm:true,pending:false,enabled:false,retrying:false,configuring_pwm:false,
 i2c_fault:false,zero_confirmed:true,manual_retry_supported:true,pwm_adjust_supported:true,right_trim:400,right_cap:1800,message:'已连接，保持停车'};
try{
 await new Promise((resolve,reject)=>{server.stdout.once('data',resolve);server.once('error',reject);server.once('exit',c=>reject(Error('server exit '+c)));});
 browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage({viewport:{width:1680,height:1050}});
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/control',async route=>{
  const request=route.request();
  if(request.method()==='POST'){
   const body=request.postDataJSON();commands.push(body);
   if(body.cmd==='configure_pwm')Object.assign(state,{configuring_pwm:true,can_arm:false,message:'正在应用右轮参数并等待FPGA读回；动作保持关闭'});
   if(body.cmd==='retry')Object.assign(state,{retrying:true,can_arm:false,message:'正在重试通信并确认零输出；动作保持关闭'});
   await route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true})});
  }else await route.fulfill({contentType:'application/json',body:JSON.stringify(state)});
 });
 await page.goto('http://127.0.0.1:18887');await page.waitForLoadState('domcontentloaded');
 await page.locator('#raised').check();await page.waitForFunction(()=>!document.getElementById('applyRightPwm').disabled);
 assert.equal(await page.locator('#rightTrim').inputValue(),'400');assert.equal(await page.locator('#rightCap').inputValue(),'1800');
 checks.push('default 400/1800 and capability-gated controls visible');
 await page.locator('#rightTrim').fill('500');await page.locator('#rightCap').fill('1900');
 await page.waitForTimeout(800);assert.equal(await page.locator('#rightTrim').inputValue(),'500');
 assert.match(await page.locator('#rightPwmReadback').textContent(),/400.*1800/);
 checks.push('polling readback does not overwrite edited inputs');
 await page.locator('#applyRightPwm').click();await page.waitForFunction(()=>document.getElementById('applyRightPwm').disabled);
 const config=commands.find(x=>x.cmd==='configure_pwm');assert.equal(config.trim,500);assert.equal(config.cap,1900);assert.equal(config.raised,true);
 assert.match(await page.locator('#applyRightPwm').textContent(),/确认/);assert.equal(await page.locator('#armDevice').isDisabled(),true);
 Object.assign(state,{configuring_pwm:false,can_arm:true,right_trim:500,right_cap:1900,message:'右轮参数已确认；动作保持关闭'});
 await page.waitForFunction(()=>document.getElementById('rightPwmReadback').textContent.includes('1900'));
 assert.equal(await page.locator('#windowTime').textContent(),'已关闭');checks.push('application waits for readback and does not open motion');
 const before=commands.filter(x=>x.cmd==='configure_pwm').length;
 await page.locator('#rightTrim').fill('801');await page.locator('#applyRightPwm').click();await page.waitForTimeout(400);
 assert.equal(commands.filter(x=>x.cmd==='configure_pwm').length,before);await page.locator('#rightTrim').fill('500');checks.push('out-of-range input is blocked');
 Object.assign(state,{i2c_fault:true,zero_confirmed:false,can_arm:false,message:'I2C故障锁定'});
 await page.waitForFunction(()=>!document.getElementById('retryDevice').disabled);await page.locator('#retryDevice').click();
 await page.waitForFunction(()=>document.getElementById('retryDevice').textContent.includes('正在'));
 Object.assign(state,{i2c_fault:false,retrying:false,zero_confirmed:true,can_arm:true,message:'通信已恢复，动作保持关闭'});
 await page.waitForFunction(()=>document.getElementById('controlState').textContent.includes('已恢复'));
 assert.equal(commands.filter(x=>x.cmd==='arm').length,0);checks.push('retry is explicit and successful recovery never emits arm');
 await page.screenshot({path:path.join(output,'HOST_R11_UI.png')});
 Object.assign(state,{manual_retry_supported:false,pwm_adjust_supported:false,i2c_fault:true,can_arm:false,right_trim:null,right_cap:null});
 await page.waitForFunction(()=>document.getElementById('rightPwmReadback').textContent.includes('不支持'));
 assert.equal(await page.locator('#retryDevice').isDisabled(),true);assert.equal(await page.locator('#applyRightPwm').isDisabled(),true);checks.push('legacy firmware cannot falsely show adjustable or retry support');
 assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(output,'HOST_R11_BROWSER.json'),JSON.stringify({hardware_opened:false,source:'synthetic browser API',checks,page_errors:errors,commands:commands.map(({token,...x})=>x)},null,2));
 console.log(JSON.stringify({checks,page_errors:errors},null,2));
}finally{if(browser)await browser.close();server.kill();await new Promise(resolve=>server.once('exit',resolve));}
