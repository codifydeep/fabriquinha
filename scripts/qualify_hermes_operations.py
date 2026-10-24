"""Real SDK pause/resume and native profile admission, with local fixed replies.

Pause once during authoring and once during immutable review. Restart while
paused, refuse stale resume authority, restore a missing reviewer, finish TDD.
No real model, paid calls, GitHub mutation, product approval or migration.
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
from fabriquinha.effects import write_json
from fabriquinha.executor import docker
from fabriquinha.kanban_lane import native
from fabriquinha.runtime import Runtime, worker_alive, recorded_worker


def qualify(root,upstream,image):
    tests,impl=create_trial(root,upstream,image,namespace='delivery-kit-hermes-operations')
    project=json.loads((root/'project.json').read_bytes())
    project['reviewers']['mobile']='flow-reviewer'  # Absent and unused must not stop web work.
    write_json(root/'project.json',project)
    runtime=Runtime(root,upstream);kb,kbc,_=native()
    held={kind:threading.Event() for kind in ('author','review')}
    release={kind:threading.Event() for kind in held};paused={};sequences={};requests={};services=[]
    class Response(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            marker=next((message['content'].splitlines()[0] for message in reversed(body['messages'])
                if message.get('role')=='user' and isinstance(message.get('content'),str)
                and message['content'].startswith('Delivery activity ')),None)
            if not marker or body.get('stream'):self.send_error(400);return
            binding=json.loads(marker.removeprefix('Delivery activity '));run=runtime.board.current(binding['task'],binding['number'])
            assert binding==run.binding()
            if run.number not in sequences:
                with kbc.connect_closing() as conn:
                    changes=conn.execute("SELECT COUNT(*) FROM task_events WHERE task_id=? AND kind='changes_requested'",(run.task,)).fetchone()[0]
                sequence=steps(run,changes)
                if run.task==tests and not run.reviewing and not changes and held['author'].is_set():
                    sequence=[('read_file',{'path':'/workspace/tests/test_new.py'}),('delivery_submit',{})]
                sequences[run.number]=sequence
            index=requests.get(run.number,0);requests[run.number]=index+1
            if index>=len(sequences[run.number]):self.send_error(400);return
            kind=('author' if run.task==tests and not run.reviewing and index==3 and not held['author'].is_set()
                  else 'review' if run.task==tests and run.reviewing and index==0 and not held['review'].is_set() else None)
            if kind:
                paused[kind]=run.binding();held[kind].set();release[kind].wait()
            name,args=sequences[run.number][index]
            value=dict(id='local-'+str(run.number)+'-'+str(index),object='chat.completion',created=int(time.time()),
                model=body['model'],choices=[dict(index=0,finish_reason='tool_calls',message=dict(role='assistant',content=None,
                    tool_calls=[dict(id='ops-'+str(run.number)+'-'+str(index),type='function',
                                    function=dict(name=name,arguments=json.dumps(args)))]))],
                usage=dict(prompt_tokens=100,completion_tokens=50,total_tokens=150))
            data=json.dumps(value).encode()
            try:
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError):pass  # Expected cancellation of a held request.
    server=ThreadingHTTPServer(('127.0.0.1',0),Response)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    write_json(root/'route.json',dict(base_url='http://127.0.0.1:'+str(server.server_port)+'/v1',api_key='local-fixture',
        provider='custom',api_mode='chat_completions',model='fabriquinha-operations-fixture'))
    def command(operation,*extra,success=True):
        result=subprocess.run([sys.executable,'-m','fabriquinha.runtime',operation,'--root',str(root),
            '--upstream',str(upstream),*extra],capture_output=True,text=True,timeout=45)
        if success:
            if result.returncode:raise RuntimeError('operational CLI failed; preserve private diagnostics: '+operation)
            return json.loads(result.stdout)
        assert result.returncode!=0
        write_json(root/('rejected-'+operation+'-'+str(time.time_ns())+'.json'),
                   dict(returncode=result.returncode,stderr=result.stderr))
    def start():
        with os.fdopen(os.open(root/('service-'+str(len(services)+1)+'.log'),os.O_CREAT|os.O_WRONLY,0o600),'wb') as log:
            service=subprocess.Popen([sys.executable,'-m','fabriquinha.runtime','serve','--root',str(root),
                '--upstream',str(upstream),'--interval','0.25'],stdin=subprocess.DEVNULL,stdout=log,
                stderr=subprocess.STDOUT,start_new_session=True)
        services.append(service);return service
    def stop(service):
        if service.poll() is None:service.send_signal(signal.SIGTERM)
        service.wait(timeout=15);assert service.returncode==0
    def until(predicate,service):
        start_at=time.monotonic()
        while not predicate():
            if service.poll() is not None:raise RuntimeError('operations service ended unexpectedly')
            with kbc.connect_closing() as conn:
                if any(kb.get_task(conn,task).status in ('blocked','triage') for task in (tests,impl)):
                    raise RuntimeError('operations fixture blocked; preserve logs, no approval')
            if time.monotonic()-start_at>180:raise TimeoutError('observation expired; do not restart live workers')
            time.sleep(0.1)
    def drained():return runtime.status()['control'].get('drained') is True
    def no_new_calls(duration=1):
        before=dict(requests);time.sleep(duration);assert requests==before
    service=start();reviewer=root/'home/profiles/flow-reviewer';hidden=root/'home/profiles/.withheld-reviewer'
    try:
        until(held['author'].is_set,service)
        assert (root/'work/tests/tests/test_new.py').read_text().endswith('app.VALUE,3)\n')
        first=command('pause')['control']['episode'];until(drained,service);no_new_calls()
        with kbc.connect_closing() as conn:
            assert kb.get_task(conn,tests).status=='ready'
            assert kb.latest_run(conn,tests).outcome=='reclaimed'
        release['author'].set();stop(service)
        (root/'route.json').rename(root/'route.held.json');reviewer.rename(hidden)
        service=start()
        until(lambda:(root/'status.json').is_file()
            and json.loads((root/'status.json').read_bytes())['dispatcher_pid']==service.pid,service)
        assert runtime.control.read()['paused'];no_new_calls()
        command('resume','--expect-pause',first,success=False)  # Missing route cannot lift pause.
        assert runtime.control.read()['paused']
        (root/'route.held.json').rename(root/'route.json')
        check=command('doctor');assert check['ready'] and check['missing_profiles']==['flow-reviewer','mobile']
        command('resume','--expect-pause',first)
        def reviewer_waiting():
            with kbc.connect_closing() as conn:
                return kb.get_task(conn,tests).status=='review' and conn.execute(
                    "SELECT 1 FROM task_events WHERE task_id=? AND kind='skipped_nonspawnable'",(tests,)).fetchone()
        until(reviewer_waiting,service)
        with kbc.connect_closing() as conn:assert kb.get_task(conn,tests).consecutive_failures==0
        hidden.rename(reviewer);until(held['review'].is_set,service)
        second=command('pause')['control']['episode'];assert second!=first
        until(drained,service);no_new_calls()
        with kbc.connect_closing() as conn:assert kb.get_task(conn,tests).status=='review'
        command('resume','--expect-pause',first,success=False)
        assert runtime.control.read()['paused'];release['review'].set()
        command('resume','--expect-pause',second)
        def finished():
            with kbc.connect_closing() as conn:
                if not all(kb.get_task(conn,task).status=='done' for task in (tests,impl)):return False
                return all(row['ended_at'] is not None and not worker_alive(recorded_worker(conn,row))
                           for row in conn.execute('SELECT * FROM task_runs').fetchall())
        until(finished,service);stop(service)
        with kbc.connect_closing() as conn:
            runs=[dict(row) for row in conn.execute('SELECT * FROM task_runs ORDER BY id')]
        assert len(runs)==8 and [row['outcome'] for row in runs].count('reclaimed')==2
        assert not any(row['outcome'] in ('blocked','crashed','failed','timed_out') for row in runs)
        activities=[json.loads((root/'runs'/str(row['id'])/'activity.json').read_bytes()) for row in runs]
        assert activities[1]['result']['resumed'] and activities[3]['result']['resumed']
        assert activities[0]['interrupted'] and activities[2]['interrupted']
        assert (root/'work/tests/app.py').read_text()=='VALUE = 1\n'
        assert (root/'work/implementation/app.py').read_text()=='VALUE = 2\n'
        assert not docker('ps','-aq','--filter','label=com.docker.compose.project='+runtime.project.namespace+'-tests').strip()
        result=dict(persistent_pause=True,restart_without_model_route_while_paused=True,
            inflight_sdk_cancelled=True,no_new_calls_after_pause_confirmation=True,
            author_files_and_session_preserved=True,review_phase_and_session_preserved=True,
            stale_resume_refused=True,missing_profile_did_not_spend_retry=True,
            absent_unused_role_did_not_stop_work=True,complete_tdd_after_resume=True,
            native_runs=len(runs),local_http_requests=sum(requests.values()),model_calls=0,
            delivery_approval=False,migration=False)
        write_json(root/'receipt.json',result);print(json.dumps(result,indent=2))
    finally:
        for event in release.values():event.set()
        if hidden.exists() and not reviewer.exists():hidden.rename(reviewer)
        if (root/'route.held.json').exists() and not (root/'route.json').exists():
            (root/'route.held.json').rename(root/'route.json')
        if service.poll() is None:
            command('pause')
            deadline=time.monotonic()+20
            while not runtime.status()['control'].get('agents_stopped') and time.monotonic()<deadline:time.sleep(0.2)
            stop(service)
        server.shutdown();server.server_close();thread.join(timeout=5)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--image',required=True);args=parser.parse_args()
    qualify(args.root.resolve(),args.upstream.resolve(),args.image)
