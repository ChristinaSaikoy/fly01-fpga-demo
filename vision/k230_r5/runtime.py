"""Full-field visual engineering prototype. No motor/PWM calculation on K230."""
import os,sys,time,gc,ujson
from machine import UART,FPIOA
from ybUtils.YbKey import YbKey
from media.sensor import Sensor
from media.display import Display
from media.media import MediaManager
from features import extract,encode
from rf_map import RF_MAP
from continuous_bridge import ContinuousBridge as Bridge
from wire import pack

ROOT='/sdcard/fly01_v2/'
ACTIVITY_HOLD_MS=500  # Execution permission only; does not duplicate visual events.

def activity_permission(now,last_activity):
    return last_activity is not None and 0<=time.ticks_diff(now,last_activity)<ACTIVITY_HOLD_MS

def next_session():
    try:
        with open(ROOT+'sessions.log','r') as f:journal=f.read()
    except OSError:previous=0
    else:
        if journal and not journal.endswith('\n'):raise RuntimeError('Session journal incomplete')
        previous=0
        for line in journal.splitlines():
            value=int(line)
            if value!=previous+1:raise RuntimeError('Session journal corrupt')
            previous=value
    if not 0<=previous<0xffffffff:raise RuntimeError('Application session exhausted/corrupt')
    value=previous+1
    with open(ROOT+'sessions.log','a') as f:f.write(str(value)+'\n')
    return value

def sample(img):
    pixels=[]
    width,height=img.width(),img.height()
    for y in range(24):
        for x in range(32):
            rgb=img.get_pixel((2*x+1)*width//64,(2*y+1)*height//48)
            if isinstance(rgb,(tuple,list)):
                pixels.append((77*rgb[0]+150*rgb[1]+29*rgb[2])>>8)
            else:pixels.append(int(rgb)&255)
    return pixels

def main(test_ms=0):
    sensor=None;uart=None;bridge=None;f=None;old=None;display=False;media=False
    feature_log=None
    session=next_session();frames=0;previous=None;last_log=0;last_activity=None
    os.exitpoint(os.EXITPOINT_ENABLE)
    print('FLY01_V2_START '+ujson.dumps({'session':session,'field':'32x24/8x6','encoding':'311 temporal proxy','version':1}))
    try:
        f=FPIOA();old=(f.get_pin_func(9),f.get_pin_func(10))
        f.set_function(9,FPIOA.UART1_TXD,ie=0,oe=1)
        f.set_function(10,FPIOA.UART1_RXD,ie=1,oe=0)
        uart=UART(UART.UART1,baudrate=115200,bits=UART.EIGHTBITS,parity=UART.PARITY_NONE,stop=UART.STOPBITS_ONE,timeout=1)
        bridge=Bridge(uart,session,ROOT+'noise_9000.bin',steps=9000,expected_sha='d3832f1eda924ba42f393197c105e0371d94897ab2434c1329ae4c8b83a7ce84')
        sensor=Sensor();sensor.reset();sensor.set_framesize(width=640,height=480)
        sensor.set_pixformat(Sensor.RGB565);sensor.set_hmirror(False);sensor.set_vflip(False)
        display=True;Display.init(Display.ST7701,width=640,height=480,to_ide=True)
        media=True;MediaManager.init();sensor.run();time.sleep_ms(1000)
        feature_log=open(ROOT+'features_%d.jsonl'%session,'w')
        feature_log.write(ujson.dumps({'version':'V2_CONTINUOUS_EXACT_NOISE_R5','session':session})+'\n');feature_log.flush()
        print('WORK15_SESSION_READY')
        began=time.ticks_ms()
        key=YbKey();released=False;pressed_since=None
        while not bridge.table_ended and (not test_ms or time.ticks_diff(time.ticks_ms(),began)<test_ms):
            os.exitpoint();bridge.poll();start=time.ticks_ms()
            if not key.is_pressed():released=True;pressed_since=None
            elif released:
                if pressed_since is None:pressed_since=start
                elif time.ticks_diff(start,pressed_since)>=800:
                    print('FLY01_V2_KEY_STOP');break
            img=sensor.snapshot()
            if img is None:raise RuntimeError('Camera frame absent')
            pixels=sample(img);field=extract(pixels,previous);previous=pixels
            mask=encode(field,RF_MAP);frames+=1;bridge.seq+=1
            age=max(0,time.ticks_diff(time.ticks_ms(),start))+25
            valid=age<250
            now=time.ticks_ms()
            if valid and field['active']:last_activity=now
            permitted=valid and activity_permission(now,last_activity)
            flags=int(valid)|(int(permitted)<<1)
            bridge.send(pack(7,session,bridge.seq,bytes((flags,0))+min(age,65535).to_bytes(2,'little')+mask))
            bridge.poll()
            active=sum(bin(x).count('1') for x in mask)
            # Actual board LCD; screen displays field rather than a colour target.
            img.draw_string_advanced(0,0,32,'FLY-01 V2  S:%d F:%d'%(session,frames),color=(255,255,255))
            img.draw_string_advanced(0,40,28,'ACT:%d HOLD:%d STEP:%s'%(active,int(permitted),str(bridge.last_reply)),color=(0,255,0))
            for zone,a in enumerate(field['areas']):
                if a[1]>=12:img.draw_rectangle((zone%8*80,zone//8*80,80,80),color=(255,255,0),thickness=2)
            Display.show_image(img,x=0,y=0)
            now=time.ticks_ms()
            if time.ticks_diff(now,last_log)>=1000:
                record=ujson.dumps({'session':session,'frame':frames,'valid':valid,'active':field['active'],
                    'global_change':field['global_change'],'age_ms':age,'mask_hex':mask.hex(),'areas':field['areas'],
                    'noise_step':bridge.last_reply,'packet_bad':bridge.parser.bad,
                    'activity_permission':permitted,'activity_hold_ms':ACTIVITY_HOLD_MS})
                feature_log.write(record+'\n');feature_log.flush()
                print('V2_FRAME '+record)
                last_log=now
            img=None;gc.collect()
            for _ in range(3):bridge.poll();time.sleep_ms(1)
        print('FLY01_V2_NOISE_EOF' if bridge.table_ended else 'FLY01_V2_TEST_COMPLETE')
    finally:
        errors=[]
        if bridge:
            try:bridge.close()
            except BaseException as e:errors.append('bridge:'+str(e))
        if uart:
            try:uart.deinit()
            except BaseException as e:errors.append('uart:'+str(e))
        if sensor:
            try:sensor.stop()
            except BaseException as e:errors.append('sensor:'+str(e))
        if display:
            try:Display.deinit()
            except BaseException as e:errors.append('display:'+str(e))
        if media:
            try:MediaManager.deinit()
            except BaseException as e:errors.append('media:'+str(e))
        if feature_log:
            try:feature_log.close()
            except BaseException as e:errors.append('log:'+str(e))
        if f and old:
            try:f.set_function(9,old[0]);f.set_function(10,old[1])
            except BaseException as e:errors.append('mux:'+str(e))
        print('FLY01_V2_END '+ujson.dumps({'frames':frames,'cleanup_errors':errors}))
