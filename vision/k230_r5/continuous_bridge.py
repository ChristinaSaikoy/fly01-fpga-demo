"""Preserve frozen first 9000 rows; exact PCG64 continuation thereafter."""
from bridge import Bridge
from wire import NOISE,REQUEST,pack

class ContinuousBridge(Bridge):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        from frozen_noise import Noise
        self.noise=Noise()
    def poll(self):
        incoming=self.uart.read(128)
        if not incoming:return
        request=None
        for kind,session,seq,payload in self.parser.feed(incoming):
            if kind==REQUEST and session==self.session and not payload:request=seq
        if request is None:return
        if request<self.steps:
            self.table.seek(request*59);row=self.table.read(59)
        else:row=self.noise.row(request)
        if len(row)!=59 or row[-1]&128:raise RuntimeError('Noise row length or padding')
        self.send(pack(NOISE,self.session,request,row));self.last_reply=request
