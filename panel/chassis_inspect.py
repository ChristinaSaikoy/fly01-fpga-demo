"""Read driver power/configuration only, while the FPGA is parked."""
import re
import time


def inspect_driver():
    import serial
    from serial.tools.list_ports import comports
    ports = [p for p in comports() if p.vid == 0x1a86 and p.pid == 0x7522]
    if len(ports) != 1:
        raise RuntimeError('未找到唯一驱动板 USB；检查底盘需要连接驱动板 USB')
    c = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=.2,
                      xonxoff=False, rtscts=False, dsrdtr=False)
    c.dtr = False
    c.rts = False
    c.port = ports[0].device
    def query(command):
        if c.write(command) != len(command):
            raise IOError('底盘查询未完整发送')
        data = bytearray()
        end = time.monotonic() + .35
        while time.monotonic() < end and len(data) < 4096:
            data.extend(c.read(min(max(c.in_waiting, 1), 4096-len(data))))
        return data.decode('ascii', errors='replace')
    try:
        c.open()
        c.reset_input_buffer()
        voltage = query(b'$read_vol#')
        config = query(b'$read_flash#')
        v = re.search(r'\$Battery:(\d+(?:\.\d+)?)V#', voltage)
        motor = re.search(r'^Motor_type:(\d+)\s*$', config, re.M)
        dead = re.search(r'^Dead_Zone:(\d+)\s*$', config, re.M)
        version = re.search(r'^Motor_Version:([^\r\n]+)', config, re.M)
        if not all((v, motor, dead, version)):
            raise RuntimeError('驱动板回复不完整，未确认底盘电源或配置')
        return dict(ok=True, port=c.port, battery_v=float(v.group(1)),
                    motor_type=int(motor.group(1)), dead_zone=int(dead.group(1)),
                    firmware=version.group(1), measured_at=time.time(),
                    physical_motion_confirmed=False)
    finally:
        if c.is_open:
            c.close()
