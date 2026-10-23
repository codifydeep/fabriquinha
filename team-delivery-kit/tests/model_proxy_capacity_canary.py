"""Real local HTTP transport in a credential-free, network-none proxy image.

The upstream is a fixed in-process fixture, never OpenRouter. Neither fixture
forwarding nor HTTP acceptance is review/test/delivery approval.
"""
import hashlib
import http.client
import json
import os
from pathlib import Path
import threading

assert os.getuid()==10000
assert not Path('/var/run/docker.sock').exists()
assert not Path('/secret/openrouter.key').exists()
mounts=Path('/proc/self/mountinfo').read_text().splitlines()
assert any(line.split()[4]=='/opt/data' and line.split(' - ',1)[1].split()[0]=='tmpfs' for line in mounts)
counter=Path('/tmp/capacity-calls.json');counter.write_text('{"calls":0}');counter.chmod(0o600)
os.environ.update(MODEL_PROXY_COUNTER_PATH=str(counter),MODEL_PROXY_MAX_CALLS='2',
    MODEL_PROXY_MAX_REQUEST_BYTES='2097152')
import model_proxy as proxy
assert proxy.MAX_BODY==2097152 and proxy.MAX_CALLS==2
forwarded=[]
def fixed_forward(body):
    assert body['model']==proxy.MODEL
    forwarded.append(len(json.dumps(body).encode()))
    return 200,b'{"choices":[{"message":{"role":"assistant","content":"fixture"},"finish_reason":"stop"}]}','application/json'
proxy.forward=fixed_forward
server=proxy.ThreadingHTTPServer(('127.0.0.1',0),proxy.Handler)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
def post(raw,declared=None):
    conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
    try:
        conn.request('POST','/api/v1/chat/completions',body=raw,headers={
            'Authorization':proxy.PLACEHOLDER,'Content-Length':str(len(raw) if declared is None else declared)})
        response=conn.getresponse();status=response.status;response.read();return status
    finally:conn.close()
try:
    sizes=[]
    for count in (600000,proxy.MAX_BODY-512):
        raw=json.dumps(dict(model=proxy.MODEL,messages=[dict(role='user',content='x'*count)])).encode()
        assert 524288<len(raw)<=proxy.MAX_BODY
        assert post(raw)==200;sizes.append(len(raw))
    assert len(forwarded)==2 and proxy.CALLS==2 and json.loads(counter.read_text())=={'calls':2}
    assert post(b'',proxy.MAX_BODY+1)==400
    raw=json.dumps(dict(model=proxy.MODEL,messages=[dict(role='user',content='small')])).encode()
    assert post(raw)==400  # Original two-call fixture ceiling still holds.
    assert len(forwarded)==2 and proxy.CALLS==2 and proxy.MAX_CALLS==2
    assert json.loads(counter.read_text())=={'calls':2}
    conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
    try:
        conn.request('GET','/runtime-status');response=conn.getresponse();runtime=json.loads(response.read())
        assert response.status==200 and runtime['max_request_bytes']==proxy.MAX_BODY
    finally:conn.close()
finally:server.shutdown();server.server_close();thread.join(timeout=5)
assert not thread.is_alive()
print(json.dumps(dict(operation='real_http_proxy_capacity_canary_v1',status='passed',
    source_sha256=hashlib.sha256(Path(proxy.__file__).read_bytes()).hexdigest(),
    max_request_bytes=proxy.MAX_BODY,accepted_request_bytes=sizes,fixed_forwards=2,
    oversized_rejected=True,call_ceiling_preserved=True,counter_preserved=True,
    fixture_max_calls=2,fixture_calls=2,model_calls=0,credentials_mounted=False,
    docker_socket=False,network='none',data_tmpfs=True,tests_approved=False,delivery_approval=False)))
