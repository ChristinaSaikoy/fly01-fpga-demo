"""Manual E/S control, optional window limit, no neural or motor command generation."""
import struct
from wire import STATUS

def decode(kind,session,step,payload,now):
    if kind!=STATUS or len(payload) not in (40,64):return None
    v=struct.unpack('<IIi7I',payload[:40])
    row=dict(received=now,session=session,model_step=step,source_seq=v[0],dn_mask=v[1],
        yaw_q20=v[2],result_age_cycles=v[3],adopted_age_cycles=v[4],flags=v[5],
        deadline_miss=v[6],bad_packets=v[7],overwrites=v[8],drops=v[9])
    if len(payload)==64:
        row['motor_uart_frame_count']=int.from_bytes(payload[40:44],'little')
        row['motor_uart_accepted_frame']=payload[44:64].split(b'\0',1)[0].decode('ascii',errors='replace')
    return row

def projected_pwm(yaw):
    n=abs(yaw)*40//1048576
    return [n,-n] if yaw<0 else [-n,n]

class PwmStats:
    def __init__(self):
        self.nonzero=0;self.peak=0;self.armed_peak=0;self.last_step=None
        self.last_motor_nonzero=None
    def add(self,row):
        amplitude=abs(projected_pwm(row['yaw_q20'])[0]);self.peak=max(self.peak,amplitude)
        if amplitude:self.nonzero+=1;self.last_step=row['model_step']
        if row['flags']&4 and not row['flags']&8:self.armed_peak=max(self.armed_peak,amplitude)
        frame=row.get('motor_uart_accepted_frame','')
        if frame.startswith('$pwm:') and frame.endswith('#'):
            try:values=[int(v) for v in frame[5:-1].split(',')]
            except ValueError:values=[]
            if len(values)==4 and any(values):self.last_motor_nonzero=frame
    def snapshot(self):return dict(nonzero_records=self.nonzero,peak_pwm=self.peak,armed_peak_pwm=self.armed_peak,last_nonzero_step=self.last_step,last_motor_nonzero_frame=self.last_motor_nonzero)

class ManualControl:
    def __init__(self,write,event,clock,continuous=False):
        self.write,self.event,self.clock=write,event,clock
        self.continuous=continuous
        self.latest=None;self.pending_until=None;self.enable_at=None;self.armed_seen=False
        self.stop_at=None;self.stop_confirmed=False;self.stop_warning=False
        self.bench_at=None;self.bench_seen=False
        self.message='已连接，保持停车；请先启动 V2 并移动手或身体'
    def send(self,data,reason):
        n=self.write(data)
        if n!=len(data):raise IOError('Incomplete E/S write')
        self.event('CONTROL_WRITE',ascii=data.decode(),reason=reason)
    def stop(self,reason='manual_stop'):
        self.pending_until=None;self.enable_at=None;self.armed_seen=False
        self.bench_at=None;self.bench_seen=False
        self.stop_at=self.clock();self.stop_confirmed=False;self.stop_warning=False
        self.message='已发停车，等待 FPGA 确认'
        self.send(b'S',reason)
    def request_enable(self):
        if self.pending_until is not None or self.enable_at is not None or self.bench_at is not None:return
        self.pending_until=float('inf') if self.continuous else self.clock()+5
        self.message='动作已开放，等待有效神经输出；点击关闭动作停止' if self.continuous else '等待有效活动和非零神经输出（最多5秒）'
        self.event('MANUAL_ENABLE_REQUEST',wait_seconds=None if self.continuous else 5,
                   maximum_window_seconds=None if self.continuous else 8)
    def request_bench(self):
        if self.bench_at is not None:return
        if self.latest is None or 'motor_uart_accepted_frame' not in self.latest:
            self.message='当前FPGA没有底座诊断功能，请先装载新版制品';return
        if self.clock()-self.latest['received']>.3:
            self.message='没有新鲜FPGA状态，不发送底座测试';return
        self.stop('before_explicit_bench')
        self.send(b'B','explicit_750ms_chassis_diagnostic')
        self.bench_at=self.clock();self.stop_at=None
        self.message='底座诊断：固定±1200，FPGA限时0.75秒；这不是神经控制结果'
    def update(self,row):
        now=self.clock();previous=self.latest;self.latest=row
        f=row['flags'];fault=bool(f&16) or bool((f>>6)&255)
        if previous and row['session']!=previous['session']:
            self.stop('session_changed');self.message='相机会话变化，已停车；需要重新手动开放'
        if fault and (self.enable_at is not None or self.pending_until is not None or self.bench_at is not None):
            self.stop('core_fault');self.message='神经故障，已停车'
        if self.enable_at is not None:
            if f&4:self.armed_seen=True
            elif self.armed_seen:
                self.stop('autonomous_disarm');self.message='FPGA 已撤销使能；不会自动重新开放'
        if self.bench_at is not None:
            if f&16384:self.bench_seen=True
            elif self.bench_seen:self.stop('hardware_bench_ended')
        if self.stop_at is not None and now-self.stop_at>=.15 and not f&(4|16384):
            if not self.stop_confirmed:self.event('FPGA_DISARM_CONFIRMED',session=row['session'],step=row['model_step'])
            self.stop_confirmed=True
        self.tick()
    def tick(self):
        now=self.clock();row=self.latest
        fresh=row is not None and now-row['received']<=.3
        if self.continuous and self.pending_until is not None and not fresh:
            self.stop('diagnostic_stale');return
        if self.pending_until is not None:
            if now>=self.pending_until:
                self.pending_until=None;self.message='没有等到可执行的神经输出；请移动物体后再点开放'
                self.event('ENABLE_REQUEST_EXPIRED')
            elif fresh:
                f=row['flags']
                safe=(f&63)==35 and row['session']>0 and row['model_step']>0 and row['source_seq']>0
                safe=safe and not f&16384
                safe=safe and max(row['result_age_cycles'],row['adopted_age_cycles'])<12500000
                # R13 preserves the sign of every nonzero Q20 sample before PWM truncation.
                has_output = row['yaw_q20'] != 0 if self.continuous else projected_pwm(row['yaw_q20']) != [0,0]
                if safe and has_output:
                    self.send(b'E','manual_continuous' if self.continuous else 'manual_single_window')
                    self.enable_at=now;self.pending_until=None;self.armed_seen=False;self.stop_at=None
                    self.message='动作持续开放；点击关闭动作停止' if self.continuous else '控制窗口已开放，最多8秒；请观察轮子'
        if self.enable_at is not None:
            reason=None
            if not fresh:reason='diagnostic_stale'
            elif not self.continuous and now-self.enable_at>=8:reason='eight_second_limit'
            elif not self.armed_seen and now-self.enable_at>=1.5:reason='enable_not_confirmed'
            if reason:self.stop(reason)
        if self.bench_at is not None and (not fresh or now-self.bench_at>=1):
            self.stop('bench_host_guard')
        if self.stop_at is not None and not self.stop_confirmed and now-self.stop_at>=1:
            if not self.stop_warning:
                self.message='停车尚未确认；如轮子仍转，请关闭底座电源'
                self.event('STOP_UNCONFIRMED');self.stop_warning=True
    def snapshot(self):
        return dict(message=self.message,row=self.latest,pending=self.pending_until is not None,
            seconds_left=max(0,8-(self.clock()-self.enable_at)) if self.enable_at is not None and not self.continuous else 0,
            stop_confirmed=self.stop_confirmed)
