import * as THREE from 'three';
import {loadMeshy} from './meshy.js';
import {createVision} from './vision.js';
import {Motion,parseReplay,poseAt} from './motion.js';
import {SnapshotReceiver} from './transport.js';
const $=id=>document.getElementById(id),scene=new THREE.Scene();scene.background=new THREE.Color(0x091017);scene.fog=new THREE.Fog(0x091017,15,32);
const camera=new THREE.PerspectiveCamera(44,innerWidth/innerHeight,.05,100),renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setSize(innerWidth,innerHeight);$('scene').append(renderer.domElement);
scene.add(new THREE.HemisphereLight(0xccefff,0x303025,3));const sun=new THREE.DirectionalLight(0xffffff,3);sun.position.set(3,6,4);scene.add(sun);
const grid=new THREE.GridHelper(30,60,0x557079,0x1a303a);grid.position.y=-.9;scene.add(grid);let fly;try{fly=await loadMeshy();scene.add(fly);$('scene').dataset.model=JSON.stringify(fly.userData.status);}catch(e){$('state').textContent='模型加载失败';$('notice').textContent=String(e.message);document.querySelectorAll('button,input,select').forEach(x=>x.disabled=true);throw e;}
const axis=new THREE.AxesHelper(1.1);axis.position.set(-2,-.89,-2);scene.add(axis);
const compass=new THREE.Mesh(new THREE.RingGeometry(1.62,1.64,96),new THREE.MeshBasicMaterial({color:0x44656b,side:THREE.DoubleSide}));compass.rotation.x=-Math.PI/2;compass.position.y=-.885;scene.add(compass);
const vision=createVision(scene);
const CAM_BASE=-Math.PI+.6;
let displayDirection=1;
let replay=null,t=0,playing=false,live=false,m=new Motion(),cameraMode=0,camYaw=CAM_BASE,camHeight=4,camRadius=7,prev=performance.now(),generation=0,notice='',receiver=new SnapshotReceiver(),inFlight=false,builtinDemo=false,targetSide='front';
function selectTarget(side,heading=fly.rotation.y){targetSide=side;vision.place(heading,side);document.querySelectorAll('[data-target]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.target===side)));}
document.querySelectorAll('[data-target]').forEach(b=>b.onclick=()=>selectTarget(b.dataset.target));
$('distance').oninput=()=>{vision.setDistance($('distance').value);$('distanceValue').textContent=Number($('distance').value).toFixed(1);};
function load(text,demo=false){
 const r=parseReplay(text);replay=r;live=false;generation++;t=0;playing=false;m=new Motion();camYaw=CAM_BASE;prev=performance.now();builtinDemo=demo;
 notice=`已载入 ${r.events.length} 条，丢弃重复/乱序 ${r.discarded} 条`;
 $('seek').disabled=false;$('seek').max=r.duration;$('distance').value=3;$('distance').oninput();selectTarget(demo?'front':'off',0);$('chapters').hidden=!demo;
}
async function preset(route){const ticket=++generation;try{const r=await fetch(route);if(!r.ok)throw Error('样本加载失败');const text=await r.text();if(ticket===generation)load(text,route==='/demo');}catch(e){if(ticket===generation)notice=e.message;}}
function playPause(){if(!live&&replay){if(t>=replay.duration)t=0;playing=!playing;prev=performance.now();}}
function seek(value){if(!live&&replay){t=Math.max(0,Math.min(value,replay.duration));playing=false;prev=performance.now();}}
$('play').onclick=playPause;
$('reset').onclick=()=>{if(!live){seek(0);camYaw=CAM_BASE;selectTarget(targetSide,0);}};
$('camera').onclick=()=>{cameraMode=(cameraMode+1)%3;$('camera').textContent=['镜头：跟随','镜头：固定','镜头：俯视'][cameraMode];};
$('displayDirection').onclick=()=>{displayDirection=-displayDirection;$('displayDirection').textContent=displayDirection===1?'显示方向：反转':'显示方向：原始';};
$('demo').onclick=()=>preset('/demo');$('r6').onclick=()=>preset('/r6');$('seek').oninput=()=>{if(replay)seek(Number($('seek').value));};
$('speed').onchange=()=>{prev=performance.now();};
$('file').onchange=async e=>{const f=e.target.files[0];if(!f)return;const ticket=++generation;try{if(f.size>8*1024*1024)throw Error('日志限制8MB');const text=await f.text();if(ticket===generation)load(text);}catch(ex){if(ticket===generation)notice=ex.message;}e.target.value='';};
$('live').onclick=()=>{live=true;playing=false;generation++;receiver=new SnapshotReceiver();m=receiver.motion;camYaw=CAM_BASE;notice='等待只读日志快照';$('seek').disabled=true;$('chapters').hidden=true;poll();};
document.querySelectorAll('[data-at]').forEach(b=>b.onclick=()=>seek(Number(b.dataset.at)));
addEventListener('keydown',e=>{if(e.repeat||e.target.closest('input,select,button,summary,textarea')||live)return;if(e.code==='Space'){e.preventDefault();playPause();}else if(e.code==='Home'){e.preventDefault();$('reset').click();}else if(e.code==='ArrowLeft'||e.code==='ArrowRight'){e.preventDefault();seek(t+(e.code==='ArrowLeft'?-1000:1000));}});
async function poll(){
 if(!live||document.hidden||inFlight)return;const g=generation;inFlight=true;
 try{const r=await fetch(window.flySnapshotURL||'/api/snapshot',{signal:AbortSignal.timeout(1500)});if(!r.ok)throw Error('HTTP '+r.status);const s=await r.json();if(g!==generation||!live||document.hidden)return;
  const oldEpoch=receiver.epoch;receiver.accept(s,performance.now());m=receiver.motion;if(oldEpoch!==receiver.epoch)camYaw=CAM_BASE;notice=window.flySnapshotURL==='/api/live-snapshot'&&!s.connected?'设备未连接 · 保持停止':receiver.notice;
 }catch(e){if(g===generation&&live){receiver.freeze(performance.now(),'连接中断 · 已冻结');notice=receiver.notice;}}
 finally{inFlight=false;}
}
setInterval(poll,100);
document.addEventListener('visibilitychange',()=>{prev=performance.now();if(document.hidden){playing=false;if(live){generation++;receiver.freeze(prev,'页面离开前台 · 已冻结');notice=receiver.notice;}}else if(live)poll();});
const stateNames={ACTIVE:'运行',DISABLED:'未使能',ARMED:'已就绪',STOP_LATCHED:'停止已锁定'};
function frame(now){
 const elapsed=Math.max(0,now-prev),dt=Math.min(elapsed/1000,.1);prev=now;
 if(!live&&replay){
  if(playing){if(elapsed>500){playing=false;notice='画面长时间停顿，已暂停；点击播放继续';}else{t=Math.min(t+elapsed*Number($('speed').value),replay.duration);if(t===replay.duration)playing=false;}}
  m=poseAt(replay,t);
 }
 const clock=live?now:t,angle=m.value(clock),travel=m.distance(clock),displayAngle=displayDirection*angle;fly.rotation.y=displayAngle;
 const allow=!live&&m.last?.origin==='synthetic',view=vision.update(displayAngle,allow);
 fly.userData.updateRig(angle,travel,view.look,view.seen);$('visionState').textContent=view.label;$('visionDetail').textContent=view.detail;if(m.last?.r6){$('visionState').textContent='目标位置未提供';$('visionDetail').textContent='显示神经输出与ACKed轮命令，不推测目标坐标或实际姿态';}
 $('scene').dataset.angle=angle.toFixed(12);$('scene').dataset.travel=travel.toFixed(12);$('scene').dataset.look=view.look.toFixed(12);
 $('scene').dataset.displayAngle=displayAngle.toFixed(12);
 document.querySelectorAll('[data-target]').forEach(b=>b.disabled=!allow);$('distance').disabled=!allow;
 const target=cameraMode===0?displayAngle+CAM_BASE:CAM_BASE,blend=1-Math.exp(-dt/.8);
 camYaw+=Math.atan2(Math.sin(target-camYaw),Math.cos(target-camYaw))*blend;camHeight+=((cameraMode===2?9:4)-camHeight)*blend;camRadius+=((cameraMode===2?.05:7)-camRadius)*blend;
 const fit=innerWidth<650?1.65:innerWidth<1000?1.25:1;
 camera.position.set(Math.sin(camYaw)*camRadius*fit,camHeight*fit,Math.cos(camYaw)*camRadius*fit);camera.lookAt(0,-.1,0);
 const e=m.last,status=m.status(clock),frozen=live&&receiver.frozen;
 $('state').textContent=frozen?'断流 · 已冻结':stateNames[status]||status;
 $('source').textContent=live?(e?.origin==='live_fpga'?'R6实时指令':e?.origin==='synthetic'?'合成日志 · 非实测':'R6实时接入'):(e?.origin==='synthetic'?'合成回放':'R6真实记录回放');
 $('notice').textContent=notice;$('yaw').textContent=e?e.yaw_ref.toFixed(2):'—';$('pwm').textContent=e?`${e.pwm_left} / ${e.pwm_right}`:'—';$('identity').textContent=e?.r6?`S:${e.r6.session}  STEP:${e.r6.model_step}  FRAME:${e.r6.source_seq}`:(e?'合成样例 · 无真实源身份':'等待设备数据');
 const value=e?.yaw_ref||0;$('yawBar').style.left=`${50+Math.min(0,value)/20*50}%`;$('yawBar').style.width=`${Math.abs(value)/20*50}%`;
 $('heading').textContent=`示意转角 ${(displayAngle*180/Math.PI).toFixed(0)}°`;
 $('raw').textContent=JSON.stringify(e,null,2)||'暂无数据';$('play').textContent=playing?'暂停':'播放';$('play').disabled=live||!replay;$('reset').disabled=live;$('speed').disabled=live;
 $('phase').textContent=live?(window.flySnapshotURL==='/api/live-snapshot'?'R6 实时控制 · '+notice:'R6日志旁路 · '+receiver.notice):`${playing?'播放中':'已暂停'} · ${builtinDemo?(status.includes('断流')?'断流冻结':e?.demo_phase||'合成样片'):'日志回放'}`;
 if(!live&&replay){$('seek').value=t;$('time').textContent=`${(t/1000).toFixed(1)} / ${(replay.duration/1000).toFixed(1)} s`;}else $('time').textContent='实时指令观察 · 人工开放动作窗口';
 renderer.render(scene,camera);requestAnimationFrame(frame);
}
renderer.domElement.addEventListener('webglcontextlost',e=>{e.preventDefault();playing=false;notice='图形环境已暂停，请刷新页面恢复';});
function resize(){camera.aspect=innerWidth/innerHeight;camera.setViewOffset(innerWidth,innerHeight,innerWidth<1000?($('source').closest('aside').getBoundingClientRect().width+20)/2:0,0,innerWidth,innerHeight);camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight);}
addEventListener('resize',resize);resize();window.flySnapshotURL='/api/live-snapshot';$('live').click();requestAnimationFrame(frame);
