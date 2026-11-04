export const HOLD=250;
export function validate(e){
 if(!e||e.schema!=='FLY01_VIEW_TELEMETRY_V1') throw Error('遥测格式不匹配');
 if(!['synthetic','recorded_fpga','live_fpga'].includes(e.origin)) throw Error('未知来源');
 if(typeof e.session_id!=='string'||!e.session_id.length||e.session_id.length>128) throw Error('无效会话');
 for(const k of ['seq','t_ms']) if(!Number.isSafeInteger(e[k])||e[k]<0) throw Error('无效 '+k);
 for(const k of ['yaw_ref','pwm_left','pwm_right']) if(!Number.isFinite(e[k])) throw Error('无效 '+k);
 if(e.execution_yaw_ref!==undefined&&(!Number.isFinite(e.execution_yaw_ref)||Math.abs(e.execution_yaw_ref)>20))throw Error('无效执行示意参考');
 if(Math.abs(e.yaw_ref)>20) throw Error('yaw 超出 ±20');
 if(!['DISABLED','ARMED','ACTIVE','STOP_LATCHED'].includes(e.execution_state)) throw Error('未知执行状态');
 if(!['sent','requested','unknown'].includes(e.command_status)) throw Error('未知命令状态');
 if(e.stop_reason!==null&&typeof e.stop_reason!=='string') throw Error('无效停止原因');
 return e;
}
export function executionYaw(e){return e?.execution_yaw_ref??e?.yaw_ref??0;}
export function gate(e){
 if(!e) return '等待数据';
 if(e.stop_reason||e.execution_state!=='ACTIVE') return e.stop_reason||e.execution_state;
 if(e.command_status!=='sent') return '尚未确认发送';
 if(!executionYaw(e)||(!e.pwm_left&&!e.pwm_right)) return '停止';
 if(Math.sign(e.pwm_right-e.pwm_left)!==Math.sign(executionYaw(e))||e.pwm_left*e.pwm_right>=0) return '轮命令方向待核对';
 return '运行';
}
export class Motion {
 constructor(){this.reset();}
 reset(){this.angle=0;this.travel=0;this.last=null;this.at=0;this.retired=new Set();this.dropped=0;this.gaps=0;this.frozen=false;}
 receive(event,at){
  const e=validate(event); if(!Number.isFinite(at))throw Error('无效到达时刻');
  if(this.last){
   if(at<this.at){this.dropped++;return false;}
   if(e.session_id!==this.last.session_id){if(this.retired.has(e.session_id)){this.dropped++;return false;}this.retired.add(this.last.session_id);this.angle=0;this.travel=0;}
   else {if(e.seq<=this.last.seq||e.t_ms<this.last.t_ms||at<this.at){this.dropped++;return false;}
    this.travel=this.distance(at);this.angle=this.value(at); if(e.seq>this.last.seq+1)this.gaps+=e.seq-this.last.seq-1;
   }
  }
  this.last={...e};this.at=at;this.frozen=false;return true;
 }
 delta(now){return (!this.frozen&&gate(this.last)==='运行'?executionYaw(this.last)/20:0)*Math.max(0,Math.min(HOLD,now-this.at))/1000;}
 value(now){return this.angle+this.delta(now);}
 distance(now){return this.travel+Math.abs(this.delta(now));}
 status(now){return !this.last?'等待数据':this.frozen||now-this.at>=HOLD?'断流 · 已冻结':gate(this.last);}
 freeze(now){this.travel=this.distance(now);this.angle=this.value(now);this.frozen=true;this.at=now;}
}
export function parseReplay(text){
 const events=[];let clock=0,last=null;const retired=new Set(),m=new Motion();let discarded=0;
 text.split(/\r?\n/).forEach((line,i)=>{if(!line.trim())return;let e;try{e=validate(JSON.parse(line));}catch(err){throw Error(`第 ${i+1} 行：${err.message}`);}
  if(last&&e.session_id===last.session_id){if(e.seq<=last.seq||e.t_ms<last.t_ms){discarded++;return;}clock+=e.t_ms-last.t_ms;}
  else if(last){if(retired.has(e.session_id)){discarded++;return;}retired.add(last.session_id);clock+=HOLD;}
  if(!Number.isSafeInteger(clock))throw Error('日志时间跨度过大');
  m.receive(e,clock);events.push({at:clock,event:{...e},angle:m.angle,travel:m.travel});last=e;
 });
 if(!events.length)throw Error('日志为空');return {events,discarded,duration:clock+1000};
}
// Prefix poses are built once. Random seeking is O(log n), not a full log replay per frame.
export function poseAt(replay,time){
 const m=new Motion();let lo=0,hi=replay.events.length;
 while(lo<hi){const mid=(lo+hi)>>>1;if(replay.events[mid].at<=time)lo=mid+1;else hi=mid;}
 if(lo){const p=replay.events[lo-1];m.last={...p.event};m.at=p.at;m.angle=p.angle;m.travel=p.travel;}
 return m;
}
