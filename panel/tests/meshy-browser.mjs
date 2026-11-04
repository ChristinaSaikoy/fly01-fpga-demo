import fs from 'node:fs';import path from 'node:path';import assert from 'node:assert/strict';import {chromium} from '../scripts/browser-runtime.mjs';
const out=path.resolve(process.env.VISUAL_OUTPUT||'verification/meshy-r6');fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true}),errors=[],badRequests=[],checks=[];
try{
 const page=await browser.newPage({viewport:{width:1440,height:960}});page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=400&&!r.url().endsWith('favicon.ico'))badRequests.push(r.url());});
 await page.goto(process.env.TEST_URL||'http://127.0.0.1:8879');await page.waitForLoadState('networkidle');
 await page.waitForFunction(()=>document.querySelector('#scene').dataset.model);
 const model=await page.locator('#scene').evaluate(e=>JSON.parse(e.dataset.model));
 assert.equal(model.source,'ROBOT_GLTF');assert.equal(model.nodes.length,17);assert.ok(model.textured>0);assert.ok(Math.abs(model.floor+.88)<1e-5);
 assert.ok(Math.abs(model.forward[0])<1e-5&&model.forward[2]<-.98);checks.push('17 Meshy nodes, atlas textures, one basis transform, forward -Z and floor fit');
 await page.screenshot({path:path.join(out,'01-meshy-hero.png')});
 const seek=async t=>{await page.locator('#seek').evaluate((el,value)=>{el.value=value;el.dispatchEvent(new Event('input'));},t);await page.waitForTimeout(120);};
 await page.locator('#r6').click();await page.waitForFunction(()=>document.querySelector('#source').textContent==='R6真实记录回放');
 await seek(4000);const pose=()=>page.locator('#scene').evaluate(e=>({angle:e.dataset.angle,travel:e.dataset.travel,model:e.dataset.model}));const a=await pose();
 assert.notEqual(Number(a.angle),0);await page.waitForTimeout(250);assert.deepEqual(await pose(),a);checks.push('R6 record drives calibrated command illustration; pause freezes pose');
 await page.screenshot({path:path.join(out,'02-r6-recorded.png')});
 assert.equal(await page.locator('[data-target="left"]').isDisabled(),true);assert.match(await page.locator('#visionState').innerText(),/未提供/);checks.push('no fabricated R6 target position');
 await page.locator('#camera').click();await page.locator('#camera').click();await page.waitForTimeout(1200);assert.deepEqual(await pose(),a);await page.screenshot({path:path.join(out,'03-meshy-top.png')});checks.push('three camera modes preserve motion and local joint pose');
 await seek(Number(await page.locator('#seek').getAttribute('max')));const stopped=await pose();await page.waitForTimeout(350);assert.deepEqual(await pose(),stopped);checks.push('R6 final ACKed zero freezes body and joints');
 await page.locator('#live').click();await page.waitForTimeout(500);const frozen=await pose();await page.waitForTimeout(400);assert.deepEqual(await pose(),frozen);checks.push('unconfigured live mode freezes, never substitutes synthetic');
 const fail=await browser.newPage();await fail.route('**/*.glb',route=>route.abort());fail.on('pageerror',()=>{});await fail.goto(process.env.TEST_URL||'http://127.0.0.1:8879');await fail.getByText('模型加载失败',{exact:true}).waitFor();assert.equal(await fail.locator('#play').isDisabled(),true);await fail.close();checks.push('model load failure is explicit and playback disabled; no procedural fallback');
 assert.deepEqual(errors,[]);assert.deepEqual(badRequests,[]);
 fs.writeFileSync(path.join(out,'RESULT.json'),JSON.stringify({checks,model,errors,badRequests},null,2));console.log(JSON.stringify({checks,errors,badRequests},null,2));
}finally{await browser.close();}
