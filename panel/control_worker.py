"""Local UI worker. No device access until an explicit connect command."""
import json
import queue
import struct
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'control_vendor'))
from wire import Parser
from i2c_console import decode_status, select_port
from operator_core import ManualControl


class Controller:
    def __init__(self, emit, clock=time.monotonic, connect_factory=None, log_dir=None, usb_stop=None, driver_inspect=None):
        self.emit, self.clock, self.factory = emit, clock, connect_factory
        self.serial = None
        self.control = None
        self.latest = None
        self.parser = Parser()
        self.lease = None
        self.port = None
        self.message = '设备未连接'
        self.log = None
        self.log_dir = log_dir
        self.retry = None
        self.pwm_request = None
        if usb_stop is None:
            if connect_factory is None:
                from emergency_usb_stop import stop_driver
                usb_stop = stop_driver
            else:
                usb_stop = lambda: dict(ok=True, simulated=True)
        self.usb_stop = usb_stop
        self.usb_stop_result = None
        self.bus_fault_handled = False
        self.driver_inspect = driver_inspect
        self.chassis_check = None
        self.chassis_test = None

    def independent_stop(self, reason):
        try:
            self.usb_stop_result = self.usb_stop()
        except Exception as exc:
            self.usb_stop_result = dict(ok=False, error=str(exc))
        self.event('USB_EMERGENCY_ZERO', reason=reason, **self.usb_stop_result)

    def event(self, name, **fields):
        e = dict(time=self.clock(), event=name, **fields)
        if self.log:
            self.log.write(json.dumps(e, ensure_ascii=False) + '\n')
            self.log.flush()

    def connect(self):
        if self.serial:
            return
        if self.factory:
            port, connection = self.factory()
        else:
            import serial
            from serial.tools.list_ports import comports
            ports = list(comports())
            port = select_port(ports)
            connection = serial.Serial(port=None, baudrate=115200, timeout=.025,
                                       write_timeout=.3, xonxoff=False, rtscts=False)
            connection.dtr = False
            connection.rts = False
            connection.port = port
            connection.open()
        self.serial, self.port = connection, port
        try:
            out = self.log_dir or ROOT / 'runs' / time.strftime('%Y%m%d_%H%M%S')
            out.mkdir(parents=True, exist_ok=True)
            self.log = (out / ('events_' + str(time.time_ns()) + '.jsonl')).open('x', encoding='utf-8')
            self.parser = Parser()
            self.latest = None
            self.control = ManualControl(self.serial.write, self.event, self.clock, continuous=True)
            self.control.stop('panel_connect')
            self.lease = self.clock()
            self.message = '已连接，等待FPGA停车确认'
        except Exception:
            connection.close()
            self.serial = None
            raise

    def safe_to_request(self):
        r = self.latest
        return bool(self.retry is None and self.pwm_request is None and self.serial and r and self.clock()-r['received'] < .3 and
                    (self.control is None or self.control.bench_at is None) and
                    self.lease is not None and self.clock()-self.lease < 1.5 and
                    r['reserved_valid'] and r['zero_ack'] and r['last_acks'] == 10 and
                    not r['fault'] and not r['fault_code'] and
                    not r['flags'] & (4 | 16384) and not ((r['flags'] >> 6) & 255))

    def command(self, cmd, confirmed=False, trim=None, cap=None, level=None, observation=None):
        if cmd == 'connect':
            if not confirmed:
                raise ValueError('请先确认双轮已架空')
            self.connect()
        elif cmd == 'heartbeat':
            if self.serial:
                self.lease = self.clock()
        elif cmd == 'arm':
            if not confirmed or not self.safe_to_request():
                raise ValueError('状态未就绪或已过期，请检查设备和架空状态')
            self.control.request_enable()
        elif cmd == 'inspect_chassis':
            if not confirmed or not self.safe_to_request():
                raise ValueError('先关闭动作并等待零指令应答，再检查底盘')
            self.control.stop('before_chassis_inspection')
            self.independent_stop('before_chassis_inspection')
            if self.driver_inspect is None:
                from chassis_inspect import inspect_driver
                inspector = inspect_driver
            else:
                inspector = self.driver_inspect
            try:
                self.chassis_check = inspector()
                self.event('CHASSIS_INSPECTION', **self.chassis_check)
            except Exception as exc:
                self.chassis_check = dict(ok=False, error=str(exc))
                raise
            finally:
                self.lease = self.clock()
            self.control.message = '底盘电压与配置已读取；未启动电机'
        elif cmd == 'chassis_test':
            if type(level) is not int or level not in (1200, 1600, 1800):
                raise ValueError('点动档位只能为1200、1600或1800')
            if not confirmed or not self.safe_to_request() or not self.latest.get('motion_build'):
                raise ValueError('先关闭神经动作并确认架空，等待零指令应答后点动')
            self.control.stop('before_explicit_chassis_test')
            self.control.send({1200:b'1',1600:b'2',1800:b'3'}[level]+b'B',
                              'explicit_fpga_750ms_chassis_test')
            self.control.bench_at = self.clock()
            self.control.bench_seen = False
            self.control.stop_at = None
            self.lease = self.clock()
            self.chassis_test = dict(level=level, duration_ms=750, acked=False,
                                     left=0, right=0, observation=None)
            self.event('CHASSIS_TEST_REQUEST', level=level, duration_ms=750)
            self.control.message = 'FPGA底盘点动中，0.75秒后停车；请观察双轮'
        elif cmd == 'chassis_feedback':
            if observation not in ('moved_stopped', 'no_motion') or self.chassis_test is None:
                raise ValueError('请先执行一次底盘点动，再记录现场结果')
            self.chassis_test['observation'] = observation
            self.event('CHASSIS_OPERATOR_FEEDBACK', observation=observation)
        elif cmd == 'retry':
            r = self.latest
            if (not confirmed or not self.serial or not r or self.clock()-r['received'] >= .3
                    or not r['reserved_valid'] or not r.get('manual_retry_supported')
                    or not (r['fault'] or r['fault_code'])):
                raise ValueError('请先连接设备并确认架空；仅在新鲜故障状态下重试')
            if self.retry is not None or self.pwm_request is not None:
                raise ValueError('正在处理操作，请等待结果')
            self.control.stop('before_manual_i2c_retry')
            self.lease = self.clock()
            self.retry = dict(deadline=self.clock()+3, sent=False, reset_seen=False,
                              baseline_epoch=r['retry_epoch'], zero_count=0, last_zero_frame=None)
            self.event('I2C_RETRY_REQUEST', baseline_epoch=r['retry_epoch'])
        elif cmd == 'configure_pwm':
            if type(trim) is not int or type(cap) is not int or not (0 <= trim <= 800 and 1200 <= cap <= 2000):
                raise ValueError('右轮补偿需为0至800整数，上限需为1200至2000整数')
            r = self.latest
            if (not confirmed or not self.serial or not r or self.clock()-r['received'] >= .3
                    or not r['reserved_valid'] or not r.get('pwm_adjust_supported')
                    or r['fault'] or r['fault_code']):
                raise ValueError('请先确认架空并连接支持调参的版本；故障时先重试恢复')
            if self.retry is not None or self.pwm_request is not None:
                raise ValueError('正在处理操作，请等待结果')
            self.control.stop('before_right_pwm_config')
            self.lease = self.clock()
            self.pwm_request = dict(deadline=self.clock()+3, sent=False, trim=trim, cap=cap)
            self.event('RIGHT_PWM_CONFIG_REQUEST', trim=trim, cap=cap)
        elif cmd == 'stop':
            self.retry = None
            self.pwm_request = None
            try:
                if self.control and self.serial:
                    self.control.stop('panel_stop')
            finally:
                self.independent_stop('manual_stop')
            self.message = '已请求停车'
        elif cmd == 'disconnect':
            self.disconnect()
        else:
            raise ValueError('Unsupported command')

    def update_retry(self, row):
        attempt = self.retry
        if attempt is None or self.clock() >= attempt['deadline']:
            return
        if not attempt['sent']:
            if not row['flags'] & (4 | 16384) and not row['busy']:
                attempt.update(sent=True, baseline_epoch=row['retry_epoch'])
                self.control.send(b'R', 'manual_i2c_retry')
            return
        if row.get('manual_retry_supported') and row['retry_epoch'] != attempt['baseline_epoch']:
            attempt['reset_seen'] = True
        if not attempt['reset_seen']:
            return
        if row['fault'] or row['fault_code']:
            self.event('I2C_RETRY_FAILED', reason='fault_after_reset', fault_code=row['fault_code'])
            self.retry = None
            self.control.stop('i2c_retry_failed')
            self.control.message = '重试失败，线路仍异常；保持动作关闭'
            return
        zero = (row['reserved_valid'] and row['zero_ack'] and row['last_acks'] == 10
                and row['acked_left'] == row['acked_right'] == 0
                and not row['flags'] & (4 | 16384))
        if not zero:
            attempt['zero_count'] = 0
            attempt['last_zero_frame'] = None
        elif row['frames'] != attempt['last_zero_frame']:
            attempt['zero_count'] += 1
            attempt['last_zero_frame'] = row['frames']
            if attempt['zero_count'] >= 2:
                self.event('I2C_RETRY_ZERO_CONFIRMED', frames=row['frames'])
                self.retry = None
                self.control.message = '通信已恢复，动作保持关闭；需要时再点开放动作'

    def update_pwm_request(self, row):
        request = self.pwm_request
        if request is None or self.clock() >= request['deadline']:
            return
        if row['fault'] or row['fault_code'] or not row['reserved_valid']:
            self.event('RIGHT_PWM_CONFIG_FAILED', reason='fault_or_invalid_status')
            self.pwm_request = None
            self.control.stop('right_pwm_config_failed')
            self.control.message = '参数未确认：通信异常；动作保持关闭'
            return
        zero = (row['zero_ack'] and row['last_acks'] == 10 and row['acked_left'] == row['acked_right'] == 0
                and not row['flags'] & (4 | 16384))
        if not request['sent']:
            if zero and not row['busy']:
                self.control.send(('T%04d,%04d\n' % (request['trim'], request['cap'])).encode('ascii'),
                                  'manual_right_pwm_config')
                request['sent'] = True
            return
        if (zero and row.get('pwm_adjust_supported') and row['right_trim'] == request['trim']
                and row['right_cap'] == request['cap']):
            self.event('RIGHT_PWM_CONFIG_CONFIRMED', trim=request['trim'], cap=request['cap'])
            self.pwm_request = None
            self.control.message = '右轮参数已确认；动作保持关闭，需要时再点开放动作'

    def step(self):
        if not self.serial:
            return
        now = self.clock()
        was_enabled = self.control.enable_at is not None or self.control.pending_until is not None or self.control.bench_at is not None
        if self.lease is not None and now-self.lease >= 1.5:
            self.retry = None
            self.pwm_request = None
            self.control.stop('panel_lease_expired')
            self.independent_stop('page_lease_expired')
            self.lease = None
            self.message = '页面连接过期，已请求停车'
        chunk = self.serial.read(min(max(getattr(self.serial, 'in_waiting', 0), 1), 4096))
        for kind, session, model_step, payload in self.parser.feed(chunk):
            if kind != 6:
                continue
            motor = decode_status(payload)
            if motor is None:
                continue
            values = struct.unpack('<IIi7I', payload[:40])
            names = ('source_seq', 'dn_mask', 'yaw_q20', 'result_age_cycles',
                     'adopted_age_cycles', 'flags', 'deadline_miss', 'bad_packets',
                     'overwrites', 'diagnostic_drops')
            row = dict(zip(names, values), received=self.clock(), session=session,
                       model_step=model_step, **motor)
            self.latest = row
            if self.chassis_test and row.get('bench_active') and row['last_acks'] == 10 and not row['fault'] and (row['acked_left'] or row['acked_right']):
                self.chassis_test.update(acked=True, left=row['acked_left'], right=row['acked_right'])
            self.event('NEURAL_I2C_STATUS', **row)
            if (row['fault'] or row['fault_code'] or not row['reserved_valid'] or
                    not row['zero_ack'] or row['last_acks'] != 10):
                if self.control.pending_until is not None or self.control.enable_at is not None:
                    self.control.stop('i2c_not_ready')
            if row['fault'] or row['fault_code']:
                if not self.bus_fault_handled:
                    try:
                        self.control.stop('i2c_fault_independent_stop')
                    finally:
                        self.independent_stop('i2c_fault')
                    self.bus_fault_handled = True
            else:
                self.bus_fault_handled = False
            self.control.update(row)
            self.update_retry(row)
            self.update_pwm_request(row)
            self.emit(dict(kind='row', row=dict(row, time=row['received'], event='NEURAL_I2C_STATUS')))
        self.control.tick()
        if was_enabled and self.control.enable_at is None and self.control.pending_until is None and self.control.bench_at is None and not self.bus_fault_handled:
            self.independent_stop('control_disarmed_or_stale')
        if self.retry is not None and self.clock() >= self.retry['deadline']:
            self.event('I2C_RETRY_FAILED', reason='timeout_or_old_firmware')
            self.retry = None
            self.control.stop('i2c_retry_timeout')
            self.control.message = '重试超时；请检查接线，并确认已烧录支持重试的版本'

        if self.pwm_request is not None and self.clock() >= self.pwm_request['deadline']:
            self.event('RIGHT_PWM_CONFIG_FAILED', reason='readback_timeout')
            self.pwm_request = None
            self.control.stop('right_pwm_config_timeout')
            self.control.message = '右轮参数确认超时，未宣称已应用；动作保持关闭'

    def snapshot(self):
        c, r = self.control, self.latest
        fresh = bool(r and self.clock()-r['received'] < .3)
        enabled = bool(c and (c.pending_until is not None or c.enable_at is not None))
        bus_fault = bool(r and (r['fault'] or r['fault_code']))
        message = c.message if c and self.lease is not None else self.message
        if self.retry is not None:
            message = '正在重试通信并确认零输出；动作保持关闭'
        elif self.pwm_request is not None:
            message = '正在应用右轮参数并等待FPGA读回；动作保持关闭'
        elif bus_fault:
            name = {1: 'BUS_STUCK', 2: 'SCL_TIMEOUT', 3: 'I2C_NACK',
                    4: 'COMMAND_OUT_OF_RANGE', 5: 'ACK_COUNT_ERROR', 6: 'SCL_EDGE_LOST'}.get(r['fault_code'], 'UNKNOWN')
            suffix = 'USB备用零命令已发，仍须观察停稳' if self.usb_stop_result and self.usb_stop_result.get('ok') else '备用停车未确认，请关闭电机电池开关'
            message = 'I²C故障锁定（%s）；%s' % (name, suffix)
        return dict(kind='status', connected=self.serial is not None, port=self.port, retrying=self.retry is not None,
                    chassis_check=self.chassis_check, chassis_test=self.chassis_test,
                    chassis_testing=bool(c and c.bench_at is not None),
                    fpga_armed=bool(r and r.get('neural_armed')),
                    wheel_left=r.get('acked_left',0) if r else 0,
                    wheel_right=r.get('acked_right',0) if r else 0,
                    usb_stop_result=self.usb_stop_result,
                    configuring_pwm=self.pwm_request is not None,
                    right_trim=r.get('right_trim') if r else None, right_cap=r.get('right_cap') if r else None,
                    manual_retry_supported=bool(r and r.get('manual_retry_supported')),
                    pwm_adjust_supported=bool(r and r.get('pwm_adjust_supported')),
                    fresh=fresh, can_arm=self.safe_to_request(),
                    pending=bool(c and c.pending_until is not None),
                    enabled=enabled, window_remaining=0,
                    message=message, i2c_fault=bus_fault,
                    zero_confirmed=bool(fresh and r['reserved_valid'] and r['last_acks'] == 10 and r['zero_ack'] and
                                        not r['fault'] and not r['fault_code'] and
                                        not r['flags'] & (4 | 16384) and
                                        r['acked_left'] == r['acked_right'] == 0),
                    crc_errors=self.parser.bad,
                    log=str(self.log.name) if self.log else None)

    def disconnect(self):
        self.retry = None
        self.pwm_request = None
        connection = self.serial
        try:
            if connection:
                try:
                    self.control.stop('panel_disconnect')
                finally:
                    self.independent_stop('disconnect')
        finally:
            self.serial = None
            if connection:
                connection.close()
            if self.log:
                self.log.close()
            self.log = None
            self.latest = None
            self.control = None
            self.lease = None
            self.message = '设备已断开；请现场确认停稳'


def process_commands(controller, batch, emit):
    stopping = any(x.get('cmd') in ('stop', 'disconnect') for x in batch)
    for x in sorted(batch, key=lambda x: x.get('cmd') not in ('stop', 'disconnect')):
        try:
            if stopping and x.get('cmd') in ('arm', 'connect', 'retry', 'configure_pwm', 'inspect_chassis', 'chassis_test'):
                raise ValueError('停车优先，请再次手动操作')
            controller.command(x.get('cmd'), x.get('raised') is True, trim=x.get('trim'), cap=x.get('cap'),
                               level=x.get('level'), observation=x.get('observation'))
            emit(dict(kind='reply', id=x.get('id'), ok=True))
        except Exception as exc:
            emit(dict(kind='reply', id=x.get('id'), ok=False, error=str(exc)))


def main():
    commands = queue.Queue(maxsize=64)
    ended = threading.Event()
    def read_commands():
        try:
            for line in sys.stdin:
                try:
                    item = json.loads(line)
                    commands.put(item, timeout=.1)
                except Exception:
                    ended.set()
                    break
        finally:
            ended.set()
    def emit(item):
        print(json.dumps(item, ensure_ascii=True), flush=True)
    threading.Thread(target=read_commands, daemon=True).start()
    controller = Controller(emit)
    last = 0
    try:
        while not ended.is_set():
            batch = []
            while not commands.empty():
                batch.append(commands.get_nowait())
            process_commands(controller, batch, emit)
            try:
                controller.step()
            except Exception as exc:
                controller.message = '连接异常：' + str(exc)
                emit(dict(kind='error', message=controller.message))
                try:
                    controller.disconnect()
                except Exception:
                    pass
            if time.monotonic()-last >= .1:
                emit(controller.snapshot())
                last = time.monotonic()
            time.sleep(.005 if controller.serial else .02)
    finally:
        controller.disconnect()


if __name__ == '__main__':
    main()
