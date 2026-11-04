"""Instrument-only synchronous sidecar; raw evidence/commit/schedule unchanged."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import struct
import time
import threading
import heapq

from uart_host import EvidenceLog, Client

FORMAT=struct.Struct('<QIIQQQQqQII')
OPS={'ReadFile':1,'WriteFile':2,'SetCommTimeouts':3,'ClearCommError':4,
     'BINARY_WRITE':10,'BINARY_FLUSH':11,'INDEX_WRITE':12,'INDEX_FLUSH':13,
     'RECORD_TOTAL':14,'PARSER_FEED':15,'PARSER_ABANDON':16,'EXCHANGE':17,'PACKET_ENCODE':18}


class BinaryTrace:
    def __init__(self,directory,max_records=12000000):
        self.directory=Path(directory)
        self.directory.mkdir(exist_ok=False)
        self.stream=(self.directory/'calls.bin').open('xb',buffering=65536)
        self.seq=0
        self.max_records=max_records
        self.closed=False
        self.failed=False
        self.owner_thread=threading.get_ident()
        self.trace_write_total_ns=0
        self.slowest_trace_writes=[]

    def record(self,name,start,end,cpu_start,cpu_end,raw_seq,requested=0,actual=0,value=1,error=0):
        if self.closed or self.seq>=self.max_records or threading.get_ident()!=self.owner_thread:
            self.failed=True
            raise RuntimeError('DIAGNOSTIC_CLOSED_OR_CAPACITY_EXCEEDED')
        data=FORMAT.pack(self.seq,OPS[name],error,start,end,cpu_start,cpu_end,value,raw_seq,requested,actual)
        before=time.perf_counter_ns()
        written=self.stream.write(data)
        after=time.perf_counter_ns()
        duration=after-before
        self.trace_write_total_ns+=duration
        item=(duration,self.seq,raw_seq,before,after)
        if len(self.slowest_trace_writes)<32:
            heapq.heappush(self.slowest_trace_writes,item)
        elif duration>self.slowest_trace_writes[0][0]:
            heapq.heapreplace(self.slowest_trace_writes,item)
        if written!=len(data):
            self.failed=True
            raise OSError('DIAGNOSTIC_SHORT_WRITE')
        self.seq+=1

    def close(self):
        if not self.closed:
            self.closed=True
            try:
                self.stream.flush()
                os.fsync(self.stream.fileno())
            finally:
                self.stream.close()
            with (self.directory/'calls.bin').open('rb') as source:
                digest=hashlib.file_digest(source,'sha256').hexdigest()
            with (self.directory/'INDEX.json').open('x',encoding='utf-8') as stream:
                json.dump(dict(status='FAILED' if self.failed else 'COMPLETE',records=self.seq,format=FORMAT.format,
                    record_bytes=FORMAT.size,ops=OPS,max_records=self.max_records,
                    buffer_bytes=65536,synchronous=True,asynchronous_queue=False,
                    trace_write_total_ns=self.trace_write_total_ns,
                    slowest_trace_writes=[dict(duration_ns=x[0],seq=x[1],raw_seq=x[2],start_ns=x[3],end_ns=x[4])
                        for x in sorted(self.slowest_trace_writes,reverse=True)],
                    raw_bytes_omitted=0,physical_arrival_time_claimed=False,
                    call_trace_sha256=digest),stream,indent=2)
                stream.flush()
                os.fsync(stream.fileno())


class DiagnosticEvidenceLog(EvidenceLog):
    def __init__(self,directory,origin):
        super().__init__(directory,origin)
        self.trace=BinaryTrace(Path(directory).parent/'native_diagnostics')

    def record(self,kind,data=b'',**fields):
        wall,cpu=time.perf_counter_ns(),time.thread_time_ns()
        try:
            return self._record(kind,data,**fields)
        except BaseException:
            self.trace.failed=True
            self.trace.record('RECORD_TOTAL',wall,time.perf_counter_ns(),cpu,time.thread_time_ns(),
                self.seq,requested=len(data),value=0,error=1)
            raise

    def _record(self,kind,data=b'',**fields):
        # Same byte/index writes, order, timestamp placement and flush as the accepted logger.
        start,cpu_start=time.perf_counter_ns(),time.thread_time_ns()
        raw_seq=self.seq
        spans=[]
        def perform(name,call):
            wall,cpu=time.perf_counter_ns(),time.thread_time_ns()
            value=call()
            spans.append((name,wall,time.perf_counter_ns(),cpu,time.thread_time_ns()))
            return value
        offset=self.binary.tell()
        perform('BINARY_WRITE',lambda:self.binary.write(data))
        perform('BINARY_FLUSH',self.binary.flush)
        row=dict(sequence=self.seq,monotonic_ns=time.monotonic_ns(),kind=kind,
            origin=self.origin,offset=offset,length=len(data),sha256=hashlib.sha256(data).hexdigest(),**fields)
        perform('INDEX_WRITE',lambda:self.index.write(json.dumps(row,sort_keys=True)+'\n'))
        perform('INDEX_FLUSH',self.index.flush)
        self.seq+=1
        end,cpu_end=time.perf_counter_ns(),time.thread_time_ns()
        for name,wall,stop,cpu,cpu_stop in spans:
            self.trace.record(name,wall,stop,cpu,cpu_stop,raw_seq,requested=len(data))
        self.trace.record('RECORD_TOTAL',start,end,cpu_start,cpu_end,raw_seq,requested=len(data))

    def close(self):
        try:
            super().close()
        finally:
            self.trace.close()


class MeasuredParser:
    def __init__(self,parser,evidence):
        self.parser,self.evidence=parser,evidence

    def __getattr__(self,name):
        return getattr(self.parser,name)

    def feed(self,data):
        wall,cpu=time.perf_counter_ns(),time.thread_time_ns()
        errors=self.parser.errors
        result=self.parser.feed(data)
        end,cpu_end=time.perf_counter_ns(),time.thread_time_ns()
        self.evidence.trace.record('PARSER_FEED',wall,end,cpu,cpu_end,self.evidence.seq,
            requested=len(data),actual=len(result),error=self.parser.errors-errors)
        return result

    def abandon_partial(self):
        wall,cpu=time.perf_counter_ns(),time.thread_time_ns()
        old=len(self.parser.buffer)
        self.parser.abandon_partial()
        self.evidence.trace.record('PARSER_ABANDON',wall,time.perf_counter_ns(),cpu,
            time.thread_time_ns(),self.evidence.seq,requested=old)


class MeasuredClient(Client):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.parser=MeasuredParser(self.parser,self.port.evidence)

    def exchange(self,request,**kwargs):
        wall,cpu=time.perf_counter_ns(),time.thread_time_ns()
        seq=self.port.evidence.seq
        error=0
        try:
            return super().exchange(request,**kwargs)
        except BaseException:
            error=1
            raise
        finally:
            self.port.evidence.trace.record('EXCHANGE',wall,time.perf_counter_ns(),cpu,
                time.thread_time_ns(),seq,value=request.opcode,error=error)


def measured_packet(evidence,operation):
    trace=getattr(evidence,'trace',None)
    if trace is None:
        return operation()
    wall,cpu=time.perf_counter_ns(),time.thread_time_ns()
    seq=evidence.seq
    try:
        return operation()
    finally:
        trace.record('PACKET_ENCODE',wall,time.perf_counter_ns(),cpu,time.thread_time_ns(),seq)


def verify_trace(directory):
    directory=Path(directory)
    index=json.loads((directory/'INDEX.json').read_text())
    path=directory/'calls.bin'
    with path.open('rb') as stream:
        digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if index['status']!='COMPLETE' or index['format']!=FORMAT.format or digest!=index['call_trace_sha256']:
        raise RuntimeError('DIAGNOSTIC_INDEX_OR_HASH')
    if path.stat().st_size!=index['records']*FORMAT.size:
        raise RuntimeError('DIAGNOSTIC_TRUNCATED')
    counts={}
    with path.open('rb') as stream:
        for seq in range(index['records']):
            row=FORMAT.unpack(stream.read(FORMAT.size))
            if row[0]!=seq or row[1] not in OPS.values() or row[4]<row[3] or row[6]<row[5]:
                raise RuntimeError('DIAGNOSTIC_SEQUENCE_OR_CLOCK')
            counts[row[1]]=counts.get(row[1],0)+1
    return dict(status='PASS',records=index['records'],op_counts=counts,raw_coverage_verified_separately=True)
