"""Real Hermes compression wire through the relay, with a fake provider.

No Docker, GitHub, production key/meter, model judgment or delivery approval.
The socket guard forbids every connection except this fixture's loopback port.
"""
import argparse
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from qualify_hermes_s1 import prepare
from qualify_hermes_agent import check_dependencies
from fabriquinha.artifacts import Store
from fabriquinha.effects import write_json
from fabriquinha.hermes import activity_route
from fabriquinha.provider import Policy,Relay,server


def qualify(root,upstream):
    if root.exists():raise ValueError('fresh private fixture root required')
    root.mkdir(parents=True,mode=0o700);home=prepare(root,upstream);check_dependencies()
    write_json(home/'config.yaml',dict(model=dict(context_length=65536),auxiliary=dict(title_generation=dict(enabled=False))))
    token='local-auxiliary-fixture-only';model='fabriquinha/auxiliary-fixture';project='a'*64
    key=root/'fixture.key';key.write_text('fixture-not-a-provider-key');key.chmod(0o600)
    meter=root/'meter';meter.mkdir(mode=0o700);write_json(meter/'calls.json',dict(calls=0))
    app=Relay(Policy.parse(dict(version=1,project=project,model=model,max_calls=8,max_output_tokens=16384,
        enabled=True,client_token=token)),meter,key)
    calls=[]
    def forward(body):
        calls.append(body)
        reply=dict(id='fixture',object='chat.completion',created=int(time.time()),model=model,
            choices=[dict(index=0,finish_reason='stop',message=dict(role='assistant',content='Verified fixture summary preserves the current state and immutable evidence.'))],
            usage=dict(prompt_tokens=10,completion_tokens=10,total_tokens=20,cost=0))
        return 200,json.dumps(reply).encode()
    app.forward=forward
    relay_server=server(app,'127.0.0.1',0);thread=threading.Thread(target=relay_server.serve_forever,daemon=True);thread.start()
    route=dict(provider='custom',model=model,base_url='http://127.0.0.1:'+str(relay_server.server_port)+'/v1',api_key=token,api_mode='chat_completions')
    store=Store(root/'private');activity=store.record('model_activity',dict(actor='fixture',task='fixture',number=1),dict(project=project))
    connect=socket.socket.connect;blocked=[]
    def local_only(sock,address):
        if not isinstance(address,tuple) or address[:2]!=('127.0.0.1',relay_server.server_port):
            blocked.append('blocked-external-target');raise RuntimeError('fixture permits only its own loopback endpoint')
        return connect(sock,address)
    try:
        with patch.object(socket.socket,'connect',local_only),patch.dict(os.environ,NO_PROXY='127.0.0.1,localhost',HTTP_PROXY='',HTTPS_PROXY='',ALL_PROXY=''):
            from agent.context_compressor import ContextCompressor
            assert Path(sys.modules['agent.context_compressor'].__file__).resolve().is_relative_to(upstream)
            def compress(selected):
                compressor=ContextCompressor(model=model,provider='custom',base_url=selected['base_url'],api_key=token,
                    api_mode='chat_completions',config_context_length=65536,quiet_mode=True)
                return compressor._call_summary_llm('Summarize the known fixture state without inventing any work.',time.monotonic())
            assert compress(route)
            first=app.ledger.read('attempts/1.json');assert 'activity' not in first
            scoped=activity_route(route,activity)
            assert compress(scoped)
            second=app.ledger.read('attempts/2.json');assert second['activity']==activity
            assert first==app.ledger.read('attempts/1.json')  # No retroactive attribution.
            connection=http.client.HTTPConnection('127.0.0.1',relay_server.server_port,timeout=5)
            body=json.dumps(dict(model=model,messages=[dict(role='user',content='fixture')]))
            try:
                connection.request('POST','/activities/'+activity+'/v1/chat/completions',body,
                    {'Content-Type':'application/json','Authorization':'Bearer '+token,'X-Fabriquinha-Activity':'b'*64})
                response=connection.getresponse();assert response.status==400;response.read()
            finally:connection.close()
            assert app.ledger.state()['calls']==2 and len(calls)==2
        usage=app.ledger.usage(project)
        assert usage['activities'][activity]['attempts']==1 and usage['activities']['unattributed']['attempts']==1
        assert not blocked
        assert not subprocess.check_output(['git','-C',str(upstream),'status','--porcelain'],text=True).strip()
        result=dict(passed=True,real_native_compressor=True,real_http_relay=True,fake_upstream=True,paid_calls=0,
            legacy_header_gap_reproduced=True,auxiliary_inherited_activity_address=True,scope_mismatch_rejected_without_charge=True,
            old_unattributed_record_unchanged=True,local_calls=2,external_connections=0,production_meter_touched=False,
            upstream_file_patches=0,delivery_approval=False)
        write_json(root/'receipt.json',result);print(json.dumps(result,indent=2));return result
    finally:relay_server.shutdown();relay_server.server_close();thread.join(timeout=5)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    args=parser.parse_args();qualify(args.root.resolve(),args.upstream.resolve())
