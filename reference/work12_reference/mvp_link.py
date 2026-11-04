"""New host adapter; frozen UART encoding and snapshot checks stay unchanged."""
import sys,time,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'vendor'))
from uart_wire import *
from uart_host import Client,LinkFault,validate_snapshot

class ResyncParser(Parser):
    """Strict wire decode; invalid delimiters can seed resync, valid frames cannot share."""
    def feed(self,data):
        messages=[]
        for value in data:
            if value==DELIM:
                closed=bool(self.started and (self.buffer or self.escaped or self.invalid))
                valid=False
                if closed:
                    try:
                        if self.escaped or self.invalid:raise ValueError('escape/overflow')
                        messages.append(decode_raw(bytes(self.buffer)));valid=True
                    except ValueError:self.errors+=1
                self.buffer.clear();self.escaped=self.invalid=False
                self.started=not valid
                continue
            if not self.started or self.invalid:continue
            if self.escaped:
                if value not in (DELIM^0x20,ESC^0x20):self.invalid=True;continue
                self.buffer.append(value^0x20);self.escaped=False
            elif value==ESC:self.escaped=True
            else:self.buffer.append(value)
            if len(self.buffer)>MAX_RAW:self.buffer.clear();self.invalid=True
        return messages

class MVPClient(Client):
    def __init__(self,port,session,timeout=.5,retries=1,cancel=None,scope_deadline_ns=None):
        if timeout!=.5 or retries!=1:raise ValueError('V1 preserves 500ms / one retry timing')
        super().__init__(port,session,timeout,retries)
        self.parser=ResyncParser();self.cancel=cancel or threading.Event();self.scope_deadline_ns=scope_deadline_ns
        self.stats=dict(retries=0,timeouts=0,bad_segments=0,stale_responses=0,duplicate_responses=0,
                        recoveries=0,max_exchange_ms=0)
    def exchange(self,request,*,retry=True,generation_change=False):
        wire=encode(request);started=time.monotonic();attempts=1+(self.retries if retry else 0);initial_bad=self.stats['bad_segments']
        total_deadline=started+self.timeout*attempts
        if self.scope_deadline_ns is not None:total_deadline=min(total_deadline,self.scope_deadline_ns/1e9)
        for attempt in range(attempts):
            if time.monotonic()>=total_deadline:self.fault='MVP_SCOPE_OR_TOTAL_DEADLINE';raise LinkFault(self.fault)
            if self.cancel.is_set():self.fault='CANCELLED_COMPLETION_UNCERTAIN';raise LinkFault(self.fault)
            deadline=min(total_deadline,time.monotonic()+self.timeout)
            self.port.evidence.record('REQUEST',wire,opcode=request.opcode,attempt=attempt)
            try:
                self.port.write(wire,deadline)
                while time.monotonic()<deadline:
                    if self.cancel.is_set():raise LinkFault('CANCELLED_COMPLETION_UNCERTAIN')
                    old_errors=self.parser.errors
                    replies=self.parser.feed(self.port.read(deadline))
                    self.stats['bad_segments']+=self.parser.errors-old_errors
                    selected=None
                    for reply in replies:
                        if reply.opcode==0xff:raise LinkFault('endpoint rejected request; reset required')
                        identity=(reply.opcode==request.opcode|0x80 and reply.session==request.session
                            and reply.frame==request.frame and reply.view==request.view
                            and (generation_change or reply.generation==request.generation))
                        if not identity:
                            self.stats['stale_responses']+=1;self.port.evidence.record('STALE_RESPONSE',encode(reply));continue
                        values=payload_words(reply.payload)
                        if not values or values[0]!=0:raise LinkFault('endpoint status '+repr(values))
                        if selected is not None:
                            if reply!=selected[0]:raise LinkFault('conflicting duplicate response')
                            self.stats['duplicate_responses']+=1;continue
                        selected=(reply,values[1:])
                    if selected:
                        self.port.evidence.record('RESPONSE_VALIDATED',encode(selected[0]),attempt=attempt)
                        if attempt or self.stats['bad_segments']>initial_bad:self.stats['recoveries']+=1
                        self.stats['max_exchange_ms']=max(self.stats['max_exchange_ms'],(time.monotonic()-started)*1000)
                        return selected
                raise TimeoutError('MVP finite exchange deadline')
            except TimeoutError:
                self.stats['timeouts']+=1;self.parser.abandon_partial()
                if attempt+1<attempts:
                    self.stats['retries']+=1;continue # SAME request bytes and identity only
                self.fault='UNCERTAIN_REQUEST_COMPLETION';raise
            except Exception:
                self.fault='OUTPUT_INVALID_OR_UNCERTAIN';raise
        raise AssertionError('unreachable')
