"""Localhost HTTP transport for FULL_BACKEND_CORE_V1."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from FULL_BACKEND_CORE_V1 import FullBackendCoreV1, PROTOCOL_VERSION

HOST="127.0.0.1"
PORT=18741
CORE=FullBackendCoreV1()
if CORE.service_ready:
    CORE.warmup()

class Handler(BaseHTTPRequestHandler):
    server_version="FLY01FullBackendHTTP/1.0"
    protocol_version="HTTP/1.1"

    def log_message(self,fmt,*args):
        pass

    def _send(self,status,obj):
        raw=json.dumps(obj,separators=(",",":"),ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(raw)))
        self.send_header("Connection","close")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path=="/status":
            self._send(200,CORE.status())
        else:
            self._send(404,{"status":"ERROR","error_code":"NOT_FOUND"})

    def _read_json(self):
        try:
            n=int(self.headers.get("Content-Length","0"))
            if n<=0 or n>2_000_000:
                raise ValueError("invalid body length")
            raw=self.rfile.read(n)
            obj=json.loads(raw.decode("utf-8"))
            if not isinstance(obj,dict):
                raise ValueError("JSON body must be object")
            return obj,None
        except Exception as exc:
            return None,{"protocol_version":PROTOCOL_VERSION,"status":"ERROR",
                         "error_code":"MALFORMED_PACKET","message":str(exc),
                         "replayed_response":"NO"}

    def do_POST(self):
        req,err=self._read_json()
        if err is not None:
            self._send(400,err)
            return
        if self.path=="/step":
            out=CORE.step(req)
            code=200 if out.get("status")=="PASS" else 409
            self._send(code,out)
        elif self.path=="/reset":
            out=CORE.reset(req)
            code=200 if out.get("status")=="PASS" else 409
            self._send(code,out)
        else:
            self._send(404,{"status":"ERROR","error_code":"NOT_FOUND"})

def main():
    startup=ROOT/"STARTUP_INTEGRITY.json"
    startup.write_text(json.dumps(CORE.status(),indent=2),encoding="utf-8")
    if not CORE.service_ready:
        raise SystemExit("SERVICE_READY=NO")
    httpd=ThreadingHTTPServer((HOST,PORT),Handler)
    httpd.daemon_threads=True
    print(json.dumps({"service_ready":True,"host":HOST,"port":PORT,
                      "backend_id":"FULL_BACKEND_CORE_V1"}),flush=True)
    httpd.serve_forever()

if __name__=="__main__":
    main()
