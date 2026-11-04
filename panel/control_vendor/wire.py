"""MicroPython-compatible binary UART-A codec; no hardware imports."""
MAGIC=b'\xa5\x5a'
VERSION=1
OBS,NOISE,REQUEST,STOP,ENABLE,STATUS=1,2,3,4,5,6
MAX_PAYLOAD=64

def crc16(data):
    crc=0xffff
    for b in data:
        crc ^= b<<8
        for _ in range(8):
            crc=((crc<<1)^0x1021)&0xffff if crc&0x8000 else (crc<<1)&0xffff
    return crc

def pack(kind,session,seq,payload=b''):
    if not 0<session<=0xffffffff or not 0<=seq<=0xffffffff or len(payload)>64:
        raise ValueError('bounds')
    body=bytes((1,kind))+session.to_bytes(4,'little')+seq.to_bytes(4,'little')+bytes((len(payload),))+payload
    return MAGIC+body+crc16(body).to_bytes(2,'little')

class Parser:
    def __init__(self):self.buf=b'';self.bad=0
    def feed(self,data):
        self.buf+=data
        result=[]
        while len(self.buf)>=2:
            pos=self.buf.find(MAGIC)
            if pos<0:self.buf=self.buf[-1:];break
            self.buf=self.buf[pos:]
            if len(self.buf)<13:break
            size=self.buf[12]
            if self.buf[2]!=1 or size>64:
                self.bad+=1;self.buf=self.buf[1:];continue
            length=15+size
            if len(self.buf)<length:break
            frame=self.buf[:length]
            if crc16(frame[2:-2])!=int.from_bytes(frame[-2:],'little'):
                self.bad+=1;self.buf=self.buf[1:];continue
            self.buf=self.buf[length:]
            result.append((frame[3],int.from_bytes(frame[4:8],'little'),int.from_bytes(frame[8:12],'little'),frame[13:-2]))
        return result

def observation(session,seq,usable,group,age_ms):
    if group not in (0,1,2,3) or not 0<=age_ms<=65535:raise ValueError('observation')
    return pack(OBS,session,seq,bytes((bool(usable),group))+age_ms.to_bytes(2,'little'))
