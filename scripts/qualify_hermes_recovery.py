"""Native service: protocol failure -> lead -> CTO SPIKE -> author -> TDD.

Actual SDK/tools/Kanban/Docker, scripted loopback responses, no paid provider.
The harness creates the initial graph and injects a bad author turn. It never
unblocks the source or dispatches a diagnostic card itself.
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
from fabriquinha.runtime import Runtime, worker_alive


def qualify(root,upstream,image):
    source,impl=create_trial(root,upstream,image,namespace='delivery-kit-hermes-recovery')
    kb,kbc,_=native()
    from hermes_cli.profiles import create_profile
    for name in ('flow-lead','flow-cto'):
        create_profile(name,no_skills=True,description='Technical recovery infrastructure fixture')
        write_json(root/'home/profiles'/name/'config.yaml',dict(model={'streaming':False,'context_length':65536},
            auxiliary={'title_generation':{'enabled':False}},tools={'tool_search':{'enabled':'off'}},
            terminal={'backend':'fabriquinha','cwd':'/workspace'}))
    project=json.loads((root/'project.json').read_bytes());project['technical_roles']=dict(lead='flow-lead',cto='flow-cto')
    write_json(root/'project.json',project);runtime=Runtime(root,upstream)
    resumed=threading.Event();release=threading.Event();sequences={};requests={};services=[]
    class Response(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            marker=next((m['content'].splitlines()[0] for m in reversed(body['messages'])
                if m.get('role')=='user' and isinstance(m.get('content'),str) and m['content'].startswith('Delivery activity ')),None)
            if not marker or body.get('stream'):self.send_error(400);return
            binding=json.loads(marker.removeprefix('Delivery activity '));run=runtime.board.current(binding['task'],binding['number'])
            assert run.binding()==binding
            if run.number not in sequences:
                with kbc.connect_closing() as conn:
                    changes=conn.execute("SELECT COUNT(*) FROM task_events WHERE task_id=? AND kind='changes_requested'",(run.task,)).fetchone()[0]
                finding=[dict(path='app.py',line=1,detail='Delivery needs an actual behavior test before implementation')]
                if run.number==1:sequence=[('read_file',{'path':'/workspace/app.py'}),(None,'I will finish the task later.')]
                elif run.kind=='diagnostic' and run.actor=='flow-lead':
                    sequence=[('read_file',{'path':'/workspace/app.py'}),
                        ('diagnostic_decide',dict(action='resume',reason='Not enough evidence yet',findings=finding)),
                        ('diagnostic_validate',dict(hypothesis='Check that the existing baseline is executable')),
                        ('diagnostic_decide',dict(action='escalate',reason='Ask CTO to test a concrete missing-behavior hypothesis',findings=finding))]
                elif run.kind=='diagnostic':
                    sequence=[('write_file',dict(path='/workspace/app.py',content='VALUE = 99\n')),
                        ('read_file',{'path':'/workspace/tests/test_existing.py'}),
                        ('diagnostic_validate',dict(hypothesis='Forbidden test mutation must not run',
                            replacements={'tests/test_existing.py':'# weakened\n'})),
                        ('diagnostic_validate',dict(hypothesis='Changing VALUE still passes because only its type is tested',
                            replacements={'app.py':'VALUE = 2\n'})),
                        ('diagnostic_decide',dict(action='resume',reason='Add the approved VALUE=2 behavior test, observe real Red, then request independent review.',
                            findings=[dict(path='tests/test_existing.py',line=3,detail='The baseline checks type, not the required value; write a new behavior test.')]))]
                else:sequence=steps(run,changes)
                sequences[run.number]=sequence
            index=requests.get(run.number,0);requests[run.number]=index+1
            if index>=len(sequences[run.number]):self.send_error(400);return
            if run.task==source and run.number!=1 and not run.reviewing and not resumed.is_set():
                resumed.set();release.wait()
            name,args=sequences[run.number][index]
            if name:
                message=dict(role='assistant',content=None,tool_calls=[dict(id='recovery-'+str(run.number)+'-'+str(index),
                    type='function',function=dict(name=name,arguments=json.dumps(args)))])
            else:message=dict(role='assistant',content=args)
            value=dict(id='local-'+str(run.number)+'-'+str(index),object='chat.completion',created=int(time.time()),
                model=body['model'],choices=[dict(index=0,message=message,finish_reason='tool_calls' if name else 'stop')],
                usage=dict(prompt_tokens=100,completion_tokens=50,total_tokens=150))
            data=json.dumps(value).encode();self.send_response(200)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
            self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Response)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    write_json(root/'route.json',dict(base_url='http://127.0.0.1:'+str(server.server_port)+'/v1',api_key='offline-fixture',
        provider='custom',api_mode='chat_completions',model='fabriquinha-recovery-fixture'))
    def start():
        with os.fdopen(os.open(root/('service-'+str(len(services)+1)+'.log'),os.O_CREAT|os.O_WRONLY,0o600),'wb') as log:
            process=subprocess.Popen([sys.executable,'-m','fabriquinha.runtime','serve','--root',str(root),'--upstream',str(upstream),
                '--interval','0.25'],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        services.append(process);return process
    def stop(process):
        if process.poll() is None:process.send_signal(signal.SIGTERM)
        process.wait(timeout=15);assert process.returncode==0
    def wait_for(predicate,process):
        first=time.monotonic();reported=False;unattended=None
        while not predicate():
            if process.poll() is not None:raise RuntimeError('continuous service failed; inspect private log')
            status_path=root/'status.json'
            if status_path.is_file():
                status=json.loads(status_path.read_bytes())['board']
                with kbc.connect_closing() as conn:
                    live=any(worker_alive(row) for row in conn.execute('SELECT * FROM task_runs'))
                    cto_blocked=any(task.status=='blocked' and json.loads(task.body).get('stage')=='cto'
                        for task in runtime.recovery.cards(conn))
                fatal=any(value=='ValueError' for value in status['recovery_issues'].values()) or cto_blocked
                if fatal and not live and not any(c['status']=='running' for c in status['cards']):
                    unattended=unattended or time.monotonic()
                    if time.monotonic()-unattended>10:raise RuntimeError('all work terminally blocked by recovery contract error')
                else:unattended=None
            if time.monotonic()-first>120 and not reported:
                print('Observing the same live service; no timeout restart.',flush=True);reported=True
            time.sleep(0.1)
    try:
        service=start();wait_for(resumed.is_set,service)
        with kbc.connect_closing() as conn:
            diagnostic_cards=[task for task in runtime.recovery.cards(conn) if json.loads(task.body).get('kind')=='diagnostic']
            incidents=runtime.recovery.status(conn)
            assert len(diagnostic_cards)==2 and all(task.status=='done' for task in diagnostic_cards)
            assert incidents and all(item['state']=='revalidating' for item in incidents)
            assert conn.execute("SELECT COUNT(*) FROM task_events WHERE task_id=? AND kind='unblocked'",(source,)).fetchone()[0]==1
        stop(service);service=start()
        wait_for(lambda:json.loads((root/'status.json').read_bytes())['dispatcher_pid']==service.pid,service)
        release.set();print('Lead and CTO completed real diagnostics; author resumed once, incident still revalidating.',flush=True)
        def finished():
            with kbc.connect_closing() as conn:
                tasks=runtime.recovery.cards(conn)
                if not all(task.status=='done' for task in tasks):return False
                rows=conn.execute('SELECT * FROM task_runs').fetchall()
                return all(not worker_alive(row) for row in rows)
        wait_for(finished,service);stop(service)
        with kbc.connect_closing() as conn:
            runs=[dict(row) for row in conn.execute('SELECT * FROM task_runs ORDER BY id')]
            assert len(runs)==9 and runs[0]['outcome']=='blocked'
            assert len(runtime.recovery.cards(conn))==4
            incidents=runtime.recovery.status(conn);assert all(item['state']=='resolved' for item in incidents)
            assert conn.execute("SELECT COUNT(*) FROM task_events WHERE task_id=? AND kind='unblocked'",(source,)).fetchone()[0]==1
            assert conn.execute("SELECT COUNT(*) FROM task_comments WHERE task_id=? AND body LIKE 'DIAG %'",(source,)).fetchone()[0]==1
            decisions=[runtime.store.receipt(json.loads(r['metadata'])['diagnosis'],kind='diagnostic_decision')
                for r in runs if r['metadata'] and 'diagnosis' in json.loads(r['metadata'])]
        assert [r['payload']['action'] for r in decisions]==['escalate','resume']
        experiment=runtime.store.receipt(decisions[-1]['payload']['experiment'],kind='diagnostic_experiment')
        assert (runtime.store.tree(experiment['payload']['snapshot'])/'app.py').read_text()=='VALUE = 2\n'
        assert (root/'work/tests/app.py').read_text()=='VALUE = 1\n'
        assert (root/'work/implementation/app.py').read_text()=='VALUE = 2\n'
        assert not docker('ps','-aq','--filter','label=com.docker.compose.project='+project['namespace']+'-tests').strip()
        proof=dict(native_diagnostic_cards=True,lead_escalated_to_cto=True,cto_executed_real_disposable_spike=True,
            source_unchanged_by_diagnosticians=True,author_resumed_with_guidance=True,restart_did_not_duplicate_actions=True,
            incident_resolved_only_after_delivery_evidence=True,tdd_revalidated=True,diagnostics=2,runs=9,
            local_http_requests=sum(requests.values()),synthetic_responses=True,model_calls=0,delivery_approval=False,migration=False)
        write_json(root/'receipt.json',proof);print(json.dumps(proof,indent=2))
    finally:
        release.set()
        for process in services:
            if process.poll() is None:stop(process)
        with kbc.connect_closing() as conn:rows=conn.execute('SELECT * FROM task_runs WHERE ended_at IS NULL').fetchall()
        for row in rows:
            if worker_alive(row):os.kill(row['worker_pid'],signal.SIGTERM)
        deadline=time.monotonic()+15
        while any(worker_alive(row) for row in rows) and time.monotonic()<deadline:time.sleep(0.1)
        if not any(worker_alive(row) for row in rows):runtime.settle()
        server.shutdown();server.server_close();thread.join(timeout=5)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--image',required=True);args=parser.parse_args()
    root=args.root.resolve();fresh=not root.exists()
    try:qualify(root,args.upstream.resolve(),args.image)
    except Exception as error:
        if fresh and root.exists():write_json(root/'failure.json',dict(qualification=False,error=type(error).__name__,
            reason=str(error),model_calls=0,native_state_preserved=True))
        raise
