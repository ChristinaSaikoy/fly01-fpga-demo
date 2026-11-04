// Data-only adaptation. Imports no serial, camera or motor-control libraries.
export class R6Adapter {
 constructor(run='r6'){this.run=run;this.lastTime=-Infinity;this.lastStep=-1;this.session=null;this.retired=new Set();this.start=null;this.seq=0;}
 accept(r,origin='recorded_fpga'){
  if(!['NEURAL_I2C_STATUS','EXIT_STATUS'].includes(r?.event))return null;
  const time=r.time??r.received;
  if(!Number.isFinite(time)||time<0||!Number.isSafeInteger(r.session)||r.session<=0||
    !Number.isSafeInteger(r.model_step)||r.model_step<0||!Number.isSafeInteger(r.source_seq)||r.source_seq<0||
    !Number.isSafeInteger(r.flags)||!Number.isFinite(r.yaw_q20)||
    !Number.isInteger(r.acked_left)||!Number.isInteger(r.acked_right)||
    Math.max(Math.abs(r.acked_left),Math.abs(r.acked_right))>2000||typeof r.fault!=='boolean'||
    !Number.isInteger(r.last_acks)||!Number.isInteger(r.fault_code)||
    typeof r.reserved_valid!=='boolean'||typeof r.zero_ack!=='boolean')throw Error('R6 status fields invalid');
  if(time<=this.lastTime)return null;
  if(this.session!==r.session){if(this.retired.has(r.session))return null;
   if(this.session!==null)this.retired.add(this.session);this.session=r.session;this.lastStep=-1;
  }
  if(r.model_step<this.lastStep)return null;
  this.lastTime=time;this.lastStep=r.model_step;if(this.start===null)this.start=time;
  const ready=(r.flags&63)===39&&!(r.flags&16384)&&!((r.flags>>6)&255)&&r.model_step>0&&r.source_seq>0&&
   !r.fault&&!r.fault_code&&r.last_acks===10&&r.zero_ack&&r.reserved_valid;
  const active=ready&&!!(r.acked_left||r.acked_right)&&r.acked_left*r.acked_right<0;
  const failed=r.fault||r.fault_code||!!(r.flags&16)||!r.reserved_valid||r.last_acks!==10||!r.zero_ack;
  return {schema:'FLY01_VIEW_TELEMETRY_V1',origin,session_id:`${this.run}/FPGA-${r.session}`,seq:++this.seq,
   t_ms:Math.round((time-this.start)*1000),yaw_ref:r.yaw_q20/1048576,
   execution_yaw_ref:active?Math.max(-20,Math.min(20,(r.acked_right-r.acked_left)/3200*20)):0,
   pwm_left:r.acked_left,pwm_right:r.acked_right,
   execution_state:failed?'STOP_LATCHED':active?'ACTIVE':r.flags&4?'ARMED':'DISABLED',
   command_status:ready?'sent':'unknown',stop_reason:failed?'R6接口故障':r.flags&8?'执行许可关闭':null,
   r6:{session:r.session,model_step:r.model_step,source_seq:r.source_seq,dn_mask:r.dn_mask??null,
    last_acks:r.last_acks,fault:r.fault,fault_code:r.fault_code,meaning:'ACKed command illustration; not measured pose',
    raw_yaw:r.yaw_q20/1048576}};
 }
}
