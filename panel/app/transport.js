import {Motion,HOLD} from './motion.js';
// A stale/duplicate response can never revive a frozen pose.
export class SnapshotReceiver {
 constructor(){this.motion=new Motion();this.epoch=null;this.version=null;this.frozen=false;this.notice='等待只读日志快照';}
 freeze(now,message){if(!this.frozen)this.motion.freeze(now);this.frozen=true;this.notice=message;}
 accept(s,now){
  if(!s||!s.connected){this.freeze(now,'未配置日志源；不会自动切换演示');return false;}
  if(!Number.isSafeInteger(s.epoch)||s.epoch<0||!Number.isSafeInteger(s.version)||s.version<0){this.freeze(now,'日志快照格式错误');return false;}
  if(this.epoch!==null&&(s.epoch<this.epoch||(s.epoch===this.epoch&&s.version<this.version)))return false;
  if(s.epoch!==this.epoch){this.motion=new Motion();this.epoch=s.epoch;this.version=null;this.frozen=false;}
  if(s.error||!s.event||!Number.isFinite(s.age_ms)||s.age_ms<0||s.age_ms>=HOLD){this.freeze(now,s.error||'日志过期 · 已冻结');return false;}
  if(s.version===this.version)return false;
  try{
   if(!this.motion.receive(s.event,now-s.age_ms))return false;
   this.version=s.version;this.frozen=false;this.notice='只读日志接入；来源字段由执行端提供';return true;
  }catch(e){this.freeze(now,'无效日志：'+e.message);return false;}
 }
}
