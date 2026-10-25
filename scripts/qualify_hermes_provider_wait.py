"""Real SDK/native provider deferral with local HTTP only, never OpenRouter.

Inject 402 after author edits and during independent review. Preserve native
failure budget, lane, workspace and session across service restart; finish TDD.
This is mechanism qualification, not autonomous product delivery.
"""
import argparse
import http.client
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from qualify_hermes_delivery import create_trial,steps
from fabriquinha.effects import write_json
from fabriquinha.executor import docker
from fabriquinha.kanban_lane import native
from fabriquinha.provider import Policy,Relay,OUTPUT_LIMITS,server as relay_server
from fabriquinha.runtime import Runtime,recorded_worker,worker_alive


def qualify(root,upstream,image,*,max_output_tokens=4096):
    tests,impl=create_trial(root,upstream,image,namespace='delivery-kit-hermes-provider-wait')
    runtime=Runtime(root,upstream);kb,kbc,dispatch=native();services=[]
    # A real native failed spawn seeds one functional failure. Provider waits
    # must preserve it, not clear it as reclaim/unblock would do.
    with kbc.connect_closing() as conn:
        def failed(*args,**kwargs):raise RuntimeError('qualification injected spawn failure')
        dispatch.dispatch_once(conn,spawn_fn=failed,max_spawn=1,max_in_progress=2)
        assert kb.get_task(conn,tests).consecutive_failures==1
    meter=root/'fixture-meter';meter.mkdir(mode=0o700);write_json(meter/'calls.json',{'calls':0})
    key=root/'fixture.key';key.write_text('local-fixture-not-a-provider-credential');key.chmod(0o600)
    model='local/provider-wait-fixture';token='local-client-provider-wait-qualification'
    policy=Policy.parse(dict(version=1,project=runtime.project.fingerprint(),model=model,max_calls=80,
        max_output_tokens=max_output_tokens,enabled=True,client_token=token))
    injected={};sequences={};requests={};forwarded=[]
    class Response(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def respond(self,status,body):
            data=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert body.get('max_tokens',body.get('max_completion_tokens'))==max_output_tokens
            marker=next((m['content'].splitlines()[0] for m in reversed(body['messages'])
                if m.get('role')=='user' and isinstance(m.get('content'),str) and m['content'].startswith('Delivery activity ')),None)
            if not marker or body.get('stream'):self.respond(400,{});return
            binding=json.loads(marker.removeprefix('Delivery activity '));run=runtime.board.current(binding['task'],binding['number'])
            assert binding==run.binding();forwarded.append(binding)
            with kbc.connect_closing() as conn:
                changes=conn.execute("SELECT COUNT(*) FROM task_events WHERE task_id=? AND kind='changes_requested'",(run.task,)).fetchone()[0]
            if run.number not in sequences:
                sequence=steps(run,changes)
                if run.task==tests and not run.reviewing and not changes and 'author' in injected:
                    sequence=[('read_file',{'path':'/workspace/tests/test_new.py'}),('delivery_submit',{})]
                sequences[run.number]=sequence
            index=requests.get(run.number,0);requests[run.number]=index+1
            stage=('author' if run.task==tests and not run.reviewing and not changes and index==3 else
                   'review' if run.task==tests and run.reviewing and not changes and index==0 else None)
            if stage and stage not in injected:
                injected[stage]=binding;self.respond(402,{'error':{'message':'local fixture payment hold'}});return
            if index>=len(sequences[run.number]):self.respond(400,{});return
            name,args=sequences[run.number][index]
            self.respond(200,dict(id='local-'+str(run.number)+'-'+str(index),object='chat.completion',created=int(time.time()),
                model=model,choices=[dict(index=0,finish_reason='tool_calls',message=dict(role='assistant',content=None,
                    tool_calls=[dict(id='fixture-'+str(run.number)+'-'+str(index),type='function',
                                    function=dict(name=name,arguments=json.dumps(args)))]))],
                usage=dict(prompt_tokens=100,completion_tokens=50,total_tokens=150)))
    fixture=ThreadingHTTPServer(('127.0.0.1',0),Response)
    fixture_thread=threading.Thread(target=fixture.serve_forever,daemon=True);fixture_thread.start()
    class LocalRelay(Relay):
        def forward(self,body):
            connection=http.client.HTTPConnection('127.0.0.1',fixture.server_port,timeout=10)
            try:
                connection.request('POST','/v1/chat/completions',json.dumps(body),{'Content-Type':'application/json'})
                response=connection.getresponse();return response.status,response.read(4*1024*1024+1)
            finally:connection.close()
    relay=LocalRelay(policy,meter,key);owner=relay.ledger.owner();owner.__enter__()
    server=relay_server(relay,'127.0.0.1',0)
    relay_thread=threading.Thread(target=server.serve_forever,daemon=True);relay_thread.start()
    write_json(root/'provider-policy.json',policy.values())
    write_json(root/'route.json',dict(base_url='http://127.0.0.1:'+str(server.server_port)+'/v1',api_key=token,
        provider='custom',api_mode='chat_completions',model=model))
    def start():
        path=root/('service-'+str(len(services)+1)+'.log')
        with os.fdopen(os.open(path,os.O_CREAT|os.O_WRONLY,0o600),'wb') as log:
            process=subprocess.Popen([sys.executable,'-m','fabriquinha.runtime','serve','--root',str(root),
                '--upstream',str(upstream),'--interval','0.25'],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                env={**os.environ,'HERMES_KANBAN_RATE_LIMIT_COOLDOWN_SECONDS':'2'},start_new_session=True)
        services.append(process);return process
    def stop(process):
        if process.poll() is None:process.send_signal(signal.SIGTERM)
        process.wait(timeout=15);assert process.returncode==0
    def until(predicate,process):
        deadline=time.monotonic()+210
        while not predicate():
            if process.poll() is not None:raise RuntimeError('provider qualification service ended')
            with kbc.connect_closing() as conn:
                if any(kb.get_task(conn,task).status in ('blocked','triage') for task in (tests,impl)):
                    raise RuntimeError('provider qualification blocked; preserve diagnostics')
            if time.monotonic()>deadline:raise TimeoutError('observation expired; never restart live workers')
            time.sleep(0.1)
    def settled(stage):
        if stage not in injected:return False
        binding=injected[stage]
        with kbc.connect_closing() as conn:
            row=conn.execute('SELECT * FROM task_runs WHERE id=?',(binding['number'],)).fetchone()
            task=kb.get_task(conn,tests)
            return (row['ended_at'] is not None and row['outcome']=='spawn_failed'
                and not worker_alive(recorded_worker(conn,row)) and task.status==('review' if stage=='review' else 'ready'))
    process=start()
    try:
        for stage in ('author','review'):
            until(lambda:settled(stage),process)
            with kbc.connect_closing() as conn:assert kb.get_task(conn,tests).consecutive_failures==1
            assert not runtime.provider_status()['ready']
            count=relay.status()['calls'];before=len(forwarded)
            stop(process);process=start()  # Restart with the financial hold still present.
            time.sleep(2.5)
            assert relay.status()['calls']==count and len(forwarded)==before
            with kbc.connect_closing() as conn:
                assert kb.get_task(conn,tests).consecutive_failures==1
                assert not conn.execute('SELECT 1 FROM task_runs WHERE ended_at IS NULL').fetchone()
            assert (root/'work/tests/tests/test_new.py').read_text().endswith('app.VALUE,3)\n')
            # Only the isolated fixture meter is released; never touch a real meter.
            write_json(root/('fixture-pause-'+stage+'.json'),relay.ledger.read('provider-pause.json'))
            (meter/'provider-pause.json').unlink()
        def finished():
            with kbc.connect_closing() as conn:
                if not all(kb.get_task(conn,task).status=='done' for task in (tests,impl)):return False
                for row in conn.execute('SELECT * FROM task_runs').fetchall():
                    if row['ended_at'] is None:return False
                    spawned=conn.execute("SELECT 1 FROM task_events WHERE run_id=? AND kind IN ('spawned','worker_registered') LIMIT 1",(row['id'],)).fetchone()
                    if not row['worker_pid'] and not spawned:
                        assert row['outcome']=='spawn_failed'  # Refusal never created a process.
                        continue
                    if worker_alive(recorded_worker(conn,row)):return False
                return True
        until(finished,process);stop(process)
        with kbc.connect_closing() as conn:
            runs=[dict(row) for row in conn.execute('SELECT * FROM task_runs ORDER BY id')]
        waits=[json.loads(path.read_bytes()) for path in (root/'runs').glob('*/provider-wait.json')]
        assert len(waits)==2
        assert not any(row['outcome'] in ('blocked','crashed','failed','timed_out') for row in runs)
        activities=[json.loads(path.read_bytes()) for path in (root/'runs').glob('*/activity.json')]
        resumed=[a for a in activities if a['result']['resumed']]
        assert any(not a['binding']['reviewing'] for a in resumed) and any(a['binding']['reviewing'] for a in resumed)
        assert (root/'work/implementation/app.py').read_text()=='VALUE = 2\n'
        assert not docker('ps','-aq','--filter','label=com.docker.compose.project='+runtime.project.namespace+'-tests').strip()
        result=dict(passed=True,native_provider_waits=2,native_runs=len(runs),functional_failure_budget_preserved=True,
            author_files_preserved=True,review_lane_preserved=True,author_and_reviewer_sessions_resumed=True,
            restart_preserved_financial_hold=True,no_forwarding_or_reservation_during_hold=True,
            complete_tdd_after_recovery=True,local_provider_requests=len(forwarded),model_calls=0,
            synthetic_decisions=True,max_output_tokens=max_output_tokens,delivery_approval=False,migration=False)
        write_json(root/'receipt.json',result);print(json.dumps(result,indent=2));return result
    finally:
        runtime.pause()
        if process.poll() is None:
            deadline=time.monotonic()+20
            while not runtime.status()['control'].get('agents_stopped') and time.monotonic()<deadline:time.sleep(0.2)
            stop(process)
        server.shutdown();server.server_close();relay_thread.join(timeout=5);owner.__exit__(None,None,None)
        fixture.shutdown();fixture.server_close();fixture_thread.join(timeout=5)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--image',required=True)
    parser.add_argument('--max-output-tokens',type=int,choices=OUTPUT_LIMITS,default=4096)
    args=parser.parse_args()
    try:qualify(args.root.resolve(),args.upstream.resolve(),args.image,max_output_tokens=args.max_output_tokens)
    except BaseException as error:
        write_json(args.root/'failure.json',dict(category=type(error).__name__,delivery_approval=False))
        raise
