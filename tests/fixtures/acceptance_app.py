"""Disposable executor capability probe, not the S6 product implementation."""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

VALUE='';CLAIMS=set();LOCK=threading.Lock()
LAG=0
BROKEN=False
PAGE='''<!doctype html><link rel="icon" href="data:,"><input id="value"><button id="send">Send</button><output id="observed"></output>
<script>
document.querySelector('#send').onclick=()=>fetch('/value',{method:'POST',body:document.querySelector('#value').value});
setInterval(async()=>{let v=await(await fetch('/value')).json();setTimeout(()=>{document.querySelector('#observed').textContent=v.value},LAG)},100);
</script>'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        value=({'status':'ok'} if self.path=='/health' else
            {'source_sha':os.environ.get('FABRIQUINHA_SOURCE_SHA')} if self.path=='/identity' else
            {'value':VALUE} if self.path=='/value' else None)
        data=json.dumps(value).encode() if value is not None else PAGE.replace('LAG',str(LAG)).encode()
        self.send_response(200);self.send_header('Content-Type','application/json' if value is not None else 'text/html')
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

    def do_POST(self):
        global VALUE
        data=self.rfile.read(int(self.headers.get('Content-Length','0'))).decode()
        with LOCK:
            code=200
            if self.path=='/claim':
                if data not in CLAIMS and len(CLAIMS)>=2:code=409
                else:CLAIMS.add(data)
            elif not BROKEN:VALUE=data
        self.send_response(code);self.send_header('Content-Length','0');self.end_headers()

    def log_message(self,*args):pass


if __name__=='__main__':ThreadingHTTPServer(('0.0.0.0',int(sys.argv[1])),Handler).serve_forever()
