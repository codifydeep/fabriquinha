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
import socket
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


def qualify(root,upstream,image,*,notifications=False,review_escalation=False,provider_error=False,control_refusal=False,invalid_red=False,terminal_deadline=False,pr_in_guidance=False):
    if sum((review_escalation,control_refusal,invalid_red))>1 or (invalid_red or terminal_deadline) and provider_error:
        raise ValueError('choose one independent recovery scenario')
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
    resumed=threading.Event();release=threading.Event();sequences={};requests={};services=[];escalated_reviews=[];feedback_seen=[]
    control_ready=threading.Event();control_release=threading.Event();control_failed=[];control_seen=[];negative_reports=[]
    terminal_cids=[];terminal_verified=[]
    reference='https://github.com/example/qualification/pull/58';guidance_seen=[]
    deadline_probe='''python - <<'PY'
import signal, subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright
signal.signal(signal.SIGTERM, signal.SIG_IGN)
subprocess.Popen([sys.executable, '-c', 'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)', 'fabriquinha-detached-child'], start_new_session=True)
pw=sync_playwright().start()
browser=pw.chromium.launch()
Path('/workspace/tests/deadline-browser-started.txt').write_text('ready')
time.sleep(60)
PY'''
    process_probe='''import json,os
rows=[]
for name in os.listdir('/proc'):
 if not name.isdigit() or int(name) in (1,os.getpid()):continue
 try:
  text=open('/proc/'+name+'/cmdline','rb').read().decode(errors='replace')
 except OSError:continue
 if text:rows.append(dict(pid=int(name),sibling='fabriquinha-sibling-control' in text))
print(json.dumps(rows))'''
    sink=None;sink_thread=None;sink_data=dict(accepted={},attempts={},accepted_at={},lookups=0,lost=None)
    if notifications:
        class Sink(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def respond(self,status,result):
                data=json.dumps(dict(ok=status==200,result=result)).encode();self.send_response(status)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
                self.end_headers();self.wfile.write(data)
            def do_POST(self):
                value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                assert self.path=='/notifications'
                key=value['key'];sink_data['attempts'][key]=sink_data['attempts'].get(key,0)+1
                if key not in sink_data['accepted']:
                    sink_data['accepted'][key]=dict(message_id=len(sink_data['accepted'])+1,message=value['message'])
                    sink_data['accepted_at'][key]=sink_data['attempts'][key]
                    write_json(root/'sink.json',sink_data)
                if sink_data['lost'] is None:
                    sink_data['lost']=key;write_json(root/'sink.json',sink_data)
                    self.close_connection=True;self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                self.respond(200,dict(message_id=sink_data['accepted'][key]['message_id']))
            def do_GET(self):
                key=self.path.removeprefix('/notifications/');sink_data['lookups']+=1
                value=sink_data['accepted'].get(key)
                self.respond(200 if value else 404,dict(message_id=value['message_id']) if value else {})
        # Bound but not listening: connect() is refused before any HTTP bytes.
        # The model server below remains available while notifications are down.
        sink=ThreadingHTTPServer(('127.0.0.1',0),Sink,bind_and_activate=False);sink.server_bind()
        write_json(root/'notifications.json',dict(transport='local',endpoint='http://127.0.0.1:'+str(sink.server_port)))
    class Response(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            marker=next((m['content'].splitlines()[0] for m in reversed(body['messages'])
                if m.get('role')=='user' and isinstance(m.get('content'),str) and m['content'].startswith('Delivery activity ')),None)
            if not marker or body.get('stream'):self.send_error(400);return
            binding=json.loads(marker.removeprefix('Delivery activity '));run=runtime.board.current(binding['task'],binding['number'])
            assert run.binding()==binding
            native_context=next(m['content'] for m in body['messages'] if m.get('role')=='user' and
                isinstance(m.get('content'),str) and m['content'].startswith('Delivery activity '))
            assert 'Workspace: dir @ /workspace' in native_context,'native host path must not be advertised as tool workspace'
            if run.number not in sequences:
                with kbc.connect_closing() as conn:
                    changes=conn.execute("SELECT COUNT(*) FROM task_events WHERE task_id=? AND kind='changes_requested'",(run.task,)).fetchone()[0]
                finding=[dict(path='app.py',line=1,detail='Delivery needs an actual behavior test before implementation')]
                control_diagnosis=False
                if control_refusal and run.kind=='diagnostic':
                    incident=runtime.store.receipt(runtime.board.input(run,'incident'),kind='incident')
                    control_diagnosis=incident['binding']['kind']=='implementation'
                if control_diagnosis:
                    visible=json.loads(native_context.split('Controller-recorded Incident context:\n',1)[1])['last_control_refusal']
                    assert visible['feedback']['missing']==['test_existing.Existing.test_type']
                    assert visible['matches_current_snapshot'] and not visible['delivery_approval']
                    control_seen.append(run.number)
                    if run.actor=='flow-lead':
                        control_ready.set();control_release.wait()
                        sequence=[('read_file',{'path':'/workspace/app.py'}),
                            ('diagnostic_validate',dict(hypothesis='Current code passes but the numeric invariant lacks a mutation witness')),
                            ('diagnostic_decide',dict(action='escalate',reason='CTO must validate a product-only counterfactual for the exact missing numeric target',findings=finding))]
                    else:
                        sequence=[('read_file',{'path':'/workspace/tests/test_existing.py'}),
                            ('diagnostic_validate',dict(hypothesis='A noninteger product value must fail both feature and numeric invariant',replacements={'app.py':"VALUE = 'broken'\n"})),
                            ('diagnostic_decide',dict(action='resume',reason='Keep production VALUE=2 and submit a noninteger disposable mutation to witness the frozen numeric risk.',
                                findings=[dict(path='app.py',line=1,detail='The refused mutation missed the numeric invariant; use a product-only noninteger counterfactual, never edit tests.')]))]
                elif control_refusal and run.kind=='implementation' and not run.reviewing:
                    if not control_failed:
                        control_failed.append(run.number)
                        sequence=steps(run,changes)+[(None,'The incomplete control proposal did not qualify; diagnostic ownership is required.')]
                    else:
                        sequence=[('read_file',{'path':'/workspace/app.py'}),('delivery_submit',{'mutations':[{'app.py':"VALUE = 'broken'\n"}]})]
                elif run.number==1:sequence=[
                    ('terminal',dict(command='touch /workspace/tests/over-cap-marker.txt',timeout=570)),
                    ('read_file',{'path':'/workspace/tests/over-cap-marker.txt'}),
                    ('read_file',{'path':'/workspace/app.py'}),(None,'I will finish the task later.')]
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
                elif review_escalation and run.reviewing and run.kind=='tests' and not escalated_reviews:
                    escalated_reviews.append(run.number)
                    sequence=[('read_file',{'path':'/workspace/tests/test_new.py'}),
                        ('delivery_review',dict(decision='escalate',reason='Technical impasse needs a CTO experiment',
                            findings=[dict(path='tests/test_new.py',line=3,detail='Confirm expected value with a disposable CTO experiment before reviewing again')]))]
                else:
                    if run.task==source and not run.reviewing and changes:
                        context=str(body['messages'])
                        assert 'Expect value 2' in context,'full structured review finding must reach the author'
                        feedback_seen.append(run.number)
                    sequence=steps(run,changes)
                    if control_refusal and run.reviewing and run.kind=='tests' and sequence[-1][1]['decision']=='approve':
                        sequence[-1][1]['control_risks']=[dict(case='test_existing.Existing.test_type',reason='The product value must remain numeric; preserve and witness this existing behavior.')]
                if invalid_red:
                    if run.number==1:
                        sequence[-1:-1]=[
                            ('write_file',dict(path='/workspace/tests/test_new.py',content=
                                'import unittest, app\nclass NewBehavior(unittest.TestCase):\n def test_value(self): self.assertEqual(app.MISSING,2)\n')),
                            ('delivery_submit',{})]
                    elif run.kind=='diagnostic':
                        visible=json.loads(native_context.split('Controller-recorded Incident context:\n',1)[1])
                        assert 'Tests author' in visible['phase_expectation'] and 'Do not require Green' in visible['phase_expectation']
                        assert visible['last_suite_refusal']['report']['errors']==['test_new.NewBehavior.test_value']
                        assert visible['last_suite_refusal']['requires_fresh_validation']
                if terminal_deadline and run.number==1:
                    sequence.insert(3,('terminal',dict(command=deadline_probe,timeout=6)))
                if pr_in_guidance and run.kind=='diagnostic' and run.actor=='flow-cto':
                    sequence[-1][1]['reason']+=' Reference: '+reference
                if pr_in_guidance and run.task==source and not run.reviewing and run.number>1:
                    assert reference in str(body['messages']),'full guidance must be resolved from the immutable receipt'
                    guidance_seen.append(run.number)
                sequences[run.number]=sequence
            index=requests.get(run.number,0);requests[run.number]=index+1
            if invalid_red and run.kind=='diagnostic':
                last=body['messages'][-1].get('content')
                if isinstance(last,str):
                    try:observed=json.loads(last)
                    except ValueError:observed={}
                    if isinstance(observed,dict) and observed.get('experiment'):
                        assert observed['report']['errors']==['test_new.NewBehavior.test_value']
                        assert observed['delivery_approval'] is False
                        negative_reports.append(run.number)
            if run.number==1:
                schema=next(t['function']['parameters'] for t in body['tools'] if t['function']['name']=='terminal')
                assert schema['properties']['timeout']['maximum']==120
                if index==1:assert 'terminal timeout must be at most 120 seconds' in str(body['messages'][-1]['content'])
                if index==2:
                    assert not (runtime.board.workspace(run)/'tests/over-cap-marker.txt').exists(),'over-cap command must never execute'
                    assert 'not found' in str(body['messages'][-1]['content']).lower()
            if provider_error and run.number==1 and index==3:
                data=json.dumps(dict(error=dict(code='output_budget_exceeds_policy',message='output_budget_exceeds_policy'))).encode()
                self.send_response(422);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
            if terminal_deadline and run.number==1 and index==3:
                ids=docker('ps','-q','--filter','label=fabriquinha.task='+source,
                    '--filter','label=com.docker.compose.project='+project['namespace']+'-tests').split()
                assert len(ids)==1
                cid=json.loads(docker('inspect',ids[0]))[0]['Id'];terminal_cids.append(cid)
                docker('exec','-d',cid,'python','-c','import time;time.sleep(120)','fabriquinha-sibling-control')
            if terminal_deadline and run.number==1 and index==4:
                result=str(body['messages'][-1].get('content'))
                assert '124' in result and ('timed out' in result.lower() or 'deadline' in result.lower())
                until=time.monotonic()+12;stable=0
                while True:
                    rows=json.loads(docker('exec',terminal_cids[0],'python','-c',process_probe))
                    assert sum(row['sibling'] for row in rows)==1,'a different exec must survive'
                    stable=stable+1 if all(row['sibling'] for row in rows) else 0
                    if stable>=2:break
                    if time.monotonic()>until:raise TimeoutError('command descendants survived internal deadline')
                    time.sleep(.2)
                assert (runtime.board.workspace(run)/'tests/deadline-browser-started.txt').read_text()=='ready'
                terminal_verified.append(run.number)
            if run.kind=='diagnostic' and run.actor=='flow-lead' and index==1:
                assert 'VALUE' in str(body['messages'][-1].get('content')),'diagnostic must actually read the mounted source'
            if index>=len(sequences[run.number]):self.send_error(400);return
            if run.task==source and run.number!=1 and not run.reviewing and not resumed.is_set():
                assert not any(m.get('role')=='assistant' and m.get('content')=='I will finish the task later.'
                               for m in body['messages']),'failed final prose must not poison the diagnosed retry'
                assert 'Controller-recorded diagnostic guidance' in native_context
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
            if pr_in_guidance:
                with kbc.connect_closing() as conn:
                    current=kb.get_task(conn,source)
                    if current.status=='ready':
                        from hermes_cli.kanban_db_dispatch import check_respawn_guard
                        assert check_respawn_guard(conn,source,lane='ready')!='active_pr','diagnostic prose incorrectly activated the duplicate-PR guard'
            status_path=root/'status.json'
            if status_path.is_file():
                status=json.loads(status_path.read_bytes())['board']
                with kbc.connect_closing() as conn:
                    live=any(worker_alive(recorded_worker(conn,row)) for row in conn.execute('SELECT * FROM task_runs'))
                    cto_blocked=any(task.status=='blocked' and json.loads(task.body).get('stage')=='cto'
                        for task in runtime.recovery.cards(conn))
                fatal=(any(value=='ValueError' or isinstance(value,dict) and value.get('category') in ('ValueError','KeyError','TypeError')
                        for value in status['recovery_issues'].values()) or cto_blocked
                    or any(c['status']=='triage' for c in status['cards'])
                    or any(i['state'] in ('held','diagnosis_failed') for i in status.get('incidents',[])))
                if fatal and not live and not any(c['status']=='running' for c in status['cards']):
                    unattended=unattended or time.monotonic()
                    if time.monotonic()-unattended>10:raise RuntimeError('all work terminally blocked by recovery contract error')
                else:unattended=None
            if time.monotonic()-first>120 and not reported:
                print('Observing the same live service; no timeout restart.',flush=True);reported=True
            time.sleep(0.1)
    try:
        service=start();wait_for(resumed.is_set,service)
        if notifications:
            assert runtime.outbox.summary()['queued']>0 and not sink_data['accepted']
        with kbc.connect_closing() as conn:
            diagnostic_cards=[task for task in runtime.recovery.cards(conn) if json.loads(task.body).get('kind')=='diagnostic']
            incidents=runtime.recovery.status(conn)
            if provider_error:
                incident_id=json.loads(diagnostic_cards[0].body)['inputs']['incident']
                failure=runtime.store.receipt(incident_id,kind='incident')['payload']['failure']
                assert 'output_budget_exceeds_policy' in failure,'real SDK failure code must reach technical diagnosis'
            assert len(diagnostic_cards)==2 and all(task.status=='done' for task in diagnostic_cards)
            assert incidents and all(item['state']=='revalidating' for item in incidents)
            assert conn.execute("SELECT COUNT(*) FROM task_events WHERE task_id=? AND kind='unblocked'",(source,)).fetchone()[0]==1
        stop(service);service=start()
        wait_for(lambda:json.loads((root/'status.json').read_bytes())['dispatcher_pid']==service.pid,service)
        if notifications:
            sink.server_activate();sink_thread=threading.Thread(target=sink.serve_forever,daemon=True);sink_thread.start()
        release.set();print('Lead and CTO completed real diagnostics; author resumed once, incident still revalidating.',flush=True)
        def finished():
            with kbc.connect_closing() as conn:
                tasks=runtime.recovery.cards(conn)
                if not all(task.status=='done' for task in tasks):return False
                rows=conn.execute('SELECT * FROM task_runs').fetchall()
                return all(not worker_alive(recorded_worker(conn,row)) for row in rows)
        if control_refusal:
            wait_for(control_ready.is_set,service);stop(service);service=start()
            wait_for(lambda:json.loads((root/'status.json').read_bytes())['dispatcher_pid']==service.pid,service)
            control_release.set();print('Control refusal reached diagnosis; supervisor restarted before diagnostic tools executed.',flush=True)
        wait_for(finished,service)
        if notifications:
            def drained():
                summary=runtime.outbox.summary()
                with kbc.connect_closing() as conn:last=conn.execute('SELECT MAX(id) FROM task_events').fetchone()[0]
                cursor=json.loads((runtime.outbox.root/'cursor.json').read_bytes())['cursor']
                return cursor>=last and not any(summary[state] for state in ('queued','sending','uncertain','rejected','corrupt'))
            wait_for(drained,service)
        stop(service)
        with kbc.connect_closing() as conn:
            runs=[dict(row) for row in conn.execute('SELECT * FROM task_runs ORDER BY id')]
            assert len(runs)==(12 if control_refusal else 11 if review_escalation else 9) and runs[0]['outcome']=='blocked'
            assert len(runtime.recovery.cards(conn))==(6 if control_refusal else 5 if review_escalation else 4)
            incidents=runtime.recovery.status(conn);assert all(item['state']=='resolved' for item in incidents)
            assert conn.execute("SELECT COUNT(*) FROM task_events WHERE task_id=? AND kind='unblocked'",(source,)).fetchone()[0]==(2 if review_escalation else 1)
            assert conn.execute("SELECT COUNT(*) FROM task_comments WHERE task_id=? AND body LIKE 'DIAG %'",(source,)).fetchone()[0]==(2 if review_escalation else 1)
            decisions=[runtime.store.receipt(json.loads(r['metadata'])['diagnosis'],kind='diagnostic_decision')
                for r in runs if r['metadata'] and 'diagnosis' in json.loads(r['metadata'])]
        assert [r['payload']['action'] for r in decisions]==(['escalate','resume']*2 if control_refusal else ['escalate','resume','resume'] if review_escalation else ['escalate','resume'])
        if review_escalation:
            assert len(escalated_reviews)==1 and feedback_seen
            failed=next(r for r in runs if r['id']==escalated_reviews[0]);assert failed['outcome']=='blocked'
            following=next(r for r in runs if r['id']>failed['id'] and r['task_id']==source)
            assert following['profile']==failed['profile'],'recovery must resume independent review, not author mode'
        experiment=runtime.store.receipt(decisions[-1]['payload']['experiment'],kind='diagnostic_experiment')
        assert (runtime.store.tree(experiment['payload']['snapshot'])/'app.py').read_text()==("VALUE = 'broken'\n" if control_refusal else 'VALUE = 2\n')
        assert (root/'work/tests/app.py').read_text()=='VALUE = 1\n'
        assert (root/'work/implementation/app.py').read_text()=='VALUE = 2\n'
        assert not docker('ps','-aq','--filter','label=com.docker.compose.project='+project['namespace']+'-tests').strip()
        proof=dict(native_diagnostic_cards=True,lead_escalated_to_cto=True,cto_executed_real_disposable_spike=True,
            source_unchanged_by_diagnosticians=True,author_resumed_with_guidance=True,restart_did_not_duplicate_actions=True,
            incident_resolved_only_after_delivery_evidence=True,tdd_revalidated=True,diagnostics=len(decisions),runs=len(runs),
            local_http_requests=sum(requests.values()),synthetic_responses=True,model_calls=0,delivery_approval=False,migration=False)
        if review_escalation:proof.update(review_escalation_resumed_review=True,structured_findings_reached_author=True)
        if provider_error:proof.update(native_sdk_policy_error_reached_diagnosis=True)
        if invalid_red:
            assert len(set(negative_reports))==2
            assert experiment['payload']['report']['errors']==['test_new.NewBehavior.test_value']
            proof.update(negative_reports_reached_lead_and_cto=True,invalid_red_not_approved=True,
                test_author_resumed_without_requiring_green=True,diagnosis_did_not_replace_red_or_freeze=True)
        if terminal_deadline:
            assert terminal_verified==[1]
            proof.update(real_browser_started_before_deadline=True,detached_sigterm_ignoring_child_reaped=True,
                host_docker_client_timeout_did_not_leave_descendants=True,independent_sibling_exec_preserved=True)
        proof.update(diagnosed_retry_did_not_reuse_failed_final_prose=True)
        if pr_in_guidance:
            assert guidance_seen
            with kbc.connect_closing() as conn:
                comments=conn.execute("SELECT body FROM task_comments WHERE task_id=? AND body LIKE 'DIAG %'",(source,)).fetchall()
                assert comments and all(reference not in row['body'] for row in comments)
                # A genuine PR comment on an unrelated fixture card still guards.
                negative=kb.create_task(conn,title='Duplicate-PR guard negative control',assignee='flow-author',completion_contract='local-only')
                kb.add_comment(conn,negative,'fixture','Existing PR: '+reference)
                from hermes_cli.kanban_db_dispatch import check_respawn_guard
                assert check_respawn_guard(conn,negative,lane='ready')=='active_pr'
                kb.block_task(conn,negative,reason='Intentional duplicate-PR negative control; never delivery approval')
            proof.update(guidance_reference_only=True,full_guidance_from_receipt=True,native_duplicate_pr_guard_preserved=True)
        if control_refusal:
            assert len(control_failed)==1 and len(control_seen)==2
            failed=next(r for r in runs if r['id']==control_failed[0])
            worker_failure=runtime.store.receipt(json.loads(failed['summary'])['failure'],kind='worker_failure')
            refusal=runtime.store.receipt(worker_failure['payload']['control_refusal'],kind='control_refusal')
            assert refusal['binding']['number']==control_failed[0] and refusal['payload']['feedback']['missing']==['test_existing.Existing.test_type']
            proof.update(control_refusal_survived_worker_exit_and_supervisor_restart=True,
                missing_targets_reached_lead_and_cto=True,corrected_controls_revalidated_independently=True)
        proof.update(terminal_timeout_rejected_before_execution=True)
        if notifications:
            messages=[value['message'] for value in sink_data['accepted'].values()]
            for row in runs:
                starts=[message for message in messages if message['run']==row['id'] and message['event']=='started']
                ends=[message for message in messages if message['run']==row['id'] and message['event'] in
                    ('completed','blocked','review_requested','changes_requested','crashed','timed_out','gave_up')]
                assert len(starts)==len(ends)==1,(row['id'],starts,ends)
                assert starts[0]['actor']==ends[0]['actor']==row['profile']
            lost=sink_data['lost']
            assert lost and sink_data['lookups']>0
            assert sink_data['attempts'][lost]==sink_data['accepted_at'][lost]
            assert len(sink_data['accepted'])==runtime.outbox.summary()['delivered']
            proof['notifications']=dict(work_continued_during_connection_refusal=True,restart_preserved_outbox=True,
                lost_ack_observed_without_resend=True,every_run_started_and_ended_once=True,
                actor_matches_native_run=True,delivered=len(messages),actual_telegram=False)
        write_json(root/'receipt.json',proof);print(json.dumps(proof,indent=2))
    finally:
        release.set()
        control_release.set()
        for process in services:
            if process.poll() is None:stop(process)
        with kbc.connect_closing() as conn:rows=[recorded_worker(conn,row) for row in conn.execute('SELECT * FROM task_runs WHERE ended_at IS NULL')]
        for row in rows:
            if worker_alive(row):os.kill(row['worker_pid'],signal.SIGTERM)
        deadline=time.monotonic()+15
        while any(worker_alive(row) for row in rows) and time.monotonic()<deadline:time.sleep(0.1)
        if not any(worker_alive(row) for row in rows):runtime.settle()
        if sink_thread:sink.shutdown();sink_thread.join(timeout=5)
        if sink:sink.server_close()
        server.shutdown();server.server_close();thread.join(timeout=5)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--image',required=True);parser.add_argument('--notifications',action='store_true')
    scenario=parser.add_mutually_exclusive_group()
    scenario.add_argument('--review-escalation',action='store_true')
    scenario.add_argument('--control-refusal',action='store_true')
    scenario.add_argument('--invalid-red',action='store_true',help='Observe test errors in diagnosis, then require author repair and genuine Red/review/Green')
    parser.add_argument('--provider-error',action='store_true',help='Inject a local HTTP 422 to verify actual SDK error propagation')
    parser.add_argument('--terminal-deadline',action='store_true',help='Qualify actual browser/detached-child retirement after host exec client timeout')
    parser.add_argument('--pr-in-guidance',action='store_true')
    args=parser.parse_args()
    root=args.root.resolve();fresh=not root.exists()
    try:qualify(root,args.upstream.resolve(),args.image,notifications=args.notifications,review_escalation=args.review_escalation,
        provider_error=args.provider_error,control_refusal=args.control_refusal,invalid_red=args.invalid_red,terminal_deadline=args.terminal_deadline,pr_in_guidance=args.pr_in_guidance)
    except Exception as error:
        if fresh and root.exists():write_json(root/'failure.json',dict(qualification=False,error=type(error).__name__,
            reason=str(error),model_calls=0,native_state_preserved=True))
        raise
