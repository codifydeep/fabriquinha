import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from planning_source_review import pending,validate,run,revalidate,transport as real_transport


class SourceReviewTests(unittest.TestCase):
    def setUp(self):
        wire=patch('planning_source_review.transport',return_value={'version':'source-review-transport-v1'})
        wire.start();self.addCleanup(wire.stop)
    def state(self,brief):
        return {'stage':'blocked_awaiting_ceo','brief_clarification_product':1,
            'configuration_sha256':'a'*64,'brief_sha256':hashlib.sha256(brief.encode()).hexdigest(),
            'name':'TEST','questions':['Navigate?'],'issues':{'product':'old'},
            'outputs':{'product':{'proposal':{'business_questions':['Navigate?']}}}}

    def answer(self):
        return {'role':'cto','resolutions':[{'index':0,'classification':'explicit_brief',
            'quote':'No page navigation.','answer':'Use a local panel, without navigation.'}]}

    def test_literal_source_is_required_and_unresolved_cannot_be_answered(self):
        self.assertEqual(validate(self.answer(),'No page navigation.',['Navigate?']),self.answer()['resolutions'])
        bad=self.answer();bad['resolutions'][0]['quote']='Allow navigation.'
        with self.assertRaises(ValueError):validate(bad,'No page navigation.',['Navigate?'])
        bad=self.answer();bad['resolutions'][0]['classification']='requires_ceo'
        with self.assertRaises(ValueError):validate(bad,'No page navigation.',['Navigate?'])
        bad['resolutions'][0].update(quote='',answer='')
        self.assertEqual(validate(bad,'No page navigation.',['Navigate?'])[0]['classification'],'requires_ceo')

    def test_literal_quote_does_not_validate_a_contradictory_unknown_answer(self):
        bad=self.answer()
        bad['resolutions'][0]['answer']='The brief does not say; direct navigation is not addressed.'
        with self.assertRaisesRegex(ValueError,'unresolved answer'):
            validate(bad,'No page navigation.',['Navigate?'])

    def test_persisted_contradictory_review_is_invalidated_without_erasing_history(self):
        brief='No page navigation.';state=self.state(brief)
        bad=self.answer();bad['resolutions'][0]['answer']='Direct navigation is not addressed.'
        state['source_review']={'stage':'verified','brief_sha256':state['brief_sha256'],
            'resolutions':bad['resolutions'],'questions':['Navigate?'],'task_id':'old'}
        before=copy.deepcopy(state)
        result=revalidate(state,brief)
        self.assertEqual(state,before)
        self.assertEqual(result['owner'],'cto')
        self.assertEqual(result['prior_invalid_source_review'],before['source_review'])
        self.assertEqual(result['outputs'],before['outputs'])
        self.assertIsNone(revalidate(result,brief))

    def test_contradictory_source_review_dispatches_one_changed_cto_diagnosis(self):
        brief='No page navigation.';state=self.state(brief)
        bad=self.answer();bad['resolutions'][0]['answer']='Direct navigation is not addressed.'
        receipt={'stage':'verified','brief_sha256':state['brief_sha256'],
            'configuration_sha256':state['configuration_sha256'],
            'resolutions':bad['resolutions'],'questions':['Navigate?'],'task_id':'old',
            'output_sha256':'b'*64,'transport':{'version':'source-review-transport-v1'}}
        state['source_review']=receipt
        state=revalidate(state,brief)
        state.pop('questions',None)
        self.assertTrue(pending(state))
        with tempfile.TemporaryDirectory() as directory,patch('planning_intake.issue_for',return_value='diagnosis') as issue,patch('planning_intake.completed_output',return_value=('new-task',json.dumps(self.answer()))):
            result=run(state,brief,{'agents':{'cto':'cto'}},Path(directory)/'receipt.json')
            self.assertEqual(issue.call_args.kwargs['run_name'],'TEST-SOURCE-REVIEW-DIAGNOSIS')
            self.assertIn('Rejected source review',issue.call_args.args[1])
            self.assertEqual(result['source_review_diagnosis']['prior_review'],state['source_review'])
            self.assertEqual(result['stage'],'product_source_reconciliation')
            self.assertEqual(result['source_review_product_attempt'],2)
            result.update(stage='blocked',active='source_review',category=state['category'])
            result['source_review']['stage']='blocked'
            self.assertFalse(pending(result))

    def test_diagnosis_does_not_retry_unknown_review_or_transport_errors(self):
        state=self.state('No page navigation.')
        for category in ('RuntimeError:agent failed','ValueError:strict transport not proven'):
            state.update(stage='blocked',active='source_review',category=category,
                source_review={'stage':'blocked','category':category})
            self.assertFalse(pending(state))

    def test_coverage_order_types_and_unknown_fields_fail_closed(self):
        for index in (1,True):
            bad=self.answer();bad['resolutions'][0]['index']=index
            with self.assertRaises(ValueError):validate(bad,'No page navigation.',['Navigate?'])
        for field,value in [('classification','technical_override'),('quote',None),('answer','x'*301)]:
            bad=self.answer();bad['resolutions'][0][field]=value
            with self.assertRaises(ValueError):validate(bad,'No page navigation.',['Navigate?'])
        with self.assertRaises(ValueError):validate(self.answer(),'No page navigation.',['A','B'])
        with self.assertRaises(ValueError):validate({**self.answer(),'merge':True},'No page navigation.',['A'])

    def test_review_routes_back_to_product_without_human_approval(self):
        brief='No page navigation.';state=self.state(brief);before=copy.deepcopy(state)
        with tempfile.TemporaryDirectory() as directory,patch('planning_intake.issue_for',return_value='review') as create,patch('planning_intake.completed_output',return_value=('task',json.dumps(self.answer()))):
            path=Path(directory)/'receipt.json'
            result=run(state,brief,{'agents':{'cto':'cto'}},path)
            self.assertEqual(result['stage'],'product_source_reconciliation')
            self.assertEqual(result['outputs'],{})
            self.assertEqual(result['prior_source_review_product']['output'],before['outputs']['product'])
            self.assertFalse(result['source_review']['ceo_answer_created'])
            self.assertFalse(result['source_review']['scope_approval_created'])
            self.assertFalse(pending(result))
            create.assert_called_once()
            self.assertEqual(state,before)

    def test_failure_is_visible_with_cto_not_blind_retry(self):
        brief='No page navigation.'
        with tempfile.TemporaryDirectory() as directory,patch('planning_intake.issue_for',side_effect=RuntimeError('failed')):
            result=run(self.state(brief),brief,{'agents':{'cto':'cto'}},Path(directory)/'receipt.json')
            self.assertEqual((result['stage'],result['owner']),('blocked','cto'))
            self.assertFalse(pending(result))

    def test_unproven_transport_cannot_resolve_or_approve_questions(self):
        brief='No page navigation.'
        with tempfile.TemporaryDirectory() as directory,patch('planning_intake.issue_for',return_value='review'),patch('planning_intake.completed_output',return_value=('task',json.dumps(self.answer()))),patch('planning_source_review.transport',side_effect=ValueError('not proven')):
            result=run(self.state(brief),brief,{'agents':{'cto':'cto'}},Path(directory)/'receipt.json')
            self.assertEqual(result['owner'],'cto')
            self.assertEqual(result['stage'],'blocked')
            self.assertNotIn('source_review_product',result)

    def test_old_unqualified_review_is_preserved_and_requalified_once(self):
        brief='No page navigation.';state=self.state(brief)
        old={'stage':'verified','questions':['Navigate?'],'task_id':'old-review'}
        state['source_review']=old
        self.assertTrue(pending(state))
        with tempfile.TemporaryDirectory() as directory,patch('planning_intake.issue_for',return_value='strict') as issue,patch('planning_intake.completed_output',return_value=('new-task',json.dumps(self.answer()))):
            result=run(state,brief,{'agents':{'cto':'cto'}},Path(directory)/'receipt.json')
            self.assertEqual(result['prior_unqualified_source_review'],old)
            self.assertEqual(issue.call_args.kwargs['run_name'],'TEST-SOURCE-REVIEW-STRICT')
            self.assertFalse(pending(result))

    def test_real_missing_choice_stays_with_ceo(self):
        brief='No page navigation.';answer=self.answer()
        answer['resolutions'][0].update(classification='requires_ceo',quote='',answer='')
        with tempfile.TemporaryDirectory() as directory,patch('planning_intake.issue_for',return_value='review'),patch('planning_intake.completed_output',return_value=('task',json.dumps(answer))):
            result=run(self.state(brief),brief,{'agents':{'cto':'cto'}},Path(directory)/'receipt.json')
            self.assertEqual((result['stage'],result['owner']),('blocked_awaiting_ceo','ceo'))
            self.assertEqual(result['questions'],['Navigate?'])
            self.assertFalse(pending(result))

    def test_drift_and_first_unreviewed_question_do_not_dispatch(self):
        state=self.state('No page navigation.')
        with patch('planning_intake.issue_for') as create:
            with self.assertRaises(ValueError):run(state,'Changed brief',{'agents':{'cto':'cto'}},None)
            create.assert_not_called()
        state.pop('brief_clarification_product')
        self.assertFalse(pending(state))

    def test_transport_requires_exact_binding_strict_schema_and_zero_tools(self):
        labels=[json.dumps({'com.docker.compose.project':'delivery-kit-port2',
                           'com.docker.compose.service':service}) for service in ('execution-broker','model-proxy')]
        binding=json.dumps([{'request_id':'execution','scope':'workspace:planning:task'}])
        event={'event':'model_proxy_request','execution_id':'execution','status':200,
            'structured_format':'json_schema','strict_schema':True,'tool_count':0,'call_number':1}
        with patch('evalctl.PROJECT','delivery-kit-port2'),patch('planning_source_review.subprocess.check_output',side_effect=[*labels,binding,json.dumps(event)]):
            self.assertEqual(real_transport('task')['task_id'],'task')
        for key,value in [('execution_id','other'),('strict_schema',False),('tool_count',18),('structured_format',None)]:
            bad={**event,key:value}
            with patch('evalctl.PROJECT','delivery-kit-port2'),patch('planning_source_review.subprocess.check_output',side_effect=[*labels,binding,json.dumps(bad)]),self.assertRaises(ValueError):
                real_transport('task')

    def test_proxy_schema_and_native_stream_cover_source_review(self):
        from planning_schema import apply,caller_response
        body={'messages':[{'role':'user','content':'DELIVERY_PLANNING_SCHEMA_V1:source_review'}]}
        apply(body)
        self.assertEqual(body['response_format']['json_schema']['schema']['properties']['role']['enum'],['cto'])
        self.assertEqual(body['tools'],[])
        self.assertIn('Role=cto.',body['messages'][-2]['content'])
        text=json.dumps(self.answer())
        raw=json.dumps({'choices':[{'message':{'content':text},'finish_reason':'stop'}]}).encode()
        data,media=caller_response(body,raw,'application/json',True)
        self.assertEqual(media,'text/event-stream');self.assertIn(b'[DONE]',data)
