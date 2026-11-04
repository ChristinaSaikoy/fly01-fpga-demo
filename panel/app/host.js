const $=id=>document.getElementById(id);let token='',connected=false,busy=false,inFlight=false,statusFlight=false,mode='live';
async function state(){if(statusFlight)return;statusFlight=true;try{const r=await fetch('/api/control',{signal:AbortSignal.timeout(1800)});const s=await r.json();token=s.token;connected=s.connected;const allow=mode==='live'&&s.fresh&&s.can_arm&&$('raised').checked&&!busy&&!s.pending;
 $('connectDevice').disabled=mode!=='live'||busy||connected||!$('raised').checked;$('armDevice').disabled=!allow||s.chassis_testing;$('disconnectDevice').disabled=busy||!connected;
 const chassisReady=allow&&!s.enabled&&!s.chassis_testing;
 $('inspectChassis').disabled=!chassisReady;$('testChassis').disabled=!chassisReady;
 $('testChassis').textContent=s.chassis_testing?'正在点动…':'点动底盘 · 0.75秒';
 $('chassisWheel').textContent=s.fresh?`${s.wheel_left??0} / ${s.wheel_right??0}`:'—';
 const check=s.chassis_check;
 $('chassisPower').textContent=check?.ok?`上次读取 ${check.battery_v.toFixed(1)} V · 电机类型 ${check.motor_type}`:check?.error||'电机电源未检查';
 $('chassisPower').dataset.ready=String(!!check?.ok&&check.battery_v>=5&&check.motor_type===4);
 const test=s.chassis_test;
 $('chassisResult').textContent=test?.observation==='moved_stopped'?'现场确认：双轮转动并停下':test?.observation==='no_motion'?'现场反馈：没有转动，需继续查底盘':s.chassis_testing?'固定点动中，请观察双轮':test?.acked?`点动已应答 ${test.left} / ${test.right}，请确认是否转动`:'固定点动经 FPGA→I²C 发送；结束后自动停车';
 for(const id of ['chassisMoved','chassisNoMotion'])$(id).disabled=!test||s.chassis_testing||busy;
 $('retryDevice').disabled=mode!=='live'||busy||!connected||!s.fresh||!s.i2c_fault||!$('raised').checked||s.retrying||s.configuring_pwm||!s.manual_retry_supported;$('retryDevice').textContent=s.retrying?'正在重试…':'重试并解除故障';
 $('applyRightPwm').disabled=mode!=='live'||busy||!connected||!s.fresh||!s.pwm_adjust_supported||s.i2c_fault||s.retrying||s.configuring_pwm||!$('raised').checked;
 $('applyRightPwm').textContent=s.configuring_pwm?'正在等待参数确认…':'应用并关闭动作';
 $('rightPwmReadback').textContent=s.pwm_adjust_supported?`当前参数：补偿 +${s.right_trim} · 上限 ${s.right_cap}`:connected?'当前版本不支持页面调参，需烧录新版':'当前参数：等待FPGA读回';
 $('controlState').textContent=s.message;$('connectionState').textContent=connected?(s.fresh?'设备已连接':'等待设备数据'):'设备未连接';$('connectionState').dataset.ready=String(connected&&s.fresh);
 $('windowTime').textContent=s.chassis_testing?'底盘点动':s.pending?'已请求 · 等待神经输出':s.enabled&&s.fpga_armed?'FPGA 已开放':s.enabled?'等待 FPGA 使能':'已关闭';
 $('stopAck').textContent=s.i2c_fault?'I²C故障锁定 · 停车安全未确认':s.zero_confirmed?'零指令已应答 · 车轮停稳需现场确认':connected?'等待零指令应答':'未连接';
 $('logPath').textContent=s.log||'连接后自动记录';
}catch{$('connectionState').textContent='控制服务离线';$('stopAck').textContent='控制服务离线 · 停车状态未知';for(const id of ['armDevice','retryDevice','applyRightPwm','inspectChassis','testChassis'])$(id).disabled=true;connected=false;}finally{statusFlight=false;}}
async function command(cmd,quiet=false,options={}){if(!token)return;try{const r=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,cmd,raised:$('raised').checked,trim:options.trim,cap:options.cap,level:options.level,observation:options.observation}),signal:AbortSignal.timeout(2500)});const a=await r.json();if(!r.ok||!a.ok)throw Error(a.error||'请求失败');if(cmd==='connect'){window.flySnapshotURL='/api/live-snapshot';$('live').click();}if(!quiet)$('controlState').textContent=cmd==='arm'?'已请求持续开放神经动作':cmd==='stop'?'已请求关闭动作':'操作完成';}catch(e){if(!quiet)$('controlState').textContent=e.message;}finally{if(!quiet)await state();}}
for(const [id,cmd]of[['connectDevice','connect'],['armDevice','arm'],['stopDevice','stop'],['disconnectDevice','disconnect'],['retryDevice','retry']])$(id).onclick=async()=>{if(cmd==='stop'){await command(cmd);return;}busy=true;await command(cmd);busy=false;state();};
$('applyRightPwm').onclick=async()=>{
 if(!$('rightTrim').reportValidity()||!$('rightCap').reportValidity())return;
 const trim=Number($('rightTrim').value),cap=Number($('rightCap').value);
 if(!Number.isInteger(trim)||!Number.isInteger(cap))return;
 busy=true;await command('configure_pwm',false,{trim,cap});busy=false;state();
};
$('inspectChassis').onclick=async()=>{busy=true;await command('inspect_chassis');busy=false;state();};
$('testChassis').onclick=async()=>{busy=true;await command('chassis_test',false,{level:Number($('chassisLevel').value)});busy=false;state();};
for(const [id,observation]of [['chassisMoved','moved_stopped'],['chassisNoMotion','no_motion']])$(id).onclick=async()=>{await command('chassis_feedback',false,{observation});state();};
$('raised').onchange=()=>{if(!$('raised').checked)command('stop');state();};
$('modeLive').onclick=()=>{mode='live';document.body.dataset.mode='live';window.flySnapshotURL='/api/live-snapshot';$('live').click();state();};
$('modeReplay').onclick=async()=>{await command('stop');mode='replay';document.body.dataset.mode='replay';$('r6').click();state();};
$('filmMode').onclick=()=>{document.body.classList.toggle('film');$('filmMode').textContent=document.body.classList.contains('film')?'退出拍摄视图':'拍摄视图';window.dispatchEvent(new Event('resize'));};
function leave(){if(token&&connected)navigator.sendBeacon('/api/control',new Blob([JSON.stringify({token,cmd:'stop'})],{type:'text/plain'}));}
addEventListener('pagehide',leave);document.addEventListener('visibilitychange',()=>{if(document.hidden)leave();});
addEventListener('keydown',e=>{if(e.code==='Escape'){e.preventDefault();command('stop');}});
setInterval(()=>{if(!document.hidden&&connected&&!inFlight){inFlight=true;command('heartbeat',true).finally(()=>inFlight=false);}},400);
setInterval(state,350);state();
