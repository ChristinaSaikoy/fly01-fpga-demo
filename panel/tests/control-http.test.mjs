import {test} from 'node:test';import assert from 'node:assert/strict';import {spawn} from 'node:child_process';
test('control API requires same origin, token and explicit raised confirmation before device access',async()=>{
 const origin='http://127.0.0.1:18881';const p=spawn(process.execPath,['server.mjs'],{env:{...process.env,PORT:'18881'},stdio:['ignore','pipe','pipe']});
 try{
  await new Promise((ok,fail)=>{p.stdout.once('data',ok);p.once('error',fail);p.once('exit',c=>fail(Error('server exit '+c)));});
  const bootstrap=await fetch(origin+'/api/control').then(r=>r.json());assert.equal(bootstrap.connected,false);assert.equal(bootstrap.can_arm,false);
  const send=(body,headers={Origin:origin})=>fetch(origin+'/api/control',{method:'POST',headers:{'Content-Type':'application/json',...headers},body:JSON.stringify(body)});
  assert.equal((await send({cmd:'arm',token:bootstrap.token},{})).status,403);
  assert.equal((await send({cmd:'arm',token:bootstrap.token},{Origin:'https://example.com'})).status,403);
  assert.equal((await send({cmd:'arm',token:'wrong'})).status,403);
  assert.equal((await send({cmd:'pwm',token:bootstrap.token})).status,400);
  assert.equal((await send({cmd:'connect',raised:false,token:bootstrap.token})).status,409);
  assert.equal((await send({cmd:'arm',raised:true,token:bootstrap.token})).status,409);
  assert.equal((await send({cmd:'retry',raised:true,token:bootstrap.token})).status,409);
  assert.equal((await send({cmd:'configure_pwm',raised:true,trim:500,cap:1900,token:bootstrap.token})).status,409);
  assert.equal((await send({cmd:'configure_pwm',raised:true,trim:500,cap:1900,token:bootstrap.token},{})).status,403);
  assert.equal((await send({cmd:'configure_pwm',raised:true,trim:true,cap:1900,token:bootstrap.token})).status,409);
  assert.equal((await send({cmd:'stop',token:bootstrap.token})).status,200);
  assert.equal((await fetch(origin+'/api/live-snapshot').then(r=>r.json())).event,null);
  assert.equal((await fetch(origin+'/api/control').then(r=>r.json())).connected,false);
 }finally{p.kill();await new Promise(ok=>p.once('exit',ok));}
});
