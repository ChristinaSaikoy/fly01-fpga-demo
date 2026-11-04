"""Independent zero-only USB path. Never sends nonzero PWM or queries."""
import time

def stop_driver():
    import serial
    from serial.tools.list_ports import comports
    ports=[p for p in comports() if p.vid==0x1a86 and p.pid==0x7522]
    if len(ports)!=1:
        return dict(ok=False,error='未找到唯一驱动USB；请关闭电机电池开关')
    connection=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=.2,
                             xonxoff=False,rtscts=False,dsrdtr=False)
    connection.dtr=False;connection.rts=False;connection.port=ports[0].device
    try:
        connection.open()
        command=b'$pwm:0,0,0,0#'
        for _ in range(3):
            if connection.write(command)!=len(command):raise IOError('Incomplete USB zero write')
            time.sleep(.01)
        connection.flush()
        return dict(ok=True,port=ports[0].device,zero_writes=3,physical_stop_confirmed=False)
    except Exception as exc:
        return dict(ok=False,error=str(exc),physical_stop_confirmed=False)
    finally:
        if connection.is_open:connection.close()
