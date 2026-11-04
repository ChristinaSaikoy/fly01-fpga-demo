import {spawn} from 'node:child_process';
import {StringDecoder} from 'node:string_decoder';
export class ControlBridge {
 constructor(root,onRow){
  this.state={connected:false,fresh:false,can_arm:false,message:'设备未连接'};this.wait=new Map();this.seq=0;
  this.worker=spawn(process.env.FLY_PYTHON||'python',['-u','-B',root+'/control_worker.py'],{cwd:root,windowsHide:true,stdio:['pipe','pipe','pipe']});
  let partial='',decoder=new StringDecoder('utf8');
  this.worker.stdout.on('data',data=>{partial+=decoder.write(data);const lines=partial.split('\n');partial=lines.pop();for(const line of lines){try{const v=JSON.parse(line);if(v.kind==='status')this.state=v;else if(v.kind==='row')onRow(v.row);else if(v.kind==='reply'){const w=this.wait.get(v.id);if(w){clearTimeout(w.timer);this.wait.delete(v.id);w.resolve(v);}}else if(v.kind==='error')this.state={...this.state,message:v.message};}catch{}}});
  this.worker.stderr.on('data',()=>{});
  this.worker.on('error',e=>this.failed('控制服务启动失败：'+e.message));
  this.worker.on('exit',()=>this.failed('控制服务已退出'));
 }
 failed(message){this.state={connected:false,fresh:false,can_arm:false,message};for(const w of this.wait.values()){clearTimeout(w.timer);w.resolve({ok:false,error:message});}this.wait.clear();}
 command(cmd,raised=false,options={}){if(!this.worker.stdin.writable)return Promise.resolve({ok:false,error:'控制服务不可用'});const id=++this.seq;return new Promise(resolve=>{const timer=setTimeout(()=>{this.wait.delete(id);resolve({ok:false,error:'控制服务响应超时；请检查现场状态'});},2000);this.wait.set(id,{resolve,timer});this.worker.stdin.write(JSON.stringify({id,cmd,raised,trim:options.trim,cap:options.cap,level:options.level,observation:options.observation})+'\n');});}
 close(){this.worker.stdin.end();}
}
