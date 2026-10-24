"""Evidence-bound operator payment resolution, never a model or approval grant.

Only the proxy's fixed operator program may query the official credit/key APIs.
The host authenticates its private receipt and logs; controller validation still
binds the native failure, retired worker and exact readonly successor separately.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import time
import uuid
import provider_pause_resolution as legacy

EVENT_KEYS={'event','status','category','call_number','route','execution_id','started_at',
    'duration_seconds','response_deadline_seconds'}
FIELDS={'operation','namespace','maintenance_operation','request_id','proxy_container','proxy_image',
    'resolver_sha256','proxy_source_sha256','event','resolution','counter','max_calls',
    'pause_absent','operator_confirmed','model_calls','delivery_approval'}


def require(ok):
    if not ok:raise ValueError('exact operator-confirmed unchanged-counter payment resolution required')


def canonical(value):
    require(isinstance(value,str) and len(value)==36 and str(uuid.UUID(value))==value)
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def source_sha256():
    return digest(dict(contract=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        resolver=hashlib.sha256(Path(legacy.__file__).read_bytes()).hexdigest()))


def event(value,request):
    canonical(request)
    require(isinstance(value,dict) and set(value)==EVENT_KEYS and value['event']=='model_proxy_request'
        and type(value['status']) is int and value['status']==402 and value['category']=='upstream_response'
        and type(value['call_number']) is int and value['call_number']>0 and value['execution_id']==request
        and value['route']=='/api/v1/chat/completions' and type(value['response_deadline_seconds']) is int
        and value['response_deadline_seconds']==120
        and type(value['started_at']) in (int,float) and math.isfinite(value['started_at']) and value['started_at']>0
        and type(value['duration_seconds']) in (int,float) and math.isfinite(value['duration_seconds'])
        and 0<=value['duration_seconds']<=120)
    return value


def validate(value,namespace,operation,request,*,proxy_source,now=None):
    canonical(operation);canonical(request)
    require(isinstance(namespace,str) and re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',namespace)
        and isinstance(value,dict) and set(value)==FIELDS
        and value['operation']=='observed_review_payment_resolution_v1' and value['namespace']==namespace
        and value['maintenance_operation']==operation and value['request_id']==request
        and value['pause_absent'] is True and value['operator_confirmed'] is True
        and type(value['model_calls']) is int and value['model_calls']==0 and value['delivery_approval'] is False
        and value['resolver_sha256']==source_sha256() and value['proxy_source_sha256']==proxy_source
        and re.fullmatch('[a-f0-9]{64}',str(proxy_source))
        and re.fullmatch('[a-f0-9]{64}',str(value['proxy_container']))
        and re.fullmatch('sha256:[a-f0-9]{64}',str(value['proxy_image'])))
    upstream=event(value['event'],request);counter=value['counter'];resolution=value['resolution']
    require(isinstance(counter,dict) and set(counter)=={'calls','sha256'}
        and type(counter['calls']) is int and counter['calls']==upstream['call_number']
        and re.fullmatch('[a-f0-9]{64}',str(counter['sha256']))
        and type(value['max_calls']) is int and value['max_calls']>counter['calls']
        and isinstance(resolution,dict) and set(resolution)=={'operation','operation_id','pause','calls_before',
            'calls_after','account_balance_positive','key_remaining_positive','delivery_approval','resolved_at'}
        and resolution['operation']=='operator_provider_access_resolution_v1'
        and resolution['operation_id']==operation and resolution['delivery_approval'] is False
        and resolution['account_balance_positive'] is True and resolution['key_remaining_positive'] is True
        and all(type(resolution[k]) is int and resolution[k]==counter['calls'] for k in ('calls_before','calls_after'))
        and resolution['pause']==dict(category='upstream_payment_required',upstream_status=402,call_number=counter['calls'])
        and type(resolution['pause'].get('upstream_status')) is int
        and type(resolution['pause'].get('call_number')) is int)
    now=time.time() if now is None else now;resolved=resolution['resolved_at']
    require(type(now) in (int,float) and math.isfinite(now)
        and type(resolved) in (int,float) and math.isfinite(resolved)
        and upstream['started_at']+upstream['duration_seconds']<=resolved<=now and now-resolved<=900)
    # Operation names/timestamps cannot manufacture another changed condition.
    return digest(dict(operation='review_payment_condition_v1',namespace=namespace,request_id=request,
        failed_call=counter['calls'],proxy_image=value['proxy_image'],resolver_sha256=value['resolver_sha256'],
        proxy_source_sha256=proxy_source))


RUNTIME=r'''
import contextlib,fcntl,hashlib,io,json,os,re,stat,sys,time,uuid
from pathlib import Path
import model_proxy as m
p=json.loads(sys.stdin.read(16385))
assert set(p)=={'namespace','maintenance_operation','request_id','proxy_container','proxy_image','event','operator_confirmed'}
assert p['operator_confirmed'] is True and mode in ('resolve','observe','finish')
assert re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',p['namespace'])
assert all(str(uuid.UUID(p[k]))==p[k] for k in ('maintenance_operation','request_id'))
calls=m.load_calls();counter=Path(m.COUNTER_PATH);before=counter.read_bytes()
assert calls==p['event']['call_number'] and m.MAX_CALLS>calls
operation=p['maintenance_operation'];receipt=counter.with_name('provider-resolution-'+operation+'.json')
lockpath=counter.with_name('provider-resolution-'+operation+'.lock')
def pending(stage):
 print(json.dumps(dict(stage=stage,model_calls=0,delivery_approval=False)));sys.exit(0)
if mode=='observe' and not lockpath.exists():pending('not_observed')
if mode=='finish' and not lockpath.exists():pending('not_observed')
flags=(os.O_RDONLY if mode=='observe' else os.O_RDWR|(os.O_CREAT if mode=='resolve' else 0))|os.O_NOFOLLOW
lock=os.open(lockpath,flags,0o600);info=os.fstat(lock)
assert stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.getuid() and not info.st_mode&0o077
try:fcntl.flock(lock,(fcntl.LOCK_SH if mode=='observe' else fcntl.LOCK_EX)|fcntl.LOCK_NB)
except BlockingIOError:pending('in_progress')
if not receipt.exists():
 if mode!='resolve':pending('not_observed')
 assert m.provider_pause()==dict(category='upstream_payment_required',upstream_status=402,call_number=calls)
 sys.argv=['provider_pause_resolution.py',operation]
 with contextlib.redirect_stdout(io.StringIO()):exec(legacy_program,{'__name__':'fixed_operator_resolution'})
assert not receipt.is_symlink() and receipt.stat().st_size<=4096
resolution=json.loads(receipt.read_bytes())
if m.provider_pause() is not None:
 if mode=='observe':pending('resolution_incomplete')
 assert mode=='finish'
 assert resolution['operation']=='operator_provider_access_resolution_v1' and resolution['operation_id']==operation
 assert resolution['calls_before']==resolution['calls_after']==calls and resolution['delivery_approval'] is False
 assert resolution['account_balance_positive'] is True and resolution['key_remaining_positive'] is True
 assert type(resolution['resolved_at']) in (int,float) and 0<=time.time()-resolution['resolved_at']<=900
 assert m.provider_pause()==resolution['pause']==dict(category='upstream_payment_required',upstream_status=402,call_number=calls)
 assert m.load_calls()==calls and counter.read_bytes()==before
 counter.with_name('provider-pause.json').unlink()
 directory=os.open(counter.parent,os.O_RDONLY);os.fsync(directory);os.close(directory)
assert m.provider_pause() is None and m.load_calls()==calls and counter.read_bytes()==before
proof=dict(operation='observed_review_payment_resolution_v1',**p,
 resolver_sha256=resolver_sha256,proxy_source_sha256=hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest(),
 resolution=resolution,counter=dict(calls=calls,sha256=hashlib.sha256(before).hexdigest()),
 max_calls=m.MAX_CALLS,pause_absent=True,model_calls=0,delivery_approval=False)
print(json.dumps(proof,sort_keys=True))
os.close(lock)
'''


def program(mode):
    require(mode in ('resolve','observe','finish'))
    return ('mode='+repr(mode)+'\nlegacy_program='+repr(legacy.PROGRAM)+
        '\nresolver_sha256='+repr(source_sha256())+'\n'+RUNTIME)
