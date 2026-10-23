"""Same-turn capture and handler enforcement, not native approval evidence."""
import copy
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import quality_review_stop as stop
import quality_phase_tools as phase
import quality_review_paging as paging
from broker import review_tool_policy as policy
import test_quality_review_stop as fixtures
import install_quality_review_stop as installer


class QualityReviewExecutionTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.QualityReviewStopTests();f.setUp()
        self.f=f;self.agent=SimpleNamespace();self.env=f.env
        self.verdict=json.dumps(f.verdict)

    def arm(self,messages=None):
        messages=[] if messages is None else messages
        stop.guard(self.agent,messages,self.verdict,39,self.env)
        return stop.apply_request(self.agent,self.f.api_request(),messages,38,self.env)

    def test_request_projects_only_exact_pending_paths_offset_and_limit(self):
        original=self.f.api_request();before=copy.deepcopy(original)
        stop.guard(self.agent,self.f.messages()[:-2],self.verdict,39,self.env)
        result=stop.apply_request(self.agent,original,self.f.messages()[:-2],38,self.env)
        schema=result['tools'][0]['function']['parameters']
        self.assertEqual(schema['properties']['path']['enum'],['/delivery/tests/test_new.py'])
        self.assertEqual(schema['properties']['offset']['enum'],[3])
        self.assertEqual(schema['properties']['limit']['enum'],[100])
        self.assertEqual(set(schema['required']),{'path','offset','limit'})
        self.assertFalse(schema['additionalProperties']);self.assertEqual(original,before)

    def test_direct_sync_async_handlers_reject_old_pages_and_duplicate_claims(self):
        self.arm(self.f.messages()[:-2])
        with patch.dict(os.environ,self.env,clear=True):
            original=Mock(return_value='fixture read')
            handler=policy.fence('read_file',original)
            for args in (dict(path='/delivery/app.py',offset=1,limit=100),
                    dict(path='/delivery/tests/test_new.py',offset=1,limit=100),
                    dict(path='/delivery/tests/test_new.py',offset=3,limit=99),
                    dict(path='/delivery/tests/test_new.py',offset=4,limit=100)):
                self.assertIn('error',json.loads(handler(args)))
            original.assert_not_called()
            args=dict(path='/delivery/tests/test_new.py',offset=3,limit=100)
            self.assertEqual(handler(args),'fixture read');original.assert_called_once()
            self.assertIn('error',json.loads(handler(args)));original.assert_called_once()
            import asyncio
            async def forbidden(*args,**kwargs):raise AssertionError('duplicate async read escaped')
            self.assertIn('error',json.loads(asyncio.run(policy.fence('read_file',forbidden,True)(args))))

    def test_registry_preflight_does_not_consume_the_real_handler_claim(self):
        self.arm(self.f.messages()[:-2])
        args=dict(path='/delivery/tests/test_new.py',offset=3,limit=100)
        with patch.dict(os.environ,self.env,clear=True):
            self.assertIsNone(policy.controlled('read_file',args))
            original=Mock(return_value='real handler entered')
            handler=policy.fence('read_file',original)
            self.assertEqual(handler(args),'real handler entered')
            self.assertIn('error',json.loads(handler(args)));original.assert_called_once()

    def test_capture_before_compaction_preserves_reads_without_requiring_early_answer(self):
        self.assertIsNone(stop.checkpoint(self.agent,self.f.messages()[:2],39,environment=self.env))
        self.assertFalse(hasattr(self.agent,'_quality_review_completion'))
        result=stop.guard(self.agent,[],self.verdict,38,self.env)
        self.assertEqual(result['complete_files'],1)
        self.assertEqual(result['next_reads'],[dict(path='/delivery/tests/test_new.py',offset=1,limit=100)])

    def test_two_completed_tool_rounds_without_new_bytes_stop_structurally(self):
        self.arm()
        first=stop.checkpoint(self.agent,[],37,after_tools=True,environment=self.env)
        self.assertIsNone(first)
        stop.apply_request(self.agent,self.f.api_request(),[],37,self.env)
        result=stop.checkpoint(self.agent,[],36,after_tools=True,environment=self.env)
        self.assertTrue(result['blocked']);self.assertEqual(result['category'],'read_progress_stalled')
        self.assertFalse(result['tests_approved']);self.assertFalse(result['delivery_approval'])
        with self.assertRaises(ValueError):stop.apply_request(self.agent,self.f.api_request(),[],35,self.env)

    def test_actual_partial_progress_does_not_stall_and_last_tool_round_is_bounded(self):
        self.arm()
        for index,messages in enumerate((self.f.page('tests/test_new.py','b',1,3,'1|one'),
                self.f.page('tests/test_new.py','c',2,3,'2|two'))):
            self.assertIsNone(stop.checkpoint(self.agent,messages,37-index,after_tools=True,environment=self.env))
            stop.apply_request(self.agent,self.f.api_request(),messages,37-index,self.env)
        exhausted=stop.checkpoint(self.agent,[],0,after_tools=True,environment=self.env)
        self.assertEqual(exhausted['category'],'iteration_budget_exhausted')
        self.assertEqual(exhausted['remaining_iterations'],0);self.assertTrue(exhausted['blocked'])

    def test_snapshot_corruption_has_structured_stop_not_read_from_offset_one(self):
        bad=self.f.messages();bad[1]['content']=bad[1]['content'].replace('VALUE=0','VALUE=1')
        result=stop.checkpoint(self.agent,bad,39,environment=self.env)
        self.assertTrue(result['blocked']);self.assertEqual(result['category'],'snapshot_read_evidence_invalid')

    def test_parallel_duplicates_claim_only_once_and_snapshot_drift_cannot_reuse_plan(self):
        self.arm(self.f.messages()[:-2])
        args=dict(path='/delivery/tests/test_new.py',offset=3,limit=100)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:phase.controlled('read_file',args,self.env,handler_entry=True),range(12)))
        self.assertEqual(results.count(None),1)
        self.assertTrue(all('error' in json.loads(result) for result in results if result is not None))
        changed=copy.deepcopy(self.f.config)
        changed['review_context']['packet']['manifest_sha256']='0'*64
        self.assertFalse(paging.allowed(changed,args))

    def test_schema_projection_retains_constraints_and_never_expands_existing_enum(self):
        plan=dict(pages=[dict(path='/delivery/app.py',offset=1,limit=100)])
        original=dict(type='object',properties=dict(path=dict(type='string',pattern='^/delivery/',description='Existing'),
            offset=dict(type='integer',minimum=1),limit=dict(type='integer',maximum=100)),required=['path'])
        result=paging.project(original,plan)
        self.assertEqual(result['properties']['path']['pattern'],'^/delivery/')
        self.assertEqual(result['properties']['path']['description'],'Existing')
        for key,restriction in [('path',dict(enum=['/delivery/other.py'])),
                ('offset',dict(enum=[2])),('limit',dict(maximum=99))]:
            bad=copy.deepcopy(original);bad['properties'][key].update(restriction)
            with self.assertRaises(ValueError):paging.project(bad,plan)

    def test_legacy_or_implementation_mode_does_not_activate_checkpoint_or_change_budget(self):
        agent=SimpleNamespace()
        self.assertIsNone(stop.checkpoint(agent,[],0,after_tools=True,environment={}))
        self.assertEqual(vars(agent),{})

    def test_capture_hook_compiles_and_runs_before_fixture_compaction(self):
        source='''def run(agent, messages):
    api_call_count=0
    final_response=None
'''+installer.CAPTURE_ANCHOR+'''        messages=[]  # simulated pre-API compaction
        break
    return messages
'''
        namespace=dict(json=json,append_message=lambda messages,msg:messages.append(msg))
        exec(compile(installer.adapt_capture(source),'capture_fixture','exec'),namespace)
        self.agent.max_iterations=40;self.agent.iteration_budget=SimpleNamespace(remaining=40)
        self.agent._budget_grace_call=False;self.agent.reasoning_callback=None
        with patch.dict(os.environ,self.env,clear=True):namespace['run'](self.agent,self.f.messages()[:2])
        self.assertEqual(self.agent._quality_review_journal.plan()['complete_files'],1)
        for drift in (source.replace(installer.CAPTURE_ANCHOR,''),source+installer.CAPTURE_ANCHOR,
                installer.adapt_capture(source)):
            with self.assertRaises(ValueError):installer.adapt_capture(drift)

    def test_post_tool_hook_returns_diagnostic_before_last_iteration_falls_out(self):
        source='''def run(agent, messages):
    api_call_count=40
    final_response=None
    while True:
        if True:
            if True:
'''+installer.POST_TOOL_ANCHOR+'''                break
    return final_response
'''
        namespace=dict(json=json,append_message=lambda messages,msg:messages.append(msg))
        exec(compile(installer.adapt_post_tools(source),'post_tool_fixture','exec'),namespace)
        self.agent.max_iterations=40;self.agent.iteration_budget=SimpleNamespace(remaining=0)
        self.agent.reasoning_callback=None
        with patch.dict(os.environ,self.env,clear=True):result=namespace['run'](self.agent,[])
        self.assertEqual(json.loads(result)['category'],'iteration_budget_exhausted')
        for drift in (source.replace(installer.POST_TOOL_ANCHOR,''),source+installer.POST_TOOL_ANCHOR,
                installer.adapt_post_tools(source)):
            with self.assertRaises(ValueError):installer.adapt_post_tools(drift)


if __name__=='__main__':unittest.main()
