"""Offline ACP integration with fixed loopback responses, never model authorship."""
import inspect
import json
import hashlib
from pathlib import Path
import subprocess
from evalctl import PROJECT,PRIVATE
from release_eval import save_receipt
from probe_acp_artifact import seeded_tool_receipts


def fixture_server(model):
    import json
    import time
    import threading
    import hashlib
    from pathlib import Path
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    root=Path('/workspace');(root/'tests').mkdir()
    initial="import unittest\nQUERY = 'calls.length'\nclass Probe(unittest.TestCase):\n    def test_fixture(self): self.assertEqual(QUERY, 'calls.length')\n"
    old="QUERY = 'calls.length'"
    valid='QUERY = \'calls.filter(c => c.url === "/service-mode").length\''
    invalid="QUERY = 'calls.filter(c => c.url === '/service-mode').length'"
    target=root/'tests/test_new.py';target.write_text(initial)
    (root/'app.py').write_text('VALUE = 0\n');(root/'tests/test_old.py').write_text('baseline preserved\n')
    for p in (root/'app.py',root/'tests/test_old.py'):p.chmod(0o444)
    target.chmod(0o666);(root/'tests').chmod(0o555);root.chmod(0o555)
    state=dict(requests=0,rejected_patch_preserved_bytes=False,exact_quotes_preserved=False)
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,body,kind='application/json'):
            self.send_response(200);self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            if self.path=='/probe-state':self.send(json.dumps(state).encode())
            elif self.path.endswith('/models'):self.send(json.dumps(dict(data=[dict(id=model)])).encode())
            else:self.send_error(404)
        def do_POST(self):
            if not self.path.endswith('/chat/completions'):self.send_error(404);return
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=1024*1024:self.send_error(400);return
            body=json.loads(self.rfile.read(size));state['requests']+=1;step=state['requests']
            if step>5:self.send_error(409);return
            if step==4:state['rejected_patch_preserved_bytes']=target.read_text()==initial
            if step==5:state['exact_quotes_preserved']=target.read_text()==initial.replace(old,valid)
            name,args=('read_file',dict(path='/workspace/app.py',offset=1,limit=200)) if step==1 else (
                ('read_file',dict(path=str(target),offset=1,limit=200)) if step==2 else
                ('patch',dict(path=str(target),old_string=old,new_string=invalid if step==3 else valid)))
            message=dict(role='assistant',content='Fixed fixture complete.') if step==5 else dict(role='assistant',
                tool_calls=[dict(id='fixed-call-'+str(step),type='function',
                    function=dict(name=name,arguments=json.dumps(args)))])
            finish='stop' if step==5 else 'tool_calls'
            if body.get('stream'):
                delta=dict(content=message['content']) if step==5 else dict(tool_calls=[
                    dict(index=0,**message['tool_calls'][0])])
                record=dict(id='fixed-response-'+str(step),object='chat.completion.chunk',created=0,model=model,
                    choices=[dict(index=0,delta=delta,finish_reason=finish)])
                self.send(('data: '+json.dumps(record)+'\n\ndata: [DONE]\n\n').encode(),'text/event-stream')
            else:
                self.send(json.dumps(dict(id='fixed-response-'+str(step),object='chat.completion',created=0,
                    model=model,choices=[dict(index=0,message=message,finish_reason=finish)])).encode())
    server=ThreadingHTTPServer(('127.0.0.1',18088),Fixture)
    timer=threading.Timer(120,server.shutdown);timer.daemon=True;timer.start()
    print('fixture-ready',flush=True)
    try:server.serve_forever()
    finally:timer.cancel();server.server_close()


def offline_bootstrap():
    import os
    from pathlib import Path
    from worker_model_config import EXPECTED
    from model_policy import PROXY_BASE_URL
    home=Path('/tmp/hermes');home.mkdir(mode=0o700,exist_ok=True)
    target=home/'config.yaml'
    with target.open('x') as stream:
        stream.write(EXPECTED.replace(PROXY_BASE_URL,'http://127.0.0.1:18088/api/v1'))
    target.chmod(0o600)
    os.execvp('hermes',['hermes','acp'])


def valid_inspection(receipts,record,writer_sha):
    return (receipts==dict(actual_patch_calls=2,actual_read_calls=2,paired_patch_results=1,
            tool_protocol_valid=True,syntax_rejected_patch_calls=1)
        and record.get('requests')==5 and record.get('uid')==10000 and record.get('writer_sha256')==writer_sha
        and all(record.get(k) is True for k in ('rejected_patch_preserved_bytes','exact_quotes_preserved',
            'baseline_unchanged','credentials_absent')))


def remote_probe(setup,bootstrap,writer_sha):
    import broker as b
    from model_policy import MODEL
    from acp_transport import Transport,failure_diagnostics
    import json,uuid,time,struct,base64
    identifier=str(uuid.uuid4());name=b.PREFIX+'-fixed-acp-patch-job-'+identifier
    owner=b.PREFIX+'-fixed-acp-patch-probe-v1'
    if b.PREFIX!='delivery-kit-port2':raise ValueError('isolated project required')
    result=dict(schema='fixed-acp-patch-probe-v1',status='failed',execution_id=identifier,
        worker_image=b.IMAGE,model_calls=0,model_authorship=False,delivery_approval=False,product_retry=False)
    private={};transport=None;created=False
    try:
        b.docker('POST','/containers/create?name='+name,dict(Image=b.IMAGE,User='0:0',
            Entrypoint=['python'],Cmd=['-c',setup+'\nfixture_server('+repr(MODEL)+')'],WorkingDir='/tmp',
            Labels={'delivery-kit.owner':owner,'delivery-kit.request':identifier},
            HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
                Memory=805306368,NanoCpus=1000000000,PidsLimit=96,
                Tmpfs={'/tmp':'rw,nosuid,nodev,size=64m,mode=1777','/workspace':'rw,nosuid,nodev,size=1m,mode=0777'})))
        created=True;b.docker('POST','/containers/'+name+'/start')
        for _ in range(30):
            if b.docker_stdout(name).strip()=='fixture-ready':break
            time.sleep(.2)
        else:raise ValueError('fixture unavailable')
        intercepted=False
        def offline_docker(method,path,payload=None):
            nonlocal intercepted
            if method=='POST' and path=='/containers/'+name+'/exec' and payload.get('Cmd')==['python','/worker_model_config.py']:
                if intercepted or payload.get('User')!='10000:10000':raise ValueError('one fixed bootstrap only')
                intercepted=True;payload=dict(payload,Cmd=['python','-c',bootstrap+'\noffline_bootstrap()'])
                payload['Env']=[('OPENROUTER_BASE_URL=http://127.0.0.1:18088/api/v1' if v.startswith('OPENROUTER_BASE_URL=')
                    else v) for v in payload['Env']]
                payload['Env'].append('PYTHONPATH=/:/opt/hermes')
            return b.docker(method,path,payload)
        transport=Transport(offline_docker,name,mode='implementation',editable_paths=['/workspace/tests/test_new.py'])
        def exchange(i,method,params):
            response=transport.exchange(dict(jsonrpc='2.0',id=i,method=method,params=params))
            private[str(i)]=response
            if response.get('error'):raise ValueError('offline ACP error')
            return response
        exchange(1,'initialize',{})
        session=exchange(2,'session/new',{'model':MODEL})['result']['sessionId']
        response=exchange(3,'session/prompt',dict(sessionId=session,prompt=[dict(type='text',text=
            'Offline fixed-response qualification. Read app.py and tests/test_new.py; '
            'patch only tests/test_new.py. If syntax is rejected, preserve the file and correct the quoting. '
            'Do not execute commands or modify baseline files. This is not a delivery or Red approval.')]))
        receipts=seeded_tool_receipts(response.get('_broker_notifications',[]),allow_syntax_recovery=True)
        result.update(receipts)
        program="""import json,urllib.request,os,hashlib
from pathlib import Path
state=json.load(urllib.request.urlopen('http://127.0.0.1:18088/probe-state',timeout=3))
state.update(uid=os.getuid(),baseline_unchanged=Path('/workspace/app.py').read_text()=='VALUE = 0\\n' and Path('/workspace/tests/test_old.py').read_text()=='baseline preserved\\n',writer_sha256=hashlib.sha256(Path('/fenced_file_write.py').read_bytes()).hexdigest(),credentials_absent=not any(Path(p).exists() for p in ('/var/run/docker.sock','/broker-state/token','/secret/openrouter.key','/run/secrets/openrouter_api_key')))
print(json.dumps(state))
"""
        execution=b.docker('POST','/containers/'+name+'/exec',dict(AttachStdout=True,AttachStderr=False,
            User='10000:10000',Cmd=['python','-c',program]))['Id']
        conn=b.DockerConnection('localhost',timeout=10)
        try:
            conn.request('POST','/v1.45/exec/'+execution+'/start',json.dumps(dict(Detach=False,Tty=False)),
                {'Content-Type':'application/json'});reply=conn.getresponse();data=reply.read(8193)
            if reply.status!=200 or len(data)>8192:raise ValueError('invalid bounded inspection')
            output=b'';offset=0
            while offset<len(data):
                size=struct.unpack('>I',data[offset+4:offset+8])[0]
                if data[offset]!=1 or offset+8+size>len(data):raise ValueError('invalid Docker frame')
                output+=data[offset+8:offset+8+size];offset+=8+size
            record=json.loads(output);result['inspection']=record
        finally:conn.close()
        if valid_inspection(receipts,record,writer_sha):result['status']='passed'
    except Exception as error:
        result['failure_category']=type(error).__name__
        if transport:
            result['transport_diagnostics']=failure_diagnostics(transport.stderr_tail)
            private['stderr_base64']=base64.b64encode(transport.stderr_tail).decode()
    finally:
        if transport:transport.close()
        if created:
            container=b.docker('GET','/containers/'+name+'/json');labels=container['Config'].get('Labels',{})
            if labels.get('delivery-kit.owner')!=owner or labels.get('delivery-kit.request')!=identifier:raise ValueError('ownership mismatch')
            b.docker('POST','/containers/'+container['Id']+'/stop?t=1')
            evidence=b.STATE/'synthetic-probe-evidence';evidence.mkdir(mode=0o700,exist_ok=True)
            if evidence.is_symlink():raise ValueError('unsafe evidence')
            path=evidence/(identifier+'.json')
            with path.open('x') as stream:json.dump(dict(result=result,private=private),stream,sort_keys=True)
            path.chmod(0o600)
            final=b.docker('GET','/containers/'+container['Id']+'/json');labels=final['Config'].get('Labels',{})
            if (final['Id']!=container['Id'] or final['State']['Running'] or labels.get('delivery-kit.owner')!=owner
                    or labels.get('delivery-kit.request')!=identifier):raise ValueError('retirement uncertain')
            b.docker('DELETE','/containers/'+container['Id']+'?force=false');result['fixture_removed']=True
    return result


def main():
    if PROJECT!='delivery-kit-port2':raise ValueError('isolated project required')
    writer=hashlib.sha256((Path(__file__).parent/'broker/fenced_file_write.py').read_bytes()).hexdigest()
    source=inspect.getsource(seeded_tool_receipts)+'\n'+inspect.getsource(valid_inspection)+'\n'+inspect.getsource(remote_probe)+'\nimport json\n'
    source+=('print(json.dumps(remote_probe('+repr(inspect.getsource(fixture_server))+','+
        repr(inspect.getsource(offline_bootstrap))+','+repr(writer)+')))\n')
    p=subprocess.run(['docker','exec','-i','-e','PYTHONPATH=/',PROJECT+'-execution-broker-1',
        'python','-c',source],capture_output=True,text=True)
    if p.returncode:raise RuntimeError('offline ACP probe unavailable; raw output withheld')
    result=json.loads(p.stdout);save_receipt(PRIVATE/'provider-probes'/('fixed-acp-patch-'+result['execution_id']+'.json'),result)
    print(json.dumps(result));return 0 if result['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
