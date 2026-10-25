"""Native SDK intake/CEO approval/independent plan review, fixed local replies.

No pre-created work graph, Docker job, real model, GitHub mutation or release
approval. Product/planner output is synthetic: this qualifies mechanisms only.
"""
import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from qualify_hermes_s1 import prepare
from qualify_hermes_agent import check_dependencies
from fabriquinha.effects import write_json
from fabriquinha.intake import HUMAN_REVIEWER
from fabriquinha.kanban_lane import native
from fabriquinha.runtime import Runtime, recorded_worker, worker_alive


def qualify(root,upstream,image,*,neutral_relay=False):
    if root.exists():raise ValueError('fresh private root required')
    root.mkdir(mode=0o700,parents=True);check_dependencies();home=prepare(root,upstream)
    os.environ['HERMES_DISABLE_LAZY_INSTALLS']='1';kb,kbc,_=native()
    with kbc.connect_closing():pass
    from hermes_cli.profiles import create_profile,profile_exists
    assert not profile_exists(HUMAN_REVIEWER)
    for name in ('intake-product','intake-lead','intake-cto'):
        create_profile(name,no_skills=True,description='Fixed local business intake qualification')
        write_json(home/'profiles'/name/'config.yaml',dict(model={'streaming':False,'context_length':65536},
            auxiliary={'title_generation':{'enabled':False}},tools={'tool_search':{'enabled':'off'}}))
    write_json(root/'project.json',dict(version=1,namespace='delivery-kit-hermes-intake',
        repository='https://github.com/example/intake-qualification',branch='release/qualification',
        validation_image=image,tests_dir='tests',reviewers={'intake-lead':'intake-cto'},qualification=True,
        coordination_roles={'product':'intake-product','lead':'intake-lead'}))
    runtime=Runtime(root,upstream)
    objective=dict(request='intake-proof',label='v0.1',objective='A local web lobby. Create a room and join it from a second browser. No mobile.')
    initial=runtime.intake.start(objective);assert runtime.intake.start(objective)==initial
    def refused(call):
        try:call()
        except ValueError:return
        raise AssertionError('negative control was accepted')
    refused(lambda:runtime.intake.start({**objective,'objective':'Reused key, changed objective'}))
    refused(lambda:runtime.intake.start({**objective,'request':'another-release'}))
    def task(kind):
        with kbc.connect_closing() as conn:
            tasks=[kb.get_task(conn,row['id']) for row in conn.execute('SELECT id,body FROM tasks')
                   if json.loads(row['body']).get('kind')==kind]
            assert len(tasks)==1
            return tasks[0]
    brief_task=task('brief');assert len(runtime.status()['cards'])==2
    approved=dict(summary='Anonymous two-browser local lobby.',criteria=[
        dict(id='CREATE',statement='Create a named room.'),dict(id='JOIN',statement='Join the room from a separate browser.')],
        assumptions=['Local network only'],out_of_scope=['Mobile'],observability='Count create/join failures without user identifiers.')
    proposed=dict(architecture='Local HTTP API with server-owned room state.',observability='Track failed joins.',tasks=[
        dict(id='create',title='Create room',owner='intake-lead',depends_on=[],criteria=['CREATE'],acceptance='Room visible in lobby.'),
        dict(id='join',title='Join room',owner='intake-lead',depends_on=['create'],criteria=['JOIN'],acceptance='Both clients see the same room.')])
    sequences={};requests={};counters=dict(product=0,lead=0,cto=0);all_requests=[]
    class Response(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            marker=next((m['content'].splitlines()[0] for m in reversed(body['messages'])
                if m.get('role')=='user' and isinstance(m.get('content'),str) and m['content'].startswith('Delivery activity ')),None)
            if not marker or body.get('stream'):self.send_error(400);return
            binding=json.loads(marker.removeprefix('Delivery activity '));run=runtime.board.current(binding['task'],binding['number'])
            assert run.binding()==binding
            expected={'plan_review'} if run.reviewing else {'brief_submit','brief_question'} if run.kind=='brief' else {'plan_submit'}
            assert {tool['function']['name'] for tool in body['tools']}==expected
            if run.kind=='plan' and not run.reviewing:
                from fabriquinha.intake import WORK_ID_PATTERN
                schema=body['tools'][0]['function']['parameters']['properties']['tasks']
                fields=schema['items']['properties']
                assert fields['id']['pattern']==WORK_ID_PATTERN
                assert fields['owner']['enum']==list(runtime.project.reviewers)
                assert fields['criteria']['items']['enum']==['CREATE','JOIN']
            all_requests.append(dict(binding=binding,tools=sorted(expected),max_tokens=body.get('max_tokens')))
            if run.number not in sequences:
                actor='product' if run.kind=='brief' else 'cto' if run.reviewing else 'lead'
                index=counters[actor];counters[actor]+=1
                if actor=='product':
                    sequence=[('brief_question',dict(question='User-facing choice '+str(index),context='Essential business clarification',
                        options=['Option A','Option B']))] if index<3 else [('brief_submit',approved)]
                elif actor=='lead':
                    sequence=[]
                    if index==0:
                        partial={**proposed,'tasks':[proposed['tasks'][0]]}
                        sequence.append(('plan_submit',partial))  # Real handler must reject missing criterion.
                    sequence.append(('plan_submit',proposed))
                else:
                    sequence=[('plan_review',dict(decision='changes' if index==0 else 'approve',
                        reason='Clarify the dependency acceptance.' if index==0 else 'Independent plan and scope review.',
                        findings=['Make the join dependency explicit.'] if index==0 else []))]
                sequences[run.number]=sequence
            index=requests.get(run.number,0);requests[run.number]=index+1
            if index>=len(sequences[run.number]):self.send_error(400);return
            if run.kind=='plan' and not run.reviewing and index==1:
                assert any('complete approved brief' in str(m.get('content')) for m in body['messages'] if m.get('role')=='tool')
            name,args=sequences[run.number][index]
            value=dict(id='local-'+str(run.number)+'-'+str(index),object='chat.completion',created=int(time.time()),model=body['model'],
                choices=[dict(index=0,finish_reason='tool_calls',message=dict(role='assistant',content=None,
                    tool_calls=[dict(id='intake-'+str(run.number)+'-'+str(index),type='function',
                        function=dict(name=name,arguments=json.dumps(args)))]))],usage=dict(prompt_tokens=100,completion_tokens=50,total_tokens=150))
            raw=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',0),Response);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    relay=None;relay_server=None;relay_thread=None;relay_owner=None;port=server.server_port;client_key='local-fixture'
    model='local/fabriquinha-intake-fixture'
    if neutral_relay:
        from fabriquinha.provider import Policy,Relay,server as relay_factory
        meter=root/'relay-meter';meter.mkdir(mode=0o700);write_json(meter/'calls.json',{'calls':0})
        key=root/'relay-fixture.key';key.write_text('not-a-provider-credential-only-fixture');key.chmod(0o600)
        client_key='local-relay-client-for-qualification'
        policy=Policy.parse(dict(version=1,project=runtime.project.fingerprint(),model=model,max_calls=32,
            max_output_tokens=4096,enabled=True,client_token=client_key))
        class LocalRelay(Relay):
            def forward(self,body):
                connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
                try:
                    connection.request('POST','/v1/chat/completions',json.dumps(body),{'Content-Type':'application/json'})
                    response=connection.getresponse();return response.status,response.read(4*1024*1024+1)
                finally:connection.close()
        relay=LocalRelay(policy,meter,key);relay_owner=relay.ledger.owner();relay_owner.__enter__()
        relay_server=relay_factory(relay,'127.0.0.1',0);port=relay_server.server_port
        relay_thread=threading.Thread(target=relay_server.serve_forever,daemon=True);relay_thread.start()
    write_json(root/'route.json',dict(base_url='http://127.0.0.1:'+str(port)+'/v1',api_key=client_key,
        provider='custom',api_mode='chat_completions',model=model))
    services=[]
    def start():
        with os.fdopen(os.open(root/('service-'+str(len(services)+1)+'.log'),os.O_CREAT|os.O_WRONLY,0o600),'wb') as log:
            service=subprocess.Popen([sys.executable,'-m','fabriquinha.runtime','serve','--root',str(root),
                '--upstream',str(upstream),'--interval','0.25'],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        services.append(service);return service
    def stop(service):
        if service.poll() is None:service.send_signal(signal.SIGTERM)
        service.wait(timeout=15);assert service.returncode==0
    def until(predicate,service):
        started=time.monotonic()
        while not predicate():
            if service.poll() is not None:raise RuntimeError('intake service stopped unexpectedly')
            with kbc.connect_closing() as conn:
                if conn.execute("SELECT 1 FROM tasks WHERE status IN ('blocked','triage') AND id!=?",(initial['release'],)).fetchone():
                    raise RuntimeError('intake blocked; preserve evidence')
            if time.monotonic()-started>120:raise TimeoutError('observation expired; inspect the same live processes')
            time.sleep(0.1)
    def pending():
        current=task('brief')
        if current.status!='review':return None
        with kbc.connect_closing() as conn:
            row=kb.latest_run(conn,current.id)
            return (row.metadata or {}).get('request') if row else None
    def reply(expected,decision):
        return runtime.intake.respond(brief_task.id,expected,decision,'CEO business response for this request only')
    def cli(operation,*extra):
        result=subprocess.run([sys.executable,'-m','fabriquinha.intake',operation,'--root',str(root),
            '--upstream',str(upstream),*extra],text=True,capture_output=True,timeout=45)
        if result.returncode:raise RuntimeError('intake CLI failed: '+operation)
        return json.loads(result.stdout)
    service=start();first_question=None
    try:
        # Three legitimate rounds exceed the infrastructure block breaker but
        # remain native human review, not false failures or a synthetic CEO run.
        for index in range(3):
            until(pending,service);question=pending()
            shown=cli('show','--task',brief_task.id)
            assert shown['request']==question and shown['kind']=='product_question'
            current=next(card for card in runtime.status()['cards'] if card['id']==brief_task.id)
            assert current['business_input']['request']==question
            if first_question:refused(lambda:reply(first_question,'answer'))
            else:first_question=question
            refused(lambda:reply(question,'approve'))
            reply(question,'answer')
        until(pending,service);first_brief=pending()
        refused(lambda:reply(first_question,'approve'))
        reply(first_brief,'changes')
        until(lambda:pending() and pending()!=first_brief,service);final_brief=pending()
        refused(lambda:reply(first_brief,'approve'))
        stop(service)
        # Inject a real persistence gap: approval is committed, but creation of
        # the dependent plan has not run. A fresh CLI must observe, not reapprove.
        with patch.object(runtime.intake,'_reconcile',side_effect=RuntimeError('qualification interruption after approval commit')):
            try:reply(final_brief,'approve')
            except RuntimeError:pass
            else:raise AssertionError('expected interruption was not injected')
        with kbc.connect_closing() as conn:
            assert kb.get_task(conn,brief_task.id).status=='done'
            assert not conn.execute("SELECT 1 FROM tasks WHERE json_extract(body,'$.kind')='plan'").fetchone()
        approval=cli('respond','--task',brief_task.id,'--expect',final_brief,'--decision','approve',
            '--text','Approve this exact business scope only');assert not approval['delivery_approval']
        runtime.intake.respond(brief_task.id,final_brief,'approve','Idempotent operator repeat')
        with kbc.connect_closing() as conn:
            plans=conn.execute("SELECT COUNT(*) FROM tasks WHERE json_extract(body,'$.kind')='plan'").fetchone()[0]
            assert plans==1
            assert conn.execute('SELECT 1 FROM task_links WHERE parent_id=? AND child_id=?',
                                (brief_task.id,task('plan').id)).fetchone()
        service=start();until(lambda:task('plan').status=='done',service)
        def dead():
            with kbc.connect_closing() as conn:
                return all(row['ended_at'] and not worker_alive(recorded_worker(conn,row)) for row in conn.execute('SELECT * FROM task_runs')
                           if row['profile']!=HUMAN_REVIEWER)
        until(dead,service);stop(service)
        with kbc.connect_closing() as conn:
            rows=[dict(row) for row in conn.execute('SELECT * FROM task_runs ORDER BY id')]
            anchor=kb.get_task(conn,initial['release']);assert anchor.status=='blocked'
            assert not any(row['profile']==HUMAN_REVIEWER and row['outcome']!='completed' for row in rows)
            lead=task('plan');review=kb.latest_run(conn,lead.id)
            receipt=runtime.store.receipt(review.metadata['plan_review'],kind='plan_review')
            assert receipt['payload']['verdict']['decision']=='approve'
            assert receipt['binding']['actor']=='intake-cto'
            assert receipt['binding']['author']=='intake-lead'
        # Every model/SDK activity has a persisted session and tool result.
        activities=[json.loads((root/'runs'/str(number)/'activity.json').read_bytes()) for number in requests]
        assert len(activities)==9 and counters==dict(product=5,lead=2,cto=2)
        product=[item['result'] for item in activities if item['binding']['kind']=='brief']
        assert len({item['session'] for item in product})==1 and sum(item['resumed'] for item in product)==4
        assert not list((runtime.store.root/'agents').glob('*/sandbox.json'))
        runtime.pause()
        result=dict(passed=True,product_questions=3,business_change_request=True,stale_approval_refused=True,
            independent_plan_changes=True,complete_coverage_gate=True,plan_revisions=2,
            native_sdk_activities=len(activities),local_http_requests=len(all_requests),
            same_product_session_resumed=True,duplicate_plan_refused=True,release_anchor=anchor.status,
            approval_creation_gap_recovered=True,
            paid_calls=0,real_model_judgment=False,docker_jobs=0,work_graph_materialized=False,
            delivery_approval=False,migration=False)
        if relay:
            from fabriquinha.provider import inspect,Held
            endpoint='http://127.0.0.1:'+str(port)
            status=inspect(policy,endpoint,runtime.project.fingerprint())
            assert status['calls']==len(all_requests)==10
            assert all(request.get('max_tokens')==policy.max_output_tokens for request in all_requests)
            relay.ledger.pause(status['calls'],402)
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
            connection.request('POST','/v1/chat/completions',json.dumps(dict(model=model,messages=[dict(role='user',content='Must not reach the fixture')])),
                {'Authorization':'Bearer '+client_key,'Content-Type':'application/json'})
            response=connection.getresponse();assert response.status==402;response.read();connection.close()
            try:inspect(policy,endpoint,runtime.project.fingerprint())
            except Held as error:assert error.status==402
            else:raise AssertionError('metadata admission bypassed the financial pause')
            assert relay.status()['calls']==10 and len(all_requests)==10
            result.update(neutral_relay=True,relay_calls=10,paused_request_not_forwarded=True,
                sdk_output_budget_aligned=True,plan_schema_constraints_observed=True,legacy_adapters=0)
        write_json(root/'receipt.json',result);return result
    finally:
        if relay_server:
            relay_server.shutdown();relay_server.server_close();relay_thread.join(timeout=5)
        if relay_owner:relay_owner.__exit__(None,None,None)
        server.shutdown();server.server_close();thread.join(timeout=5)
        # A failure does not kill unknown/live workers: the recorded pause is
        # reconciled by the current service, and evidence is never approved.
        for running in services:
            if running.poll() is None:
                runtime.pause()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--image',required=True);parser.add_argument('--neutral-relay',action='store_true');args=parser.parse_args()
    try:print(json.dumps(qualify(args.root.resolve(),args.upstream.resolve(),args.image,neutral_relay=args.neutral_relay),indent=2))
    except BaseException as error:
        write_json(args.root/'failure.json',dict(category=type(error).__name__,message=str(error)[:2000],delivery_approval=False))
        raise
