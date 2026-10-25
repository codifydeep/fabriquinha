"""Neutral bounded OpenRouter relay. No phase/schema adapters or model fallback.

Policy enablement is local operator configuration, not business approval. The
old calls.json/provider-pause.json formats are retained; no reset/unpause API.
"""
import argparse
from contextlib import contextmanager
from dataclasses import asdict,dataclass
import fcntl
import hmac
import http.client
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import signal
import threading
import time
from urllib.parse import urlsplit
from .artifacts import digest
from .effects import write_json


class Held(RuntimeError):
    def __init__(self,code,status=503):self.code,self.status=code,status;super().__init__(code)


@dataclass(frozen=True)
class Policy:
    version:int
    project:str
    model:str
    max_calls:int
    max_output_tokens:int
    enabled:bool
    client_token:str

    @classmethod
    def parse(cls,value):
        if (not isinstance(value,dict) or set(value)!=set(cls.__dataclass_fields__)
                or type(value['version']) is not int or value['version']!=1
                or not isinstance(value['project'],str) or not re.fullmatch('[a-f0-9]{64}',value['project'])
                or not isinstance(value['model'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.:/-]{1,160}',value['model'])
                or type(value['max_calls']) is not int or not 1<=value['max_calls']<=1000000
                or type(value['max_output_tokens']) is not int or value['max_output_tokens'] not in (2048,4096,8192)
                or type(value['enabled']) is not bool or not isinstance(value['client_token'],str)
                or not re.fullmatch('[A-Za-z0-9_-]{20,128}',value['client_token'])):
            raise ValueError('closed operator model/budget policy required')
        return cls(**value)

    def values(self):return asdict(self)
    def fingerprint(self):return digest(self.values())


class Ledger:
    def __init__(self,root,limit):
        self.root,self.limit=Path(root),limit
        if not self.root.is_dir():raise ValueError('existing private meter directory required')

    @contextmanager
    def lock(self,name,*,nonblocking=False):
        path=self.root/(name+'.lock')
        if path.is_symlink():raise ValueError('unsafe meter lock')
        with os.fdopen(os.open(path,os.O_CREAT|os.O_RDWR,0o600),'a') as file:
            fcntl.flock(file,fcntl.LOCK_EX|(fcntl.LOCK_NB if nonblocking else 0))
            try:yield
            finally:fcntl.flock(file,fcntl.LOCK_UN)

    def owner(self):return self.lock('relay-owner',nonblocking=True)

    def read(self,name):
        path=self.root/name
        if path.is_symlink() or not path.is_file() or path.stat().st_size>4096:raise ValueError('bounded existing meter file required')
        return json.loads(path.read_bytes())

    def save(self,name,value):
        write_json(self.root/name,value)
        descriptor=os.open(self.root,os.O_RDONLY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)

    def state(self):
        value=self.read('calls.json')
        if not isinstance(value,dict) or set(value)!={'calls'} or type(value['calls']) is not int or value['calls']<0:
            raise ValueError('invalid durable counter; never initialize or reset it')
        pause=None;hold=None
        if (self.root/'provider-pause.json').exists():
            pause=self.read('provider-pause.json')
            if (not isinstance(pause,dict) or set(pause)!={'category','upstream_status','call_number'}
                    or (pause['category'],pause['upstream_status']) not in (('upstream_payment_required',402),('upstream_access_denied',401),('upstream_access_denied',403))
                    or type(pause['call_number']) is not int or not 1<=pause['call_number']<=value['calls']):
                raise ValueError('invalid preserved provider pause')
        if (self.root/'relay-hold.json').exists():
            hold=self.read('relay-hold.json')
            if (not isinstance(hold,dict) or set(hold)!={'category','call_number'} or hold['category']!='transport_unknown'
                    or type(hold['call_number']) is not int or not 1<=hold['call_number']<=value['calls']):raise ValueError('invalid relay hold')
        return dict(calls=value['calls'],max_calls=self.limit,remaining=max(0,self.limit-value['calls']),provider_pause=pause,relay_hold=hold)

    def reserve(self):
        with self.lock('counter'):
            value=self.state()
            if value['provider_pause']:raise Held('provider_paused',value['provider_pause']['upstream_status'])
            if value['relay_hold']:raise Held('transport_unknown')
            if not value['remaining']:raise Held('budget_exhausted',429)
            number=value['calls']+1;self.save('calls.json',{'calls':number});return number

    def pause(self,number,status):
        with self.lock('counter'):
            if type(number) is not int or not 1<=number<=self.state()['calls'] or status not in (401,402,403):raise ValueError('actual failed attempt required')
            self.save('provider-pause.json',dict(category='upstream_payment_required' if status==402 else 'upstream_access_denied',
                upstream_status=status,call_number=number))

    def uncertain(self,number):
        with self.lock('counter'):self.save('relay-hold.json',dict(category='transport_unknown',call_number=number))


class Relay:
    def __init__(self,policy,meter,key):self.policy,self.ledger,self.key=policy,Ledger(meter,policy.max_calls),Path(key)

    def status(self):
        result=dict(version=1,project=self.policy.project,policy=self.policy.fingerprint(),model=self.policy.model,enabled=self.policy.enabled,
            max_output_tokens=self.policy.max_output_tokens,max_request_bytes=2*1024*1024,fallback=None,neutral=True,ready=False)
        try:
            value=self.ledger.state();result.update(value)
            key_ready=self.key.is_file() and not self.key.is_symlink() and self.key.stat().st_size<=4096 and not self.key.stat().st_mode&0o077
            result.update(credential_present=bool(key_ready),ready=bool(self.policy.enabled and key_ready and value['remaining']
                          and not value['provider_pause'] and not value['relay_hold']))
        except (ValueError,OSError,TypeError):result['error']='InvalidMeter'
        return result

    def handle(self,authorization,raw):
        number=None
        try:
            if not isinstance(authorization,str) or not hmac.compare_digest(authorization,'Bearer '+self.policy.client_token):raise Held('unauthorized',401)
            if len(raw)>2*1024*1024:raise Held('request_too_large',413)
            body=json.loads(raw)
            if (not isinstance(body,dict) or body.get('model')!=self.policy.model or body.get('stream') not in (None,False)
                    or {'models','route'}&set(body) or not isinstance(body.get('messages'),list) or not body['messages']):raise Held('invalid_request',400)
            if not self.policy.enabled:raise Held('provider_disabled')
            state=self.status()
            if state.get('error'):raise Held('invalid_meter')
            if not state.get('credential_present'):raise Held('credential_unavailable')
            for field in ('max_tokens','max_completion_tokens'):
                if field in body:
                    if type(body[field]) is not int or body[field]<1:raise Held('invalid_output_budget',400)
                    body[field]=min(body[field],self.policy.max_output_tokens)
            if not {'max_tokens','max_completion_tokens'}&set(body):body['max_tokens']=self.policy.max_output_tokens
            number=self.ledger.reserve()  # Commit before any HTTP attempt. Never refund uncertainty.
            try:status,data=self.forward(body)  # One upstream attempt; never repair/rewrite its schema.
            except Exception:
                self.ledger.uncertain(number);raise Held('transport_unknown') from None
            if status in (401,402,403):self.ledger.pause(number,status)
            if status!=200:raise Held('upstream_'+str(status),status if 400<=status<=599 else 502)
            return 200,data
        except Held as error:return error.status,json.dumps({'error':{'code':error.code}}).encode()
        except (ValueError,TypeError):return 400,b'{"error":{"code":"invalid_request"}}'
        except Exception:
            if number:self.ledger.uncertain(number)
            return 503,b'{"error":{"code":"provider_unavailable"}}'

    def forward(self,body):
        with self.key.open() as file:key=file.read(4097).strip()
        if not 20<=len(key)<=4096 or '\n' in key:raise ValueError('credential unavailable')
        connection=http.client.HTTPSConnection('openrouter.ai',timeout=30);deadline=time.monotonic()+120
        try:
            connection.request('POST','/api/v1/chat/completions',json.dumps(body).encode(),
                {'Authorization':'Bearer '+key,'Content-Type':'application/json','X-Title':'Fabriquinha'})
            response=connection.getresponse();chunks=[];size=0
            while True:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('bounded provider response expired')
                sock=connection.sock or getattr(getattr(response.fp,'raw',None),'_sock',None)
                if sock:sock.settimeout(min(30,remaining))
                chunk=response.read1(min(65536,4*1024*1024-size+1))
                if not chunk:break
                size+=len(chunk)
                if size>4*1024*1024:raise RuntimeError('bounded provider response exceeded')
                chunks.append(chunk)
            return response.status,b''.join(chunks)
        finally:connection.close()


def admit(policy,observed,project):
    """Metadata-only preflight. It cannot release a pause, quota or operator grant."""
    if (not isinstance(observed,dict) or policy.project!=project or observed.get('version')!=1
            or observed.get('project')!=project or observed.get('model')!=policy.model
            or observed.get('policy')!=policy.fingerprint() or observed.get('neutral') is not True
            or 'fallback' not in observed or observed['fallback'] is not None or type(observed.get('max_calls')) is not int
            or observed['max_calls']!=policy.max_calls or observed.get('max_output_tokens')!=policy.max_output_tokens
            or observed.get('max_request_bytes')!=2*1024*1024 or type(observed.get('remaining')) is not int
            or type(observed.get('calls')) is not int or observed['calls']<0
            or observed.get('remaining')!=max(0,policy.max_calls-observed['calls'])):raise Held('provider_identity_mismatch')
    if not policy.enabled or observed.get('enabled') is not True:raise Held('provider_disabled')
    pause=observed.get('provider_pause')
    if pause:
        if not isinstance(pause,dict):raise Held('provider_identity_mismatch')
        raise Held('provider_paused',pause['upstream_status'] if pause.get('upstream_status') in (401,402,403) else 503)
    if observed.get('relay_hold'):raise Held('transport_unknown')
    if not observed['remaining']:raise Held('budget_exhausted',429)
    if observed.get('ready') is not True:raise Held('provider_unavailable')
    return dict(model=policy.model,calls=observed['calls'],remaining=observed['remaining'],max_calls=policy.max_calls)


def inspect(policy,endpoint,project):
    """Fixed loopback GET /status; never query the provider or read its key."""
    url=urlsplit(endpoint)
    if (url.scheme!='http' or url.hostname!='127.0.0.1' or not url.port or url.username or url.password
            or url.path not in ('','/') or url.query or url.fragment):raise Held('invalid_relay_endpoint')
    connection=http.client.HTTPConnection('127.0.0.1',url.port,timeout=3)
    try:
        connection.request('GET','/status');response=connection.getresponse();raw=response.read(8193)
        if response.status!=200 or len(raw)>8192:raise Held('provider_status_unavailable')
        return admit(policy,json.loads(raw),project)
    except Held:raise
    except (OSError,ValueError,http.client.HTTPException):raise Held('provider_status_unavailable') from None
    finally:connection.close()


def server(app,host,port):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):super().setup();self.connection.settimeout(15)
        def log_message(self,*args):pass  # No prompts, outputs, keys or authorization in logs.
        def send(self,status,data):
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if self.path!='/status':self.send(404,b'{}');return
            self.send(200,json.dumps(app.status()).encode())
        def do_POST(self):
            if self.path!='/v1/chat/completions':self.send(404,b'{}');return
            try:size=int(self.headers.get('Content-Length','0'))
            except ValueError:self.send(400,b'{}');return
            if not 0<size<=2*1024*1024:self.send(413,b'{}');return
            self.send(*app.handle(self.headers.get('Authorization'),self.rfile.read(size)))
    service=ThreadingHTTPServer((host,port),Handler);service.daemon_threads=False
    return service


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--policy',type=Path,required=True)
    parser.add_argument('--meter',type=Path,required=True);parser.add_argument('--key',type=Path,required=True)
    parser.add_argument('--host',choices=('127.0.0.1','0.0.0.0'),default='127.0.0.1');parser.add_argument('--port',type=int,default=8080)
    args=parser.parse_args();path=args.policy
    if path.is_symlink() or not path.is_file() or path.stat().st_mode&0o077 or path.stat().st_size>4096:raise ValueError('private operator policy required')
    app=Relay(Policy.parse(json.loads(path.read_bytes())),args.meter,args.key)
    with app.ledger.owner():
        service=server(app,args.host,args.port)
        for signum in (signal.SIGTERM,signal.SIGINT):
            signal.signal(signum,lambda *_:threading.Thread(target=service.shutdown,daemon=True).start())
        try:service.serve_forever(poll_interval=0.25)
        finally:service.server_close()


if __name__=='__main__':main()
