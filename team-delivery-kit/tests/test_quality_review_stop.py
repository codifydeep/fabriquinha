"""Advisory loop feedback; synthetic messages never qualify a native review."""
import copy
import hashlib
import json
import os
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import quality_phase_tools as phase
import quality_review_stop as stop
from install_quality_review_stop import (adapt_loop,adapt_acp,adapt_session,adapt_request,
    LOOP_ANCHOR,STREAM_ANCHOR,SESSION_ANCHOR,REQUEST_ANCHOR)
from broker import quality_review_completion_receipts as receipts


class QualityReviewStopTests(unittest.TestCase):
    def setUp(self):
        self.files={'app.py':b'VALUE=0\n','tests/test_new.py':b'one\ntwo\nthree\n'}
        inventory={p:dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw)) for p,raw in self.files.items()}
        packet=dict(manifest_sha256=hashlib.sha256(json.dumps({'files':inventory},sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            plan_sha256='a'*64,red_sha256='b'*64,plan=dict(criteria=['A01'],new_tests=['tests/test_new.py']))
        self.request='60000000-0000-4000-8000-000000000001'
        self.config=dict(version=2,phase='test_review_v2',request_id=self.request,editable_paths=[],
            read_paths=['/delivery/'+p for p in self.files],review_context=dict(packet=packet,files=inventory))
        self.env={phase.KEY:json.dumps(self.config),'DELIVERY_EXECUTION_MODE':'review',
            'DELIVERY_MODEL_EXECUTION_ID':self.request}
        self.verdict=dict(action='approve_tests',reason='Fixture review',criteria=['A01'],findings=[],
            **{k:packet[k] for k in ('manifest_sha256','plan_sha256','red_sha256')})

    def page(self,path,key,offset,total,content):
        return [dict(role='assistant',content=None,tool_calls=[dict(id=key,type='function',
            function=dict(name='read_file',arguments=json.dumps(dict(path='/delivery/'+path,offset=offset,limit=100))))]),
            dict(role='tool',tool_call_id=key,content=json.dumps(dict(content=content,total_lines=total)))]

    def messages(self):
        return self.page('app.py','a',1,1,'1|VALUE=0')+self.page('tests/test_new.py','b',1,3,'1|one\n2|two')+self.page('tests/test_new.py','c',3,3,'3|three')

    def test_complete_exact_reads_and_strict_verdict_need_no_feedback_or_authority(self):
        agent=SimpleNamespace()
        self.assertIsNone(stop.guard(agent,self.messages(),json.dumps(self.verdict),39,self.env))
        self.assertFalse(hasattr(agent,'_quality_review_completion'))

    def test_format_and_partial_read_are_both_reported_with_next_missing_page(self):
        result=stop.guard(SimpleNamespace(),self.messages()[:-2],'Explanation\n'+json.dumps(self.verdict),39,self.env)
        self.assertEqual(result['verdict_format'],'invalid');self.assertEqual(result['remaining_files'],1)
        self.assertEqual(result['next_reads'],[dict(path='/delivery/tests/test_new.py',offset=3,limit=100)])
        self.assertFalse(result['blocked']);self.assertFalse(result['tests_approved'])

    def test_two_stalls_stop_even_when_prose_changes(self):
        agent=SimpleNamespace()
        first=stop.guard(agent,[],json.dumps(self.verdict),39,self.env)
        second=stop.guard(agent,[dict(role='assistant',content='I read all files')],json.dumps({**self.verdict,'reason':'Another prose claim'}),38,self.env)
        self.assertEqual(first['progress_sha256'],second['progress_sha256'])
        self.assertTrue(second['blocked']);self.assertEqual(second['repeated_without_progress'],2)
        self.assertIn('CTO',second['next_action'])

    def api_request(self):
        return dict(model='fixture',messages=[dict(role='user',content='review')],tool_choice='auto',
            tools=[dict(type='function',function=dict(name='read_file',parameters=dict(type='object'))),
                dict(type='function',function=dict(name='terminal',parameters=dict(type='object')))])

    def test_first_request_plans_and_fences_reads_without_a_premature_answer(self):
        agent=SimpleNamespace();request=self.api_request();before=copy.deepcopy(request)
        result=stop.apply_request(agent,request,[],40,self.env)
        self.assertEqual(request,before)
        self.assertFalse(hasattr(agent,'_quality_review_completion'))
        self.assertEqual(result['tool_choice'],'auto')
        self.assertEqual([t['function']['name'] for t in result['tools']],['read_file'])
        paths=result['tools'][0]['function']['parameters']['properties']['path']['enum']
        self.assertEqual(paths,['/delivery/tests/test_new.py','/delivery/app.py'])
        self.assertIn('controller_review_continuation_v1',result['messages'][0]['content'])
        self.assertNotIn('previous answer',result['messages'][0]['content'])
        import quality_review_paging as paging
        allowed=dict(path=paths[0],offset=1,limit=100)
        self.assertTrue(paging.allowed(self.config,allowed))
        self.assertFalse(paging.allowed(self.config,{**allowed,'offset':401}))
        self.assertTrue(paging.allowed(self.config,allowed,consume=True))
        self.assertFalse(paging.allowed(self.config,allowed,consume=True))

    def test_tool_only_progress_survives_context_drop_before_any_final_answer(self):
        agent=SimpleNamespace();request=self.api_request()
        stop.apply_request(agent,request,[],40,self.env)
        stop.checkpoint(agent,self.messages()[2:4],39,after_tools=True,environment=self.env)
        result=stop.apply_request(agent,request,[],39,self.env)
        props=result['tools'][0]['function']['parameters']['properties']
        self.assertEqual(props['path']['enum'],['/delivery/tests/test_new.py'])
        self.assertEqual(props['offset']['enum'],[3])
        self.assertFalse(hasattr(agent,'_quality_review_completion'))
        stop.checkpoint(agent,self.messages()[4:],38,after_tools=True,environment=self.env)
        result=stop.apply_request(agent,request,[],38,self.env)
        self.assertEqual(result['tool_choice'],'auto')
        self.assertIn('/delivery/app.py',result['messages'][0]['content'])
        self.assertNotIn('snapshot_read_evidence_invalid',result['messages'][0]['content'])

    def test_early_rejection_remains_available_after_initial_premature_approval(self):
        agent=SimpleNamespace();request=self.api_request()
        stop.apply_request(agent,request,[],40,self.env)
        stop.guard(agent,[],json.dumps(self.verdict),39,self.env)
        result=stop.apply_request(agent,request,self.messages()[2:],38,self.env)
        self.assertEqual(result['tool_choice'],'auto')
        choice={**self.verdict,'action':'request_changes','findings':[dict(path='tests/test_new.py')]}
        self.assertIsNone(stop.guard(agent,[],json.dumps(choice),38,self.env))
        # Same reads never suffice for approval of the full snapshot.
        incomplete=stop.guard(agent,[],json.dumps(self.verdict),37,self.env)
        self.assertIsNotNone(incomplete);self.assertEqual(incomplete['remaining_files'],1)

    def test_premature_stop_requires_real_read_tool_without_expanding_its_schema(self):
        agent=SimpleNamespace();request=self.api_request();before=copy.deepcopy(request)
        stop.guard(agent,self.messages()[:-2],json.dumps(self.verdict),36,self.env)
        result=stop.apply_request(agent,request,self.messages()[:-2],35,self.env)
        self.assertEqual(request,before)
        self.assertEqual(result['tools'][0]['function']['name'],'read_file')
        self.assertEqual(result['tools'][0]['function']['parameters']['properties']['offset']['enum'],[3])
        self.assertEqual(result['tool_choice'],dict(type='function',function=dict(name='read_file')))
        self.assertTrue(result['parallel_tool_calls'])
        note=result['messages'][0];self.assertEqual(note['role'],'system')
        self.assertIn('file count is not iteration count',note['content'])
        self.assertIn('"offset": 3',note['content']);self.assertIn('"remaining_iterations": 35',note['content'])
        self.assertFalse(agent._quality_review_completion['blocked'])

    def test_completion_policy_never_fakes_reads_or_approves_after_inspection(self):
        agent=SimpleNamespace();request=self.api_request()
        first=stop.apply_request(agent,request,[],39,self.env)
        self.assertIsNot(first,request)
        self.assertEqual(first['tool_choice'],'auto')
        self.assertIn('"remaining_files": 2',first['messages'][0]['content'])
        self.assertFalse(agent._quality_review_journal.messages())
        stop.guard(agent,[],'not a verdict',38,self.env)
        completed=stop.apply_request(agent,request,self.messages(),37,self.env)
        self.assertEqual(completed['tools'],request['tools']);self.assertEqual(completed['tool_choice'],'auto')
        self.assertIn('no verdict has been accepted',completed['messages'][0]['content'])
        self.assertEqual(request['messages'],[dict(role='user',content='review')])
        self.assertIs(stop.apply_request(agent,request,[],39,{}),request)

    def test_changed_request_missing_registry_or_blocked_loop_never_sends_a_model_call(self):
        agent=SimpleNamespace();stop.guard(agent,[],json.dumps(self.verdict),39,self.env)
        for request in ({**self.api_request(),'tools':[]},
                {**self.api_request(),'tools':[self.api_request()['tools'][0]]*2},
                {**self.api_request(),'response_format':dict(type='json_object')}):
            with self.assertRaises(ValueError):stop.apply_request(agent,request,[],38,self.env)
        config=copy.deepcopy(self.config);config['request_id']=config['request_id'][:-1]+'2'
        env={**self.env,phase.KEY:json.dumps(config),'DELIVERY_MODEL_EXECUTION_ID':config['request_id']}
        with self.assertRaises(ValueError):stop.apply_request(agent,self.api_request(),[],38,env)
        stop.guard(agent,[],json.dumps(self.verdict),38,self.env)
        with self.assertRaises(ValueError):stop.apply_request(agent,self.api_request(),[],37,self.env)

    def test_request_changes_continuation_does_not_require_unrelated_approval_reads(self):
        agent=SimpleNamespace();choice={**self.verdict,'action':'request_changes','findings':[dict(path='tests/test_new.py')]}
        stop.guard(agent,[],json.dumps(choice),39,self.env)
        result=stop.apply_request(agent,self.api_request(),self.messages()[2:],38,self.env)
        self.assertEqual(result['tool_choice'],'auto')
        self.assertIn('"remaining_files": 0',result['messages'][0]['content'])

    def test_actual_new_page_is_progress_but_does_not_reset_original_budget(self):
        agent=SimpleNamespace()
        stop.guard(agent,[],json.dumps(self.verdict),39,self.env)
        progressed=stop.guard(agent,self.messages()[:2],json.dumps(self.verdict),38,self.env)
        self.assertEqual(progressed['repeated_without_progress'],1);self.assertFalse(progressed['blocked'])
        exhausted=stop.guard(agent,self.messages()[:-2],json.dumps(self.verdict),0,self.env)
        self.assertTrue(exhausted['blocked']);self.assertEqual(exhausted['attempt'],3)

    def test_partial_line_progress_prevents_false_stall_before_file_completion(self):
        agent=SimpleNamespace()
        first=stop.guard(agent,self.page('tests/test_new.py','b',1,3,'1|one'),json.dumps(self.verdict),39,self.env)
        second=stop.guard(agent,self.page('tests/test_new.py','c',2,3,'2|two'),json.dumps(self.verdict),38,self.env)
        self.assertNotEqual(first['progress_sha256'],second['progress_sha256'])
        self.assertEqual(second['repeated_without_progress'],1);self.assertFalse(second['blocked'])
        self.assertEqual(second['next_reads'],[dict(path='/delivery/tests/test_new.py',offset=3,limit=100)])

    def test_same_review_journal_survives_dropped_context_without_granting_approval(self):
        agent=SimpleNamespace()
        stop.guard(agent,self.messages()[:2],json.dumps(self.verdict),39,self.env)
        # Old app.py read is no longer in the model conversation. The journal
        # retains its actual result; controller attestation remains independent.
        result=stop.apply_request(agent,self.api_request(),self.messages()[2:4],38,self.env)
        self.assertIn('"complete_files": 1',result['messages'][0]['content'])
        self.assertIn('"offset": 3',result['messages'][0]['content'])
        final=stop.guard(agent,self.messages()[-2:],json.dumps(self.verdict),37,self.env)
        self.assertIsNone(final)
        self.assertFalse(agent._quality_review_journal.plan()['tests_approved'])

    def test_duplicate_content_under_new_id_is_not_progress(self):
        agent=SimpleNamespace();one=self.page('app.py','a',1,1,'1|VALUE=0')
        stop.guard(agent,one,json.dumps(self.verdict),39,self.env)
        repeat=self.page('app.py','another',1,1,'1|VALUE=0')
        second=stop.guard(agent,repeat,json.dumps(self.verdict),38,self.env)
        self.assertTrue(second['blocked']);self.assertEqual(second['repeated_without_progress'],2)

    def test_valid_rejection_cannot_hide_conflicting_other_snapshot_bytes(self):
        choice={**self.verdict,'action':'request_changes','findings':[dict(path='tests/test_new.py')]}
        bad=self.messages();bad[1]['content']=bad[1]['content'].replace('VALUE=0','VALUE=1')
        result=stop.guard(SimpleNamespace(),bad,json.dumps(choice),39,self.env)
        self.assertIsNotNone(result);self.assertTrue(result['blocked'])
        self.assertEqual(result['inspection_error'],'snapshot_read_evidence_invalid')

    def test_verified_progress_has_no_four_handoff_cap_inside_the_original_budget(self):
        config=copy.deepcopy(self.config)
        inventory={f'file-{n}.py':dict(bytes=2,sha256=hashlib.sha256(b'x\n').hexdigest()) for n in range(7)}
        config['read_paths']=['/delivery/'+p for p in inventory]
        config['review_context']['files']=inventory
        config['review_context']['packet']['manifest_sha256']=hashlib.sha256(json.dumps({'files':inventory},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        config['review_context']['packet']['plan']['new_tests']=['file-0.py']
        env={**self.env,phase.KEY:json.dumps(config)}
        verdict={**self.verdict,'manifest_sha256':config['review_context']['packet']['manifest_sha256']}
        agent=SimpleNamespace();history=[]
        for n in range(6):
            result=stop.guard(agent,history,json.dumps(verdict),39-n,env)
            self.assertFalse(result['blocked']);self.assertEqual(result['repeated_without_progress'],1)
            history+=self.page(f'file-{n}.py','file-'+str(n),1,1,'1|x')
        self.assertEqual(result['attempt'],6)

    def test_no_foreign_execution_or_invalid_context_can_reuse_feedback_state(self):
        agent=SimpleNamespace();stop.guard(agent,[],json.dumps(self.verdict),39,self.env)
        config=copy.deepcopy(self.config);config['request_id']=config['request_id'][:-1]+'2'
        env={**self.env,phase.KEY:json.dumps(config),'DELIVERY_MODEL_EXECUTION_ID':config['request_id']}
        with self.assertRaises(ValueError):stop.guard(agent,[],json.dumps(self.verdict),39,env)
        invalid=copy.deepcopy(self.config);invalid['review_context']['files']['app.py']['sha256']='0'*64
        with self.assertRaises(ValueError):phase.validate(invalid,self.request)
        invalid=copy.deepcopy(self.config);invalid['phase']='tests_only_v2'
        with self.assertRaises(ValueError):phase.validate(invalid,self.request)

    def test_no_reads_from_prose_or_wrong_bytes_or_denied_tool_calls(self):
        bad=self.messages();bad[1]['content']=bad[1]['content'].replace('VALUE=0','VALUE=1')
        result=stop.guard(SimpleNamespace(),bad,json.dumps(self.verdict),39,self.env)
        self.assertEqual(result['remaining_files'],1);self.assertEqual(result['next_reads'],[])
        self.assertTrue(result['blocked']);self.assertEqual(result['inspection_error'],'snapshot_read_evidence_invalid')
        denied=self.page('app.py','denied',1,1,'1|VALUE=0');denied[-1]['content']='{"error":"denied"}'
        self.assertEqual(stop.pairs(denied),[])
        self.assertEqual(stop.pairs([dict(role='assistant',content=json.dumps(self.messages()))]),[])

    def test_rejection_requires_new_tests_and_cited_files_not_all_approval_paths(self):
        choice={**self.verdict,'action':'request_changes','findings':[dict(path='tests/test_new.py')]}
        result=stop.inspect(self.config,self.messages()[2:],json.dumps(choice))
        self.assertEqual(result['remaining_files'],0);self.assertEqual(result['required_files'],1)
        # Advisory scope is NOT semantic finding validation. Controller still
        # rejects this intentionally incomplete finding via its exact schema/AST.
        self.assertFalse(result['tests_approved'])

    def test_hook_retries_inside_the_same_loop_and_never_increments_its_budget(self):
        source='''def run(agent, responses, messages):
    api_call_count = 0
    while api_call_count < agent.max_iterations and agent.iteration_budget.remaining > 0:
        api_call_count += 1
        agent.iteration_budget.remaining -= 1
        final_response = responses.pop(0)
        final_msg = {"role": "assistant", "content": final_response}
        if True:
            if True:
'''+LOOP_ANCHOR+'''                break
    return final_response, api_call_count, messages
'''
        namespace=dict(json=json,append_message=lambda messages,msg:messages.append(msg))
        exec(compile(adapt_loop(source),'fixture_loop','exec'),namespace)
        audit=[];agent=SimpleNamespace(max_iterations=40,iteration_budget=SimpleNamespace(remaining=40),reasoning_callback=audit.append)
        good=json.dumps(self.verdict)
        with patch.dict(os.environ,self.env,clear=True):
            output,count,history=namespace['run'](agent,['Prose\n'+good,good],self.messages())
        self.assertEqual(output,good);self.assertEqual(count,2);self.assertEqual(agent.iteration_budget.remaining,38)
        self.assertEqual(len(audit),1);self.assertIn('Prose',audit[0])
        self.assertTrue(any('advisory_review_completion_v1' in str(m.get('content')) for m in history))
        for changed in (source+LOOP_ANCHOR,source.replace(LOOP_ANCHOR,''),adapt_loop(source)):
            with self.assertRaises(ValueError):adapt_loop(changed)

    def test_acp_drafts_are_suppressed_only_for_enabled_review(self):
        source='''def setup(message_cb):
    streamed_message = False
    if True:
        if True:
'''+STREAM_ANCHOR+'''                    streamed_message = True
                message_cb(text)
            return stream_delta_cb
'''
        namespace={};exec(compile(adapt_acp(source),'fixture_acp','exec'),namespace)
        seen=[]
        with patch.dict(os.environ,self.env,clear=True):namespace['setup'](seen.append)('rejected draft')
        self.assertEqual(seen,[])
        with patch.dict(os.environ,{},clear=True):namespace['setup'](seen.append)('legacy message')
        self.assertEqual(seen,['legacy message'])
        with self.assertRaises(ValueError):adapt_acp(adapt_acp(source))

    def test_acp_factory_explicitly_binds_forty_iterations_only_for_v2(self):
        source='def create(kwargs):\n    if True:\n'+SESSION_ANCHOR+'        return agent\n'
        namespace=dict(AIAgent=lambda **kwargs:kwargs)
        exec(compile(adapt_session(source),'fixture_factory','exec'),namespace)
        with patch.dict(os.environ,self.env,clear=True):
            actual=namespace['create'](dict(model='fixed',max_iterations=999))
        self.assertEqual(actual,dict(model='fixed',max_iterations=40))
        with patch.dict(os.environ,{},clear=True):self.assertEqual(namespace['create'](dict(model='legacy')),dict(model='legacy'))
        with self.assertRaises(ValueError):adapt_session(adapt_session(source))

    def test_outbound_hook_uses_the_original_budget_and_rejects_source_drift(self):
        source='''def request(agent, api_kwargs, messages, api_call_count):
    if True:
        if True:
            if True:
'''+REQUEST_ANCHOR+'''                return api_kwargs
'''
        namespace={};exec(compile(adapt_request(source),'fixture_request','exec'),namespace)
        agent=SimpleNamespace(max_iterations=40,iteration_budget=SimpleNamespace(remaining=37))
        stop.guard(agent,[],json.dumps(self.verdict),38,self.env)
        with patch.dict(os.environ,self.env,clear=True):
            result=namespace['request'](agent,self.api_request(),[],3)
        self.assertEqual(result['tool_choice']['function']['name'],'read_file')
        self.assertEqual(agent.iteration_budget.remaining,37)
        for changed in (source.replace(REQUEST_ANCHOR,''),source+REQUEST_ANCHOR,adapt_request(source)):
            with self.assertRaises(ValueError):adapt_request(changed)

    def test_advisory_attempts_are_archived_but_cannot_attest_or_grant(self):
        with sqlite3.connect(':memory:') as con:
            con.execute('CREATE TABLE quality_native_scopes(request_id TEXT,task_id TEXT,phase TEXT)')
            con.execute('INSERT INTO quality_native_scopes VALUES(?,?,?)',(self.request,'task','test_review_v2'))
            note=dict(candidate='prose',candidate_sha256=hashlib.sha256(b'prose').hexdigest(),diagnostic=dict(tests_approved=True))
            notifications=[dict(method='session/update',params=dict(update=dict(sessionUpdate='agent_thought_chunk',
                content=dict(type='text',text=receipts.PREFIX+json.dumps(note)))))]
            binding=dict(request_id=self.request,task_id='task')
            receipts.store(con,binding,notifications);receipts.store(con,binding,notifications)
            rows=con.execute('SELECT receipt FROM quality_review_completion_receipts').fetchall()
            self.assertEqual(len(rows),1)
            saved=json.loads(rows[0][0]);self.assertFalse(saved['authoritative']);self.assertFalse(saved['tests_approved'])
            self.assertEqual(saved['worker_advisory'],note)
            self.assertFalse(con.execute("SELECT 1 FROM sqlite_master WHERE name IN ('grants','quality_review_attestations')").fetchone())


if __name__=='__main__':unittest.main()
