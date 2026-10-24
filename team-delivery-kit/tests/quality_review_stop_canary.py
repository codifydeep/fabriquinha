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
scale_summaries=[];scale_reads=set();outside_recommendations=[];mixed_offset_batches=[]


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
        if scenario=='scale' and body['model']=='fixture-summary':
            scale_summaries.append(True)
            if len(scale_summaries)>4:
                self.send_response(400);self.end_headers();return
            return self.respond(body,dict(role='assistant',content=(
                'Historical synthetic review: continue inspecting the remaining registered pages. '
                'No tests or delivery have been approved. Follow the original operator fixture '
                'and the controller notices for exact pending paths and offsets.')),'stop','summary')
        index=len(calls);calls.append(dict(stream=bool(body.get('stream')),messages=len(body.get('messages',[]))))
        maximum=7 if scenario=='scale' else 1 if scenario=='budget' else 4 if scenario=='normal' else 3
        if index>=maximum:
            self.send_response(400);self.end_headers();self.wfile.write(b'{"error":"fixed fixture call ceiling"}');return
        if scenario=='normal' and index==1:
            assert body.get('tool_choice')=='auto'
            assert body.get('response_format')==dict(type='json_object')
        elif scenario=='normal' and index==2:
            assert body.get('tool_choice')==dict(type='function',function=dict(name='read_file')),body.get('tool_choice')
            assert [t['function']['name'] for t in body.get('tools',[])]==['read_file']
            assert body.get('parallel_tool_calls') is True
            assert any(m.get('role')=='system' and 'controller_review_continuation_v1' in str(m.get('content'))
                for m in body.get('messages',[]))
        elif scenario=='normal' and index==3:
            assert body.get('tool_choice')=='none' and body.get('response_format')==dict(type='json_object')
            assert not body.get('tools') and not body.get('parallel_tool_calls')
        message=dict(role='assistant',content=('Premature approval\n'+verdict) if index==0 else verdict)
        finish='stop'
        if scenario=='normal' and index in (0,2):
            assert body.get('response_format')==(dict(type='json_object') if index==0 else None)
            chosen=['tests/test_new.py'] if index==0 else ['app.py']
            message=dict(role='assistant',content=None,tool_calls=[dict(id='read-'+str(i),type='function',
                function=dict(name='read_file',arguments=json.dumps(dict(path='/delivery/'+p,offset=1,limit=100))))
                for i,p in enumerate(chosen,index)])
            finish='tool_calls'
        elif scenario=='normal' and index==1:
            message=dict(role='assistant',content='I read the new tests. I will read the remaining app file in a later turn.')
        elif (scenario=='stall' and index>0) or scenario=='budget':
            args=(dict(path='/delivery/app.py',offset=401,limit=100) if scenario=='stall' else
                dict(path='/delivery/tests/test_new.py',offset=1,limit=1))
            message=dict(role='assistant',content=None,tool_calls=[dict(id='control-'+str(index),type='function',
                function=dict(name='read_file',arguments=json.dumps(args)))])
            finish='tool_calls'
        elif scenario=='scale':
            notices=[m['content'] for m in body['messages'] if m.get('role')=='system'
                and 'controller_review_continuation_v1' in str(m.get('content'))]
            assert len(notices)==1
            note=json.loads(notices[0][notices[0].index('{'):])
            assert note['request_id']=='60000000-0000-4000-8000-000000000005'
            assert note['phase_contract']['phase']=='immutable_test_revision_review_v2'
            assert note['phase_contract']['approval_scope']=='exact_test_revision_only'
            assert note['phase_contract']['downstream_gates']==['implementation_green','negative_controls',
                'independent_delivery_review','product_pr_ci','same_commit_deploy_qa_rollback']
            assert 'not prerequisites' in notices[0] and 'Do not invent an additional CTO approval' in notices[0]
            assert note['verdict_contract']['criteria']==['A01']
            assert all(note['verdict_contract'][key]==config_value for key,config_value in
                json.loads(verdict).items() if key in ('manifest_sha256','plan_sha256','red_sha256'))
            if note['remaining_files']:
                assert body.get('tool_choice')=='auto'
                assert body.get('response_format')==dict(type='json_object')
                # Reproduce a real model's large parallel batch, not the
                # smaller recommended cohort that hid aggregate spill.
                pages=note['pending_reads'][:64];assert 1<=len(pages)<=64
                outside_recommendations.extend(page for page in pages if page not in note['next_reads'])
                if len({page['offset'] for page in pages})>1:mixed_offset_batches.append(True)
                schema=body['tools'][0]['function']['parameters']['properties']
                assert schema['path']['enum']==list(dict.fromkeys(p['path'] for p in note['pending_reads']))
                assert schema['offset']['enum']==sorted({p['offset'] for p in note['pending_reads']}) and schema['limit']['enum']==[100]
                for page in pages:
                    key=(page['path'],page['offset'],page['limit'])
                    assert key not in scale_reads
                    assert 1<=page['offset']<=len(scale_files_data[page['path'].removeprefix('/delivery/')].splitlines())
                    scale_reads.add(key)
                message=dict(role='assistant',content=None,tool_calls=[dict(id=f'scale-{index}-{n}',type='function',
                    function=dict(name='read_file',arguments=json.dumps(page))) for n,page in enumerate(pages)])
                finish='tool_calls'
            else:
                assert note['complete_files']==71
                assert body.get('tool_choice')=='none' and body.get('response_format')==dict(type='json_object')
                assert not body.get('tools') and not body.get('parallel_tool_calls')
                if index==5:
                    # Syntactically valid JSON is still not a valid review.
                    # The real local guard must reject it, preserve it, and
                    # give specific feedback after a REAL context compression.
                    bad={**json.loads(verdict),'action':'request_changes','reason':
                        'Fixed invalid control: require Green and negative controls before test review.'}
                    message=dict(role='assistant',content=json.dumps(bad))
                else:
                    assert index==6
                    assert note['verdict_rejection']=='changes_require_concrete_findings'
        return self.respond(body,message,finish,index)

    def respond(self,body,message,finish,index):
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
assert len(calls)==4,calls
notes=[json.loads(s.split(':',1)[1]) for s in audit if s.startswith('QUALITY_REVIEW_COMPLETION_ATTEMPT_V1:')]
print(json.dumps(dict(stage='fixed_probe_observed',fixed_calls=calls,auxiliary=auxiliary,
    audit_notes=len(notes),acp=acp_mode,agent_text_chunks=len(text_chunks))))
assert len(notes)==1 and notes[0]['diagnostic']['remaining_files']==1 and not notes[0]['diagnostic']['blocked'],notes
assert notes[0]['diagnostic']['remaining_iterations']==38,notes
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
    request=dict(messages=[],tools=[dict(type='function',function=dict(name='read_file',parameters=dict(type='object')))])
    stop.apply_request(probe_agent,request,[],40)
    assert not hasattr(probe_agent,'_quality_review_completion')
    args=dict(path='/delivery/app.py',offset=1,limit=100)
    denied=json.loads(registry.get_entry('read_file').handler({**args,'offset':401}))
    assert denied.get('error','').startswith('review_page_not_pending:'),denied
    read=json.loads(registry.dispatch('read_file',args))
    assert not read.get('error') and read.get('content_returned') is not False,read
    repeated=json.loads(registry.get_entry('read_file').handler(args))
    assert repeated.get('error','').startswith('review_page_not_pending:'),repeated
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


def scale_compaction_control():
    """Real read handlers, real summarizer and real compression commit.

    The fixture changes only trigger parameters and supplies a fixed local
    summary response. It does not replace the compression algorithm or create
    read receipts. Production code and its 40-iteration budget are unchanged.
    """
    global calls,scenario,verdict,scale_files_data
    from run_agent import AIAgent
    import quality_review_stop as stop
    from review_execution_evidence import scale_files
    import agent.tool_executor as executor
    from tools.budget_config import BudgetConfig,budget_for_context_window
    from tools.tool_result_storage import enforce_turn_budget,PERSISTED_OUTPUT_TAG
    from quality_review_paging import MAX_BYTES
    scale_files_data=scale_files()
    assert all((Path('/delivery')/p).read_bytes()==raw for p,raw in scale_files_data.items())
    inv={p:dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw)) for p,raw in scale_files_data.items()}
    packet=dict(manifest_sha256=hashlib.sha256(json.dumps({'files':inv},sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        plan_sha256='a'*64,red_sha256='b'*64,plan=dict(criteria=['A01'],new_tests=['scale/file-000.py']))
    case=dict(version=2,phase='test_review_v2',request_id='60000000-0000-4000-8000-000000000005',
        editable_paths=[],read_paths=['/delivery/'+p for p in inv],review_context=dict(packet=packet,files=inv))
    verdict=json.dumps(dict(action='approve_tests',reason='Fixed scale fixture only',criteria=['A01'],findings=[],
        **{k:packet[k] for k in ('manifest_sha256','plan_sha256','red_sha256')}))
    os.environ.update(DELIVERY_QUALITY_PHASE_JSON=json.dumps(case),DELIVERY_MODEL_EXECUTION_ID=case['request_id'])
    scenario='scale';calls=[]
    local=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=local.serve_forever,daemon=True).start()
    commits=[];triggered=[];transport=[]
    original_budget_enforcer=executor.enforce_turn_budget
    legacy=[dict(role='tool',tool_call_id='fixed-legacy-budget',content='x'*210000)]
    enforce_turn_budget(legacy,config=BudgetConfig())
    assert PERSISTED_OUTPUT_TAG in legacy[0]['content']  # Real upstream counter-control.
    def observe_budget(messages,*args,**kwargs):
        before=sum(len(m.get('content','')) for m in messages)
        result=original_budget_enforcer(messages,*args,**kwargs)
        transport.append(dict(chars=before,count=len(result),
            spills=sum(PERSISTED_OUTPUT_TAG in m.get('content','') for m in result)))
        return result
    executor.enforce_turn_budget=observe_budget
    try:
        # The auxiliary resolver reads task configuration independently from
        # AIAgent's explicit base_url. Never inherit the earlier closed server.
        import yaml
        endpoint=f'http://127.0.0.1:{local.server_port}/v1'
        settings=yaml.safe_load((home/'config.yaml').read_text())
        settings.setdefault('model',{})['base_url']=endpoint
        settings.setdefault('auxiliary',{})['compression']=dict(provider='openai',
            model='fixture-summary',base_url=endpoint,key_env='OPENAI_API_KEY')
        (home/'config.yaml').write_text(yaml.safe_dump(settings))
        os.environ['OPENAI_BASE_URL']=endpoint
        current=AIAgent(model='anthropic/claude-haiku-5.5',provider='openai',api_mode='chat_completions',
            base_url=endpoint,api_key='offline-not-a-credential',
            max_iterations=40,enabled_toolsets=['hermes-acp'],quiet_mode=True,max_tokens=8192,
            checkpoints_enabled=False)
        actual_budget=executor._budget_for_agent(current)
        base_budget=budget_for_context_window(current.context_compressor.context_length)
        from dataclasses import replace
        assert actual_budget.turn_budget==MAX_BYTES
        assert replace(actual_budget,turn_budget=base_budget.turn_budget)==base_budget
        compressor=current.context_compressor
        compressor.protect_first_n=1;compressor.protect_last_n=2
        compressor.summary_model='fixture-summary'
        current.compression_enabled=True
        original_should=compressor.should_compress
        original_compress=current._compress_context
        def should_compress(prompt_tokens=None):
            journal=getattr(current,'_quality_review_journal',None)
            if not triggered and journal is not None and len(journal.messages())>=64:return True
            return original_should(prompt_tokens)
        def compress(messages,system_message,**kwargs):
            before=len(stop.pairs(messages))
            if not triggered:kwargs['force']=True
            triggered.append(True)
            updated,system=original_compress(messages,system_message,**kwargs)
            after=len(stop.pairs(updated))
            assert 1<=len(triggered)<=4 and after<before,(before,after)
            assert not getattr(compressor,'_last_summary_error',None)
            assert len(current._quality_review_journal.messages())>=before
            commits.append((before-after)//2)
            return updated,system
        compressor.should_compress=should_compress
        current._compress_context=compress
        result=current.run_conversation('Fixed operator scale fixture. Review all registered pages; do not authorize any native delivery.')
    finally:
        executor.enforce_turn_budget=original_budget_enforcer
        local.shutdown();local.server_close()
    assert result['final_response']==verdict,result
    assert len(calls)==7 and 1<=len(scale_summaries)<=4 and len(scale_reads)==219,(calls,scale_summaries,len(scale_reads))
    assert outside_recommendations and mixed_offset_batches
    completed=current._quality_review_completion
    assert completed['attempts']==1 and not completed['blocked']
    rejected=json.loads(completed['candidate'])
    assert rejected['action']=='request_changes' and rejected['findings']==[]
    assert len(commits)==len(scale_summaries)==compressor.compression_count and all(n>0 for n in commits),commits
    assert current._quality_review_journal.plan()['complete_files']==71
    largest=max(p['chars'] for p in transport)
    assert 200000<largest<=MAX_BYTES and sum(p['count'] for p in transport)==219,transport
    assert all(p['spills']==0 for p in transport),transport
    assert all((Path('/delivery')/p).read_bytes()==raw for p,raw in scale_files_data.items())
    return dict(operation='real_hermes_review_scale_compaction_v1',files=71,pages=len(scale_reads),
        main_provider_calls=len(calls),summary_provider_calls=len(scale_summaries),max_iterations=40,
        complete_files=71,compactions=compressor.compression_count,dropped_read_pairs=sum(commits),
        duplicate_reads=0,eof_reads=0,tool_only_from_first_call=True,
        out_of_recommended_reads=len(outside_recommendations),mixed_offset_batches=len(mixed_offset_batches),
        largest_batch_chars=largest,legacy_turn_budget_chars=200000,
        review_turn_budget_chars=MAX_BYTES,spill_previews=0,legacy_spill_observed=True,
        phase_contract_persisted=True,invalid_final_verdict_rejected=True,json_only_after_inspection=True,
        snapshot_unchanged=True,model_calls=0,tests_approved=False,delivery_approval=False)


normal_calls=list(calls)
controls=execution_controls()
scale=scale_compaction_control()
import quality_review_stop,quality_phase_tools,quality_review_verdict,quality_review_paging,review_tool_policy,quality_review_budget
guard_sources={key:hashlib.sha256(Path(path).read_bytes()).hexdigest() for key,path in {
    'feedback':quality_review_stop.__file__,'phase':quality_phase_tools.__file__,
    'verdict':quality_review_verdict.__file__,'installer':'/install_quality_review_stop.py',
    'paging':quality_review_paging.__file__,
    'budget':quality_review_budget.__file__,
    'handler':review_tool_policy.__file__,
    'loop':'/opt/hermes/agent/conversation_loop.py','acp':'/opt/hermes/acp_adapter/server.py',
    'session':'/opt/hermes/acp_adapter/session.py','executor':'/opt/hermes/agent/tool_executor.py'}.items()}
print(json.dumps(dict(operation='real_hermes_review_stop_loop_canary_v1',status='passed',
    provider='fixed_loopback_not_model',model_calls=0,fixed_provider_calls=len(normal_calls),
    premature_after_tests_forced_read=True,
    total_fixed_provider_calls=len(normal_calls)+controls['stall']['provider_calls']+controls['budget']['provider_calls']
        +scale['main_provider_calls']+scale['summary_provider_calls'],
    execution_controls=controls,scale_controls=scale,
    fixture_source_sha256=hashlib.sha256(Path('/review_execution_evidence.py').read_bytes()).hexdigest(),
    feedback_rounds=len(notes),same_agent=True,max_iterations=40,acp=acp_mode,
    protected_files_unchanged=True,guard_sources=guard_sources,tests_approved=False,delivery_approval=False)))
