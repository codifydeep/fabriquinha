"""Real Hermes loop + handlers, FIXED loopback replies, never native approval.

Run only in an owned --rm/none-network/read-only worker with the exact synthetic
two-file fixture mounted RO at /delivery. No model/provider credentials needed.
"""
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import subprocess
import queue
import time

sys.path[:0]=['/opt/hermes','/']
FILES={'app.py':b'VALUE=0\n','tests/test_new.py':b'def test_new():\n    assert False\n'}
assert all((Path('/delivery')/p).read_bytes()==raw for p,raw in FILES.items())
assert not Path('/var/run/docker.sock').exists()
inventory={p:dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw)) for p,raw in FILES.items()}
packet=dict(manifest_sha256=hashlib.sha256(json.dumps({'files':inventory},sort_keys=True,separators=(',',':')).encode()).hexdigest(),
    plan_sha256='a'*64,red_sha256='b'*64,plan=dict(criteria=['A01'],new_tests=['tests/test_new.py']))
config=dict(version=2,phase='test_review_v2',request_id='60000000-0000-4000-8000-000000000001',editable_paths=[],
    read_paths=['/delivery/'+p for p in FILES],review_context=dict(packet=packet,files=inventory))
os.environ.update(DELIVERY_QUALITY_PHASE_JSON=json.dumps(config),DELIVERY_EXECUTION_MODE='review',
    DELIVERY_MODEL_EXECUTION_ID=config['request_id'],HERMES_HOME='/tmp/hermes',HOME='/tmp')
home=Path('/tmp/hermes');home.mkdir(exist_ok=True)
(home/'config.yaml').write_text('memory:\n  nudge_interval: 0\nskills:\n  creation_nudge_interval: 0\nauxiliary:\n  title_generation:\n    enabled: false\n')
verdict=json.dumps(dict(action='approve_tests',reason='Fixed offline fixture only',criteria=['A01'],findings=[],
    **{k:packet[k] for k in ('manifest_sha256','plan_sha256','red_sha256')}))
calls=[];auxiliary=[]
scenario='normal'


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
        self.wfile.write(b'{"data":[]}')
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if not self.path.endswith('/chat/completions') or not body.get('model'):
            auxiliary.append(dict(path=self.path,keys=sorted(body)))
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(b'{}');return
        index=len(calls);calls.append(dict(stream=bool(body.get('stream')),messages=len(body.get('messages',[]))))
        maximum=1 if scenario=='budget' else 3
        if index>=maximum:
            self.send_response(400);self.end_headers();self.wfile.write(b'{"error":"fixed fixture call ceiling"}');return
        if scenario=='normal' and index==1:
            assert body.get('tool_choice')==dict(type='function',function=dict(name='read_file')),body.get('tool_choice')
            assert [t['function']['name'] for t in body.get('tools',[])]==['read_file']
            assert body.get('parallel_tool_calls') is True
            assert any(m.get('role')=='system' and 'controller_review_continuation_v1' in str(m.get('content'))
                for m in body.get('messages',[]))
        elif scenario=='normal' and index==2:
            assert body.get('tool_choice')!=dict(type='function',function=dict(name='read_file'))
        message=dict(role='assistant',content=('Premature approval\n'+verdict) if index==0 else verdict)
        finish='stop'
        if scenario=='normal' and index==1:
            message=dict(role='assistant',content=None,tool_calls=[dict(id='read-'+str(i),type='function',
                function=dict(name='read_file',arguments=json.dumps(dict(path='/delivery/'+p,offset=1,limit=100))))
                for i,p in enumerate(FILES)])
            finish='tool_calls'
        elif (scenario=='stall' and index>0) or scenario=='budget':
            args=(dict(path='/delivery/app.py',offset=401,limit=100) if scenario=='stall' else
                dict(path='/delivery/tests/test_new.py',offset=1,limit=1))
            message=dict(role='assistant',content=None,tool_calls=[dict(id='control-'+str(index),type='function',
                function=dict(name='read_file',arguments=json.dumps(args)))])
            finish='tool_calls'
        stream=bool(body.get('stream'));kind='text/event-stream' if stream else 'application/json'
        self.send_response(200);self.send_header('Content-Type',kind);self.end_headers()
        common=dict(id='fixed-'+str(index),created=0,model=body['model'])
        if stream:
            delta=dict(message)
            if 'tool_calls' in delta:delta['tool_calls']=[{**c,'index':i} for i,c in enumerate(delta['tool_calls'])]
            for chunk in (dict(**common,object='chat.completion.chunk',choices=[dict(index=0,delta=delta,finish_reason=None)]),
                    dict(**common,object='chat.completion.chunk',choices=[dict(index=0,delta={},finish_reason=finish)])):
                self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        else:
            self.wfile.write(json.dumps(dict(**common,object='chat.completion',choices=[dict(index=0,message=message,finish_reason=finish)],
                usage=dict(prompt_tokens=10,completion_tokens=10,total_tokens=20))).encode())


server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
audit=[]
acp_mode=os.environ.get('REVIEW_STOP_CANARY_ACP')=='1'
text_chunks=[]
try:
    prompt='Fixed operator canary, NOT native test approval. Review the two registered fixture files. Return the exact registered JSON verdict.'
    if acp_mode:
        os.environ.update(OPENAI_API_KEY='offline-not-a-credential',OPENAI_BASE_URL=f'http://127.0.0.1:{server.server_port}/v1')
        with (home/'config.yaml').open('a') as config_file:
            config_file.write(f'model:\n  provider: openai\n  default: anthropic/claude-haiku-5.5\n  base_url: http://127.0.0.1:{server.server_port}/v1\n')
        child=subprocess.Popen(['hermes','acp'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,bufsize=1,cwd='/delivery')
        incoming=queue.Queue();errors=[]
        def reader():
            for line in child.stdout:incoming.put(line)
            incoming.put(None)
        def stderr():
            for line in child.stderr:
                errors.append(line)
                if len(errors)>30:errors.pop(0)
        threading.Thread(target=reader,daemon=True).start();threading.Thread(target=stderr,daemon=True).start()
        notifications=[]
        def exchange(identifier,method,params):
            child.stdin.write(json.dumps(dict(jsonrpc='2.0',id=identifier,method=method,params=params))+'\n');child.stdin.flush()
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                line=incoming.get(timeout=max(.01,deadline-time.monotonic()))
                assert line is not None,errors
                frame=json.loads(line)
                if frame.get('id')==identifier:
                    assert 'error' not in frame,frame
                    return frame['result']
                notifications.append(frame)
            raise TimeoutError('same canary ACP response')
        try:
            exchange(1,'initialize',dict(protocolVersion=1,clientCapabilities={},clientInfo=dict(name='fixed-canary',version='1')))
            created=exchange(2,'session/new',dict(cwd='/delivery',mcpServers=[]))
            exchange(3,'session/prompt',dict(sessionId=created['sessionId'],prompt=[dict(type='text',text=prompt)]))
        finally:
            child.terminate();child.wait(timeout=10)
        for frame in notifications:
            update=(frame.get('params') or {}).get('update') or {};content=update.get('content') or {}
            if update.get('sessionUpdate')=='agent_message_chunk':text_chunks.append(content.get('text',''))
            elif update.get('sessionUpdate')=='agent_thought_chunk':audit.append(content.get('text',''))
        result=dict(final_response=''.join(text_chunks))
    else:
        from run_agent import AIAgent
        agent=AIAgent(model='anthropic/claude-haiku-5.5',provider='openai',api_mode='chat_completions',
            base_url=f'http://127.0.0.1:{server.server_port}/v1',api_key='offline-not-a-credential',
            max_iterations=40,enabled_toolsets=['hermes-acp'],quiet_mode=True,max_tokens=2048,
            reasoning_callback=audit.append,checkpoints_enabled=False)
        result=agent.run_conversation(prompt)
finally:server.shutdown();server.server_close()
assert result['final_response']==verdict,result.get('final_response')
assert len(calls)==3,calls
notes=[json.loads(s.split(':',1)[1]) for s in audit if s.startswith('QUALITY_REVIEW_COMPLETION_ATTEMPT_V1:')]
print(json.dumps(dict(stage='fixed_probe_observed',fixed_calls=calls,auxiliary=auxiliary,
    audit_notes=len(notes),acp=acp_mode,agent_text_chunks=len(text_chunks))))
assert len(notes)==1 and notes[0]['diagnostic']['remaining_files']==2 and not notes[0]['diagnostic']['blocked'],notes
assert notes[0]['diagnostic']['remaining_iterations']==39,notes
assert all((Path('/delivery')/p).read_bytes()==raw for p,raw in FILES.items())


def execution_controls():
    """Actual Hermes registry/loop, fixed local responses, never model calls."""
    global calls,scenario
    from types import SimpleNamespace
    import quality_review_stop as stop
    from tools.registry import registry,discover_builtin_tools
    from run_agent import AIAgent
    discover_builtin_tools()
    probe_config={**config,'request_id':'60000000-0000-4000-8000-000000000004'}
    os.environ.update(DELIVERY_QUALITY_PHASE_JSON=json.dumps(probe_config),DELIVERY_MODEL_EXECUTION_ID=probe_config['request_id'])
    probe_agent=SimpleNamespace()
    stop.guard(probe_agent,[],verdict,39)
    request=dict(messages=[],tools=[dict(type='function',function=dict(name='read_file',parameters=dict(type='object')))])
    stop.apply_request(probe_agent,request,[],38)
    args=dict(path='/delivery/app.py',offset=1,limit=100)
    read=json.loads(registry.dispatch('read_file',args))
    assert not read.get('error') and read.get('content_returned') is not False,read
    repeated=json.loads(registry.get_entry('read_file').handler(args))
    assert repeated.get('error')=='operation_forbidden_in_test_review_v2',repeated
    results={}
    for mode,request_id,iterations in [('stall','60000000-0000-4000-8000-000000000002',40),
            ('budget','60000000-0000-4000-8000-000000000003',1)]:
        scenario=mode;calls=[]
        case={**config,'request_id':request_id}
        os.environ.update(DELIVERY_QUALITY_PHASE_JSON=json.dumps(case),DELIVERY_MODEL_EXECUTION_ID=request_id)
        local=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=local.serve_forever,daemon=True).start()
        try:
            current=AIAgent(model='anthropic/claude-haiku-5.5',provider='openai',api_mode='chat_completions',
                base_url=f'http://127.0.0.1:{local.server_port}/v1',api_key='offline-not-a-credential',
                max_iterations=iterations,enabled_toolsets=['hermes-acp'],quiet_mode=True,max_tokens=2048,
                checkpoints_enabled=False)
            result=current.run_conversation('Fixed operator execution-stop control, not a native task or approval.')
        finally:local.shutdown();local.server_close()
        observed=json.loads(result['final_response'])
        expected='read_progress_stalled' if mode=='stall' else 'iteration_budget_exhausted'
        assert observed['operation']=='advisory_review_execution_v1' and observed['category']==expected,observed
        assert observed['blocked'] and observed['tests_approved'] is False and observed['delivery_approval'] is False
        assert len(calls)==(3 if mode=='stall' else 1),calls
        results[mode]=dict(provider_calls=len(calls),category=expected,fixture_iterations=iterations)
    assert all((Path('/delivery')/p).read_bytes()==raw for p,raw in FILES.items())
    return dict(operation='real_hermes_review_execution_controls_v1',**results,
        preflight_then_dispatch=True,direct_duplicate_denied=True,snapshot_unchanged=True,model_calls=0)


normal_calls=list(calls)
controls=execution_controls()
import quality_review_stop,quality_phase_tools,quality_review_verdict,quality_review_paging,review_tool_policy
guard_sources={key:hashlib.sha256(Path(path).read_bytes()).hexdigest() for key,path in {
    'feedback':quality_review_stop.__file__,'phase':quality_phase_tools.__file__,
    'verdict':quality_review_verdict.__file__,'installer':'/install_quality_review_stop.py',
    'paging':quality_review_paging.__file__,
    'handler':review_tool_policy.__file__,
    'loop':'/opt/hermes/agent/conversation_loop.py','acp':'/opt/hermes/acp_adapter/server.py',
    'session':'/opt/hermes/acp_adapter/session.py'}.items()}
print(json.dumps(dict(operation='real_hermes_review_stop_loop_canary_v1',status='passed',
    provider='fixed_loopback_not_model',model_calls=0,fixed_provider_calls=len(normal_calls),
    total_fixed_provider_calls=len(normal_calls)+controls['stall']['provider_calls']+controls['budget']['provider_calls'],
    execution_controls=controls,
    feedback_rounds=len(notes),same_agent=True,max_iterations=40,acp=acp_mode,
    protected_files_unchanged=True,guard_sources=guard_sources,tests_approved=False,delivery_approval=False)))
