"""Real continuous service + native AIAgent/Docker; local scripted responses.

Restart only the dispatcher while its worker is healthy, then kill that exact
worker after a verified file write. Native recovery must preserve work/session,
retire its old sandbox and complete TDD without operator handoffs. Not a release.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
from qualify_hermes_delivery import create_trial, steps
from fabriquinha.artifacts import digest
from fabriquinha.effects import write_json
from fabriquinha.executor import docker
from fabriquinha.kanban_lane import native
from fabriquinha.runtime import Runtime, worker_alive


def qualify(root,upstream,image):
    tests,impl=create_trial(root,upstream,image,namespace='delivery-kit-hermes-service')
    kb,kbc,dispatch=native();runtime=Runtime(root,upstream)
    held=threading.Event();release=threading.Event();killed=threading.Event()
    requests={};sequences={};injected={};services=[]
    def active():
        with kbc.connect_closing() as conn:
            cards=[kb.get_task(conn,ident) for ident in (tests,impl)]
        if any(card.status in ('blocked','triage') for card in cards):
            raise RuntimeError('native fixture blocked; inspect private worker logs, no approval')
        return cards
    class Response(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            marker=next((message['content'].splitlines()[0] for message in reversed(body['messages'])
                if message.get('role')=='user' and isinstance(message.get('content'),str)
                and message['content'].startswith('Delivery activity ')),None)
            if not marker or body.get('stream'):
                self.send_error(400);return
            binding=json.loads(marker.removeprefix('Delivery activity '));number=binding['number']
            run=runtime.board.current(binding['task'],number)
            if run.binding()!=binding:raise ValueError('fixture context does not match actual native claim')
            if number not in sequences:
                with kbc.connect_closing() as conn:
                    changes=conn.execute('SELECT COUNT(*) FROM task_events WHERE task_id=? AND kind=?',
                                        (run.task,'changes_requested')).fetchone()[0]
                sequence=steps(run,changes)
                if run.kind=='tests' and not run.reviewing and not changes and killed.is_set():
                    assert (root/'work/tests/tests/test_new.py').read_text().endswith('app.VALUE,3)\n')
                    sequence=[('read_file',{'path':'/workspace/tests/test_new.py'}),('delivery_submit',{})]
                sequences[number]=sequence
            index=requests.get(number,0);requests[number]=index+1
            if index>=len(sequences[number]):self.send_error(400);return
            if run.kind=='tests' and not run.reviewing and not held.is_set() and index==1:
                injected['held_run']=number;held.set();release.wait()
            if run.kind=='tests' and not run.reviewing and not killed.is_set() and index==3:
                assert (root/'work/tests/tests/test_new.py').is_file()
                with kbc.connect_closing() as conn:
                    row=conn.execute('SELECT * FROM task_runs WHERE id=?',(number,)).fetchone()
                assert worker_alive(row),'only the verified live fixture worker may be signalled'
                os.kill(row['worker_pid'],signal.SIGKILL)
                injected['killed_run']=number;killed.set()
                self.send_error(503);return
            name,args=sequences[number][index]
            message=dict(role='assistant',content=None,tool_calls=[dict(id='service-'+str(number)+'-'+str(index),
                type='function',function=dict(name=name,arguments=json.dumps(args)))])
            value=dict(id='local-'+str(number)+'-'+str(index),object='chat.completion',created=int(time.time()),
                model=body['model'],choices=[dict(index=0,message=message,finish_reason='tool_calls')],
                usage=dict(prompt_tokens=100,completion_tokens=50,total_tokens=150))
            data=json.dumps(value).encode();self.send_response(200)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
            self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Response)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    write_json(root/'route.json',dict(base_url='http://127.0.0.1:'+str(server.server_port)+'/v1',
        api_key='offline-fixture',provider='custom',api_mode='chat_completions',model='fabriquinha-service-fixture'))
    def start():
        fd=os.open(root/('service-'+str(len(services)+1)+'.log'),os.O_CREAT|os.O_WRONLY,0o600)
        with os.fdopen(fd,'wb') as log:
            process=subprocess.Popen([sys.executable,'-m','fabriquinha.runtime','serve','--root',str(root),
                '--upstream',str(upstream),'--interval','0.25'],stdin=subprocess.DEVNULL,stdout=log,
                stderr=subprocess.STDOUT,start_new_session=True)
        services.append(process);return process
    def wait_for(predicate,service):
        observed=time.monotonic();reported=False
        while not predicate():
            if service.poll() is not None:raise RuntimeError('continuous dispatcher stopped unexpectedly')
            active()
            if time.monotonic()-observed>120 and not reported:
                print('Observation continuing on the same live dispatcher; no restart.',flush=True);reported=True
            time.sleep(0.1)
    def stop(service):
        if service.poll() is None:service.send_signal(signal.SIGTERM)
        service.wait(timeout=15)
        assert service.returncode==0,'dispatcher must stop cleanly, not kill its workers'
    try:
        service=start();wait_for(held.is_set,service)
        with kbc.connect_closing() as conn:
            before=dict(conn.execute('SELECT * FROM task_runs WHERE id=?',(injected['held_run'],)).fetchone())
        stop(service)
        assert worker_alive(before),'healthy worker must survive dispatcher shutdown'
        service=start()
        # A real second service, not a scripted handoff or a second claim.
        wait_for(lambda:(root/'status.json').is_file()
                 and json.loads((root/'status.json').read_bytes())['dispatcher_pid']==service.pid,service)
        with kbc.connect_closing() as conn:
            assert kb.get_task(conn,tests).current_run_id==before['id']
        assert worker_alive(before);release.set()
        print('Dispatcher restarted; its original worker and claim survived.',flush=True)
        wait_for(killed.is_set,service)
        def finished():
            cards=active()
            if not all(card.status=='done' for card in cards):return False
            with kbc.connect_closing() as conn:
                rows=conn.execute('SELECT * FROM task_runs').fetchall()
            return all(not worker_alive(row) for row in rows)
        wait_for(finished,service);stop(service)
        with kbc.connect_closing() as conn:
            runs=[dict(row) for row in conn.execute('SELECT * FROM task_runs ORDER BY id')]
        assert len(runs)==7 and runs[0]['outcome']=='crashed',[(r['id'],r['outcome']) for r in runs]
        assert [r['outcome'] for r in runs[1:]]==['review_requested','changes_requested','review_requested',
            'completed','review_requested','completed']
        activities=[json.loads((root/'runs'/str(row['id'])/'activity.json').read_bytes()) for row in runs[1:]]
        assert activities[0]['result']['resumed'] and activities[2]['result']['resumed'] and activities[3]['result']['resumed']
        intents=[json.loads(path.read_bytes()) for path in (runtime.store.root/'effects').glob('*.json')]
        creates={state['identity']['binding']['number']:state for state in intents
            if isinstance(state.get('identity'),dict) and set(state['identity'])=={
                'binding','project','workspace','phase','baseline_tests','image'}
            and state['identity']['binding']['task']==tests
            and (runtime.store.root/'effects'/(digest(digest(state['identity'])+':agent-create')+'.json')).is_file()
            and state['state']=='done' and 'container' in state.get('result',{})}
        prior=creates[runs[0]['id']];replacement=creates[runs[1]['id']]
        retired=runtime.store.root/'agents'/digest(prior['identity'])/'retirement.json'
        assert retired.stat().st_mtime<=replacement['started'],'orphan must be retired before replacement sandbox creation'
        runtime.settle()
        assert not runtime.settlement
        assert not docker('ps','-aq','--filter','label=com.docker.compose.project='+runtime.project.namespace+'-tests').strip()
        assert (root/'work/tests/app.py').read_text()=='VALUE = 1\n'
        assert (root/'work/implementation/app.py').read_text()=='VALUE = 2\n'
        proof=dict(continuous_native_dispatch=True,real_native_agent_tools=True,real_docker_tdd=True,
            dispatcher_restart_preserved_live_worker=True,crashed_worker_recovered=True,
            orphan_sandbox_retired_before_replacement=True,workspace_and_session_preserved=True,
            independent_review_changes_freeze_green_controls=True,cards_done=2,runs=7,
            local_http_requests=sum(requests.values()),synthetic_responses=True,model_calls=0,
            delivery_approval=False,migration=False)
        write_json(root/'receipt.json',proof);print(json.dumps(proof,indent=2))
    except Exception:
        # A verified failed fixture is terminal, unlike an observation timeout.
        # Quiesce only its fingerprinted workers before withdrawing the local
        # model transport; never turn a healthy unrelated worker into an outage.
        for service in services:
            if service.poll() is None:stop(service)
        with kbc.connect_closing() as conn:
            rows=conn.execute('SELECT * FROM task_runs WHERE ended_at IS NULL').fetchall()
        for row in rows:
            if worker_alive(row):os.kill(row['worker_pid'],signal.SIGTERM)
        deadline=time.monotonic()+15
        while any(worker_alive(row) for row in rows) and time.monotonic()<deadline:time.sleep(0.1)
        if not any(worker_alive(row) for row in rows):runtime.settle()
        raise
    finally:
        release.set()
        for service in services:
            if service.poll() is None:stop(service)
        server.shutdown();server.server_close();thread.join(timeout=5)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--image',required=True);args=parser.parse_args()
    root=args.root.resolve();fresh=not root.exists()
    try:qualify(root,args.upstream.resolve(),args.image)
    except Exception as error:
        if fresh and root.exists():write_json(root/'failure.json',dict(qualification=False,model_calls=0,
            error=type(error).__name__,reason=str(error),native_state_preserved=True))
        raise
