import asyncio
import hashlib
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock,patch
import unittest
from broker import author_feedback_client as client,review_tool_policy as policy
from broker.patch_receipt_contract import receipt
import literal_author_feedback as sandbox
import literal_feedback_wire as wire
import test_literal_test_maintenance as fixture


class AuthorFeedbackClientTests(unittest.TestCase):
    def setUp(self):
        client.PAGES.clear();self.current=fixture.LiteralMaintenanceTests.SOURCE
        self.cfg=dict(request_id='11111111-1111-4111-8111-111111111111',task_id='22222222-2222-4222-8222-222222222222',
            capability='a'*64,test_path='tests/test.py',previous_manifest_sha256='b'*64,feedback_sha256='c'*64,
            expected=dict(initial_expected=1,poll_minimum=3,stale_expected='Newest matching: #11'))
        env=patch.dict(os.environ,{'DELIVERY_EXECUTION_MODE':'implementation','DELIVERY_AUTHOR_FEEDBACK_JSON':json.dumps(self.cfg)})
        env.start();self.addCleanup(env.stop)
        reader=patch.object(client,'read_current',side_effect=lambda cfg:self.current);reader.start();self.addCleanup(reader.stop)
        self.opener=Mock();self.opener.open.side_effect=self.response
        builder=patch.object(client.urllib.request,'build_opener',return_value=self.opener)
        self.builder=builder.start();self.addCleanup(builder.stop)
        self.args=dict(path='/workspace/tests/test.py',old_string='const value = 1;',new_string='const value = 2;')

    def value(self):
        return dict(operation='literal_author_feedback_v1',candidate_sha256=hashlib.sha256(self.current).hexdigest(),
            feedback_sha256='c'*64,previous_manifest_sha256='b'*64,test_path='tests/test.py',expected=self.cfg['expected'],
            reports={n:dict(initial_requests=1,poll_requests=2,stale_guard_text='Newest matching: #11' if n=='guarded' else 'Newest matching: #4')
                for n in ('guarded','unguarded')},capture=dict(field='poll_requests',literal='NODE_HARNESS',literal_line=177,
                    assignment='snap.poll_requests = latestCount();'),failed_fields=['poll_requests'],checks_passed=False,
            outside_literal_bytes_preserved=True,candidate_bytes_stable_during_measurement=True,
            evidence_scope='current_file_fixed_diagnostic_only',non_target_verification='not_performed_in_feedback',
            model_calls=0,next_action='not trusted policy',request_id=self.cfg['request_id'],task_id=self.cfg['task_id'],
            validation_job_key='d'*64,validation_contract_sha256='e'*64,**{k:False for k in wire.FALSE_FLAGS})

    def response(self,*args,**kwargs):
        result=Mock();result.status=200;result.read.return_value=json.dumps(self.value()).encode()
        result.__enter__=Mock(return_value=result);result.__exit__=Mock(return_value=False);return result

    def inspected(self):
        client.observe(self.cfg,'read_file',dict(path=self.args['path'],offset=1,limit=200),
            json.dumps(dict(content=self.current.decode(),total_lines=len(self.current.decode().splitlines()))))

    def handler(self,args):
        self.current=self.current.decode().replace(args['old_string'],args['new_string'],1).encode()
        return json.dumps(dict(success=True,diff='real local diff'))

    def test_patch_includes_current_measurement_and_formatter_preserves_it_without_approval(self):
        self.inspected();handler=Mock(side_effect=self.handler)
        result=policy.fence('patch',handler)(self.args);handler.assert_called_once()
        facts=receipt('patch',result);self.assertTrue(facts['changed'])
        feedback=facts['author_feedback'];self.assertFalse(feedback['checks_passed'])
        self.assertIn('BEFORE snap.poll_requests',feedback['instruction'])
        self.assertFalse(feedback['delivery_approval']);self.assertNotIn('capability',json.dumps(facts))
        request=self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url,client.ENDPOINT)
        self.assertEqual(json.loads(request.data),dict(candidate_sha256=hashlib.sha256(self.current).hexdigest()))
        self.assertEqual(self.builder.call_args.args[0].proxies,{})
        self.assertEqual(client.PAGES,{})

    def test_direct_handler_cannot_skip_fresh_reads_or_modify_assertions_or_product(self):
        handler=Mock(side_effect=self.handler);wrapped=policy.fence('patch',handler)
        self.assertIn('error',json.loads(wrapped(self.args)));handler.assert_not_called()
        self.inspected()
        for args in ({**self.args,'path':'/workspace/app.py'},
                dict(path=self.args['path'],old_string='assertEqual(1, 2)',new_string='assertTrue(True)')):
            self.assertIn('error',json.loads(wrapped(args)))
        for tool in ('terminal','write_file','cronjob','surgical_test_edit'):
            self.assertIn('error',json.loads(policy.controlled(tool,dict(command='id'))))
        handler.assert_not_called();self.opener.open.assert_not_called()

    def test_failed_feedback_transport_does_not_hide_saved_patch_or_leak_private_body(self):
        self.inspected();self.opener.open.side_effect=RuntimeError('PRIVATE HTTP BODY '+self.cfg['capability'])
        result=json.loads(policy.fence('patch',self.handler)(self.args))
        self.assertTrue(result['success']);self.assertIn(b'const value = 2;',self.current)
        self.assertEqual(result['_author_feedback_v1']['status'],'unavailable')
        self.assertNotIn('PRIVATE HTTP BODY',json.dumps(result));self.assertNotIn(self.cfg['capability'],json.dumps(result))

    def test_virtual_read_observes_feedback_without_running_original_file_handler(self):
        handler=Mock();result=json.loads(policy.fence('read_file',handler)(dict(path=client.VIRTUAL_PATH)))
        handler.assert_not_called();facts=json.loads(result['content']);self.assertFalse(facts['checks_passed'])
        self.assertEqual(facts['candidate_sha256'],hashlib.sha256(self.current).hexdigest())

    def test_wrong_execution_response_stale_bytes_or_forged_green_is_not_presented(self):
        original=self.value
        for key,value in (('request_id','other'),('candidate_sha256','f'*64),('checks_passed',True),('delivery_approval',True)):
            with patch.object(self,'value',side_effect=lambda:{**original(),key:value}):
                self.assertEqual(client.request(self.cfg)['status'],'unavailable')

    def test_no_redirect_and_pending_observes_same_hash_without_repatching(self):
        with self.assertRaises(ValueError):client.NoRedirect().redirect_request(None,None,None,None,None,None)
        pending=dict(operation='literal_author_feedback_pending_v1',candidate_sha256=hashlib.sha256(self.current).hexdigest(),
            next_action='observe_same_feedback_job',**{k:False for k in wire.FALSE_FLAGS})
        first=self.response();first.read.return_value=json.dumps(pending).encode()
        self.opener.open.side_effect=[first,self.response()]
        with patch.object(client.time,'sleep'):result=client.request(self.cfg)
        self.assertFalse(result['checks_passed']);calls=self.opener.open.call_args_list
        self.assertEqual(calls[-1].args[0].data,calls[-2].args[0].data)

    def test_async_direct_handler_is_fenced_and_reports_feedback(self):
        self.inspected()
        async def handler(args):
            await asyncio.sleep(0);return self.handler(args)
        result=json.loads(asyncio.run(policy.fence('patch',handler,True)(self.args)))
        self.assertFalse(result['_author_feedback_v1']['checks_passed'])

    def test_shared_wire_flags_match_sandbox_and_reject_unknown_formatter_data(self):
        self.assertEqual(wire.FALSE_FLAGS,sandbox.FALSE_FLAGS)
        raw=json.dumps(dict(success=True,diff='x',_author_feedback_v1={**{k:False for k in wire.FALSE_FLAGS},'capability':'secret'}))
        self.assertNotIn('author_feedback',receipt('patch',raw))
