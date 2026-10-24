"""Fixed Linux/HTTP/file/lock canary, never real provider or native authority."""
import contextlib
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
from types import ModuleType
import urllib.request
from unittest.mock import patch
import quality_provider_resolution as contract

assert os.getuid()==10000 and not Path('/var/run/docker.sock').exists() and not Path('/secret/openrouter.key').exists()
mounts=Path('/proc/self/mountinfo').read_text().splitlines()
assert any(line.split()[4]=='/opt/data' and line.split(' - ',1)[1].split()[0]=='tmpfs' for line in mounts)
root=Path('/tmp/payment-fixture');root.mkdir(mode=0o700)
http=[];data={'credits':dict(total_credits=10.,total_usage=2.),'key':dict(limit=5.,limit_remaining=3.)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        name=self.path.removeprefix('/')
        assert name in ('credits','key')
        http.append(name);self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
        self.wfile.write(json.dumps(dict(data=data[name])).encode())


server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
original_open=urllib.request.urlopen;original_read=Path.read_text


def official(request,timeout):
    assert request.full_url in ('https://openrouter.ai/api/v1/credits','https://openrouter.ai/api/v1/key')
    assert request.get_header('Authorization')=='Bearer fixture-not-a-real-key'
    return original_open('http://127.0.0.1:'+str(server.server_port)+'/'+request.full_url.rsplit('/',1)[1],timeout=timeout)


def read_text(path,*args,**kwargs):
    return 'fixture-not-a-real-key' if str(path)=='/secret/openrouter.key' else original_read(path,*args,**kwargs)


def case(number):
    directory=root/str(number);directory.mkdir(mode=0o700)
    counter=directory/'calls.json';counter.write_text('{"calls": 17}')
    pause=directory/'provider-pause.json'
    pause.write_text(json.dumps(dict(category='upstream_payment_required',upstream_status=402,call_number=17)))
    m=ModuleType('model_proxy');m.COUNTER_PATH=str(counter);m.MAX_CALLS=10000;m.__file__='/qualified_proxy_source.py'
    m.load_calls=lambda:json.loads(counter.read_bytes())['calls']
    m.provider_pause=lambda:json.loads(pause.read_bytes()) if pause.exists() else None
    operation='60000000-0000-4000-8000-'+str(number).zfill(12)
    request='70000000-0000-4000-8000-'+str(number).zfill(12)
    payload=dict(namespace='delivery-kit-fixture',maintenance_operation=operation,request_id=request,
        proxy_container='1'*64,proxy_image='sha256:'+'2'*64,operator_confirmed=True,
        event=dict(event='model_proxy_request',status=402,category='upstream_response',call_number=17,
            route='/api/v1/chat/completions',execution_id=request,started_at=time.time()-5,
            duration_seconds=1.,response_deadline_seconds=120))
    def run(mode,**changes):
        namespace={};output=io.StringIO();completed=False
        try:
            with patch.dict(sys.modules,{'model_proxy':m}),patch.object(sys,'stdin',io.StringIO(json.dumps({**payload,**changes}))),\
                    patch.object(sys,'argv',['fixed-canary']),patch.object(Path,'read_text',read_text),\
                    patch.object(urllib.request,'urlopen',official),contextlib.redirect_stdout(output):
                try:
                    exec(compile(contract.program(mode),'<fixed-payment-runtime>','exec'),namespace)
                    completed=True
                except SystemExit as error:assert error.code==0
        finally:
            if not completed and 'lock' in namespace:
                try:os.close(namespace['lock'])
                except OSError:pass
        assert counter.read_text()=='{"calls": 17}'
        value=json.loads(output.getvalue())
        if 'resolution' in value:
            contract.validate(value,payload['namespace'],operation,request,
                proxy_source=hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest())
        return value
    return directory,pause,run


try:
    _,pause,run=case(1)
    try:run('resolve',operator_confirmed=False);raise RuntimeError('confirmation was not required')
    except AssertionError:pass
    assert pause.exists() and not http
    data['credits']=dict(total_credits=2.,total_usage=2.)
    _,pause,run=case(2)
    try:run('resolve');raise RuntimeError('zero credit was not rejected')
    except ValueError:pass
    assert pause.exists() and len(http)==2
    data['credits']=dict(total_credits=10.,total_usage=2.)
    _,pause,run=case(3);proof=run('resolve');assert not pause.exists() and len(http)==4
    assert run('observe')==proof and len(http)==4
    data['key']=dict(limit=None,limit_remaining=None)
    _,pause,run=case(4);run('resolve');assert not pause.exists() and len(http)==6
    _,pause,run=case(5);unlink=Path.unlink
    def interrupted(path,*args,**kwargs):
        if path==pause:raise OSError('fixed interruption after receipt')
        return unlink(path,*args,**kwargs)
    with patch.object(Path,'unlink',interrupted):
        try:run('resolve');raise RuntimeError('fixed interruption not observed')
        except OSError:pass
    assert pause.exists() and len(http)==8
    assert run('observe')['stage']=='resolution_incomplete' and pause.exists()
    run('finish');assert not pause.exists() and len(http)==8
    directory,pause,run=case(6);lock=directory/'provider-resolution-60000000-0000-4000-8000-000000000006.lock'
    fd=os.open(lock,os.O_CREAT|os.O_RDWR,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert run('observe')['stage']=='in_progress' and pause.exists() and len(http)==8
    finally:os.close(fd)
finally:server.shutdown();server.server_close()

sources={name:hashlib.sha256(Path('/'+path).read_bytes()).hexdigest() for name,path in {
    'contract':'quality_provider_resolution.py','resolver':'provider_pause_resolution.py',
    'payment_recovery':'quality_review_payment_recovery.py',
    'lineage':'quality_review_completion_recovery.py','proxy':'qualified_proxy_source.py'}.items()}
print(json.dumps(dict(operation='fixed_payment_resolution_runtime_canary_v1',status='passed',
    credit_source='fixed_loopback_not_provider',fixture_http_calls=8,model_calls=0,real_provider_calls=0,
    confirmation_required=True,counter_preserved=True,zero_credit_rejected=True,unlimited_key_supported=True,
    readback_no_repeat=True,partial_finish_no_repeat=True,live_lock_observed=True,
    credential_mounts=False,docker_socket=False,image_data_tmpfs=True,
    delivery_approval=False,tests_approved=False,sources=sources),sort_keys=True))
