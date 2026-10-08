import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from planning_source_review import pending,validate,run


class SourceReviewTests(unittest.TestCase):
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
