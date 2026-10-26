"""Neutral bounded OpenRouter relay. No phase/schema adapters or model fallback.

Policy enablement is local operator configuration, not business approval. The
old calls.json/provider-pause.json formats are retained; no reset/unpause API.
"""
import argparse
from contextlib import contextmanager
from dataclasses import asdict,dataclass
from decimal import Decimal,InvalidOperation
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

OUTPUT_LIMITS=(2048,4096,8192,16384)


def response_usage(reply):
    """Allowlisted provider accounting only; never messages or arbitrary fields."""
    usage=reply.get('usage');usage=usage if isinstance(usage,dict) else {}
    counts={k:v for k,v in usage.items() if k in ('prompt_tokens','completion_tokens','total_tokens')
            and type(v) is int and 0<=v<=10**10}
    for group,names in (('prompt_tokens_details',('cached_tokens','cache_write_tokens')),
                        ('completion_tokens_details',('reasoning_tokens',))):
        details=usage.get(group)
        if isinstance(details,dict):
            counts.update({k:details[k] for k in names if type(details.get(k)) is int and 0<=details[k]<=10**10})
    cost=usage.get('cost');reported=None
    if type(cost) in (int,float,Decimal):
        try:
            value=Decimal(str(cost))
            if value.is_finite() and 0<=value<=10**6 and (value==0 or value.adjusted()>=-32) and len(value.as_tuple().digits)<=64:
                reported='0' if value==0 else format(value,'f')
        except InvalidOperation:pass
    result=dict(usage=counts,reported_cost=reported,cost_currency='USD',cost_status='reported' if reported is not None else 'unknown')
    generation=reply.get('id')
    if isinstance(generation,str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}',generation):result['generation_id']=generation
    return result


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
                or type(value['max_output_tokens']) is not int or value['max_output_tokens'] not in OUTPUT_LIMITS
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
        target=self.root/name
        if not target.parent.resolve().is_relative_to(self.root.resolve()):raise ValueError('meter write must stay inside its owner root')
        write_json(target,value)
        # Nested audit archives must be durable BEFORE removing a live marker.
        directory=target.parent
        while True:
            descriptor=os.open(directory,os.O_RDONLY)
            try:os.fsync(descriptor)
            finally:os.close(descriptor)
            if directory==self.root:break
            directory=directory.parent

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

    def usage(self,project):
        """Recorded calls only. Gaps and absent billing stay visible, never estimated."""
        through=self.state()['calls'];groups={};valid=0;invalid=0
        def empty():return dict(attempts=0,reported_cost_calls=0,unknown_cost_calls=0,known_cost_usd='0',tokens={},token_reporting_calls={},outcomes={})
        total=empty()
        for path in sorted((self.root/'attempts').glob('*.json')):
            if not re.fullmatch(r'[1-9][0-9]*',path.stem) or int(path.stem)>through:continue
            try:
                value=self.read('attempts/'+path.name)
                if not isinstance(value,dict) or value.get('call_number')!=int(path.stem) or not re.fullmatch('[a-f0-9]{64}',str(value.get('project'))):raise ValueError('scope')
            except (ValueError,OSError,TypeError):invalid+=1;continue
            valid+=1
            if value['project']!=project:continue
            activity=value.get('activity')
            if not isinstance(activity,str) or not re.fullmatch('[a-f0-9]{64}',activity):activity='unattributed'
            if activity not in groups and len(groups)>=128:activity='overflow'
            group=groups.setdefault(activity,empty())
            for bucket in (total,group):
                bucket['attempts']+=1
                category=value.get('category');category=category if category in ('reserved','returned','transport_unknown') else 'other'
                bucket['outcomes'][category]=bucket['outcomes'].get(category,0)+1
                try:
                    raw=value['reported_cost']
                    if not isinstance(raw,str) or not re.fullmatch(r'[0-9]{1,7}(?:\.[0-9]{1,96})?',raw):raise ValueError('unknown cost')
                    cost=Decimal(raw)
                    if value.get('cost_status')!='reported' or not cost.is_finite() or not 0<=cost<=10**6:raise ValueError('unknown cost')
                except (KeyError,ValueError,TypeError,InvalidOperation):bucket['unknown_cost_calls']+=1
                else:
                    bucket['known_cost_usd']=format(Decimal(bucket['known_cost_usd'])+cost,'f');bucket['reported_cost_calls']+=1
                usage=value.get('usage');usage=usage if isinstance(usage,dict) else {}
                for key,count in usage.items():
                    if key in ('prompt_tokens','completion_tokens','total_tokens','cached_tokens','cache_write_tokens','reasoning_tokens') and type(count) is int and count>=0:
                        bucket['tokens'][key]=bucket['tokens'].get(key,0)+count
                        bucket['token_reporting_calls'][key]=bucket['token_reporting_calls'].get(key,0)+1
        for bucket in (total,*groups.values()):
            bucket['recorded_cost_complete']=bucket['unknown_cost_calls']==0
            bucket['recorded_total_cost_usd']=bucket['known_cost_usd'] if bucket['recorded_cost_complete'] else None
        return dict(project=project,through_call=through,global_unrecorded_calls=max(0,through-valid),invalid_records=invalid,
            scope='recorded_attempts_only',currency='USD',total=total,activities=groups)

    def pause(self,number,status):
        with self.lock('counter'):
            if type(number) is not int or not 1<=number<=self.state()['calls'] or status not in (401,402,403):raise ValueError('actual failed attempt required')
            self.save('provider-pause.json',dict(category='upstream_payment_required' if status==402 else 'upstream_access_denied',
                upstream_status=status,call_number=number))

    def uncertain(self,number):
        with self.lock('counter'):self.save('relay-hold.json',dict(category='transport_unknown',call_number=number))

    def archive_uncertain(self,expected_calls,authorization):
        """LOCAL operator API only, after explicit human authorization; no HTTP tool.

        The possibly billed call stays consumed. An archive survives interrupted
        acknowledgement; replay never clears a different/new hold.
        """
        if (type(expected_calls) is not int or expected_calls<1 or not isinstance(authorization,str)
                or not re.fullmatch('[a-f0-9]{32}',authorization)):raise ValueError('exact operator authorization required')
        folder=self.root/'hold-archives'/authorization;receipt=folder/'receipt.json'
        with self.owner(),self.lock('counter'):
            if receipt.exists():
                prior=self.read(str(receipt.relative_to(self.root)))
                if prior.get('calls_preserved')!=expected_calls:raise ValueError('authorization reused for another counter')
                return prior
            state=self.state();archive=folder/'relay-hold.json'
            if state['calls']!=expected_calls or state['provider_pause']:
                raise ValueError('counter or financial pause changed; preserve all markers')
            expected=dict(category='transport_unknown',call_number=expected_calls)
            if archive.exists():
                if self.read(str(archive.relative_to(self.root)))!=expected:raise ValueError('archive identity drift')
            else:
                if state['relay_hold']!=expected:raise ValueError('exact current uncertain call required')
                self.save(str(archive.relative_to(self.root)),expected)
            if state['relay_hold'] is not None:
                if state['relay_hold']!=expected:raise ValueError('hold changed; never remove another occurrence')
                (self.root/'relay-hold.json').unlink()
                fd=os.open(self.root,os.O_RDONLY)
                try:os.fsync(fd)
                finally:os.close(fd)
            result=dict(authorization=authorization,calls_preserved=expected_calls,archived=expected,
                model_calls=0,retry_executed=False,counter_reset=False)
            self.save(str(receipt.relative_to(self.root)),result);return result


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

    def handle(self,authorization,raw,activity=None):
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
                    # Do not pretend the SDK's retry boost was honored while
                    # silently resending the same effective generation budget.
                    if body[field]>self.policy.max_output_tokens:raise Held('output_budget_exceeds_policy',422)
            if not {'max_tokens','max_completion_tokens'}&set(body):body['max_tokens']=self.policy.max_output_tokens
            number=self.ledger.reserve()  # Commit before any HTTP attempt. Never refund uncertainty.
            evidence=dict(project=self.policy.project,model=self.policy.model,request_hash=digest(body),
                output_cap=self.policy.max_output_tokens,requested_output=body.get('max_tokens',body.get('max_completion_tokens')),
                call_number=number,category='reserved')
            if isinstance(activity,str) and re.fullmatch('[a-f0-9]{64}',activity):evidence['activity']=activity
            path=f'attempts/{number}.json';self.ledger.save(path,evidence)
            try:status,data=self.forward(body)  # One upstream attempt; never repair/rewrite its schema.
            except Exception as error:
                self.ledger.save(path,{**evidence,'category':'transport_unknown','error_type':type(error).__name__})
                self.ledger.uncertain(number);raise Held('transport_unknown') from None
            metadata={}
            try:
                reply=json.loads(data,parse_float=Decimal)
                reasons=[item.get('finish_reason') for item in reply.get('choices',[])]
                metadata['finish_reasons']=[r if r in ('stop','length','tool_calls','content_filter',None) else 'other' for r in reasons[:16]]
                metadata.update(response_usage(reply))
            except (ValueError,TypeError,AttributeError):metadata['response_metadata_unavailable']=True
            self.ledger.save(path,{**evidence,'category':'returned','upstream_status':status,**metadata})
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
        connection=http.client.HTTPSConnection('openrouter.ai',timeout=120);deadline=time.monotonic()+120
        try:
            connection.request('POST','/api/v1/chat/completions',json.dumps(body).encode(),
                {'Authorization':'Bearer '+key,'Content-Type':'application/json','X-Title':'Fabriquinha'})
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('bounded provider headers expired')
            if connection.sock:connection.sock.settimeout(remaining)
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


def inspect_usage(policy,endpoint):
    """Authenticated local accounting only; no provider request or policy change."""
    url=urlsplit(endpoint)
    if (url.scheme!='http' or url.hostname!='127.0.0.1' or not url.port or url.username or url.password
            or url.path not in ('','/') or url.query or url.fragment):raise ValueError('fixed local usage endpoint required')
    connection=http.client.HTTPConnection('127.0.0.1',url.port,timeout=10)
    try:
        connection.request('GET','/usage',headers={'Authorization':'Bearer '+policy.client_token})
        response=connection.getresponse();raw=response.read(256*1024+1)
        if response.status!=200 or len(raw)>256*1024:raise ValueError('bounded authenticated usage response required')
        value=json.loads(raw)
        if value.get('project')!=policy.project or value.get('scope')!='recorded_attempts_only':raise ValueError('foreign accounting scope')
        return value
    finally:connection.close()


def server(app,host,port):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):super().setup();self.connection.settimeout(15)
        def log_message(self,*args):pass  # No prompts, outputs, keys or authorization in logs.
        def send(self,status,data):
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if self.path=='/usage':
                if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+app.policy.client_token):
                    self.send(401,b'{}');return
                self.send(200,json.dumps(app.ledger.usage(app.policy.project)).encode());return
            if self.path!='/status':self.send(404,b'{}');return
            self.send(200,json.dumps(app.status()).encode())
        def do_POST(self):
            if self.path!='/v1/chat/completions':self.send(404,b'{}');return
            try:size=int(self.headers.get('Content-Length','0'))
            except ValueError:self.send(400,b'{}');return
            if not 0<size<=2*1024*1024:self.send(413,b'{}');return
            self.send(*app.handle(self.headers.get('Authorization'),self.rfile.read(size),self.headers.get('X-Fabriquinha-Activity')))
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
