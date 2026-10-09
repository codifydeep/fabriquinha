import copy
import json
import unittest
from unittest.mock import patch
import test_read_stream_recovery as fixtures
import model_proxy as proxy
from decision_schema import apply as schema
from typed_decision_contract import apply,translate,NAME,REVIEW_NAME,response_shape,normalize_technical_padding
from structured_response_contract import StructuredResponseRejected


class TypedDecisionTests(unittest.TestCase):
    def test_opt_in_prose_feedback_requires_fresh_valid_tool_submission(self):
        import sqlite3
        for valid in (True,False):
            f=fixtures.ReadStreamRecoveryTests();f.setUp()
            try:
                body=fixtures.request_body();body['messages'][0]['content']='DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\nDELIVERY_TECHNICAL_FORMAT_FEEDBACK_V1\n'
                prose=json.dumps({'choices':[{'message':{'content':'PRIVATE_PROSE'},'finish_reason':'stop'}]}).encode()
                good=self.wire(self.decision)
                with patch.object(proxy,'forward',side_effect=[(200,prose,'application/json'),(200,good if valid else prose,'application/json')]) as forward:
                    reply=f.request(body)
                self.assertEqual(reply.status,200 if valid else 502);self.assertEqual(forward.call_count,2)
                revised=forward.call_args_list[1].args[0]
                self.assertNotIn('PRIVATE_PROSE',json.dumps(revised))
                self.assertEqual(revised['tools'],forward.call_args_list[0].args[0]['tools'])
                with sqlite3.connect(f.counter.with_name('deterministic-reads.sqlite')) as con:
                    receipt=json.loads(con.execute('SELECT receipt FROM technical_format_feedback').fetchone()[0])
                    self.assertFalse(receipt['delivery_approval']);self.assertFalse(receipt['worker_tool_executed'])
                with patch.object(proxy,'forward') as again:
                    self.assertEqual(f.request(body).status,502);again.assert_not_called()
            finally:f.doCleanups()

    def test_format_feedback_does_not_repair_mixed_tool_prose(self):
        from typed_decision_contract import claim_format_feedback,FORMAT_MARKER
        body=copy.deepcopy(self.body);body['messages'].append(dict(role='user',content=FORMAT_MARKER))
        wire=json.loads(self.wire());wire['choices'][0]['message']['content']='PRIVATE'
        with self.assertRaises(StructuredResponseRejected) as caught:translate(body,json.dumps(wire).encode(),'application/json')
        self.assertIsNone(claim_format_feedback(None,'a'*36,caught.exception,body,1))

    def test_format_feedback_cannot_extend_budget_or_grant_approval(self):
        from typed_decision_contract import format_feedback_enabled,FORMAT_MARKER
        body=copy.deepcopy(self.body);body['messages'].append(dict(role='user',content=FORMAT_MARKER))
        self.assertTrue(format_feedback_enabled(body))
        body['tools'][0]['function']['parameters']['properties']['action']['enum'].append('approve')
        self.assertFalse(format_feedback_enabled(body))
        f=fixtures.ReadStreamRecoveryTests();f.setUp();self.addCleanup(f.doCleanups)
        incoming=fixtures.request_body();incoming['messages'][0]['content']='DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'+FORMAT_MARKER+'\n'
        prose=json.dumps({'choices':[{'message':{'content':'PRIVATE'},'finish_reason':'stop'}]}).encode()
        with patch.object(proxy,'MAX_CALLS',1),patch.object(proxy,'forward',return_value=(200,prose,'application/json')) as forward:
            reply=f.request(incoming)
        self.assertNotEqual(reply.status,200);forward.assert_called_once()

    def review_decision(self):
        return dict(action='reject_test_revision',reason='Actual coverage missing',optional_files=[],
            manifest_sha256='a'*64,findings=[dict(kind='missing_coverage',tree='candidate',
                path='tests/test_new.py',test='__module__',line=1,quote='assert value',
                expected='Real interaction',observed='Static check only')])

    def test_review_feedback_corrects_length_only_and_never_approves_itself(self):
        import sqlite3
        for fields in (('reason',),('expected','observed')):
            f=fixtures.ReadStreamRecoveryTests();f.setUp()
            try:
                body=self.review_body(findings=True);body['model']=proxy.MODEL
                good=self.review_decision();bad=copy.deepcopy(good)
                for field in fields:
                    if field=='reason':bad[field]='x'*1300
                    else:bad['findings'][0][field]='x'*501
                with patch.object(proxy,'forward',side_effect=[
                        (200,self.wire(bad,name=REVIEW_NAME),'application/json'),
                        (200,self.wire(good,name=REVIEW_NAME),'application/json')]) as forward:
                    reply=f.request(body)
                self.assertEqual(reply.status,200);self.assertEqual(forward.call_count,2)
                revised=forward.call_args_list[1].args[0]
                self.assertEqual(json.loads(revised['messages'][-2]['tool_calls'][0]['function']['arguments']),bad)
                feedback=json.loads(revised['messages'][-1]['content'])
                self.assertFalse(feedback['worker_tool_executed'])
                self.assertFalse(feedback['review_acceptance_by_proxy'])
                with sqlite3.connect(f.counter.with_name('deterministic-reads.sqlite')) as con:
                    receipt=json.loads(con.execute('SELECT receipt FROM technical_length_feedback').fetchone()[0])
                    self.assertEqual(receipt['operation'],'review_length_feedback_v1')
                    self.assertEqual(receipt['manifest_sha256'],'a'*64)
                with patch.object(proxy,'forward') as again:
                    self.assertEqual(f.request(body).status,502);again.assert_not_called()
            finally:f.doCleanups()

    def test_review_format_feedback_rejects_verdict_or_finding_drift(self):
        for mutation in ('action','finding_removed','reference','unlisted_prose'):
            f=fixtures.ReadStreamRecoveryTests();f.setUp()
            try:
                body=self.review_body(findings=True);body['model']=proxy.MODEL
                good=self.review_decision();bad=copy.deepcopy(good);bad['reason']='x'*1300
                if mutation=='action':good.update(action='approve_test_revision',findings=[])
                if mutation=='finding_removed':good['findings']=[]
                if mutation=='reference':good['findings'][0]['line']=2
                if mutation=='unlisted_prose':good['findings'][0]['expected']='Changed expectation'
                with patch.object(proxy,'forward',side_effect=[
                        (200,self.wire(bad,name=REVIEW_NAME),'application/json'),
                        (200,self.wire(good,name=REVIEW_NAME),'application/json')]) as forward:
                    reply=f.request(body)
                self.assertEqual(reply.status,502);self.assertEqual(forward.call_count,2)
            finally:f.doCleanups()

    def test_review_feedback_never_repairs_other_schema_failures(self):
        body=self.review_body(findings=True,observed=True)
        for mutation in ('enum','snapshot','path','symbol','unmarked','empty_findings','extra_field','bad_quote'):
            request=copy.deepcopy(body);bad=self.review_decision();bad['reason']='x'*1300
            if mutation=='enum':bad['action']='APPROVE'
            if mutation=='snapshot':bad['manifest_sha256']='b'*64
            if mutation=='path':bad['findings'][0]['path']='x'*201
            if mutation=='symbol':bad['findings'][0]['test']='x'*201
            if mutation=='empty_findings':bad['findings']=[]
            if mutation=='extra_field':bad['unexpected']='not allowed'
            if mutation=='bad_quote':bad['findings'][0]['quote']='unobserved source'
            if mutation=='unmarked':
                from typed_decision_contract import REVIEW_LENGTH_MARKER
                request['messages']=[m for m in request['messages'] if m.get('content')!=REVIEW_LENGTH_MARKER+'\n']
            with self.assertRaises(StructuredResponseRejected) as caught:
                translate(request,self.wire(bad,name=REVIEW_NAME),'application/json')
            self.assertFalse(hasattr(caught.exception,'length_feedback'),mutation)

    def test_review_feedback_is_one_call_and_obeys_the_global_cap(self):
        for cap,good in ((2,False),(1,True)):
            f=fixtures.ReadStreamRecoveryTests();f.setUp()
            try:
                body=self.review_body(findings=True);body['model']=proxy.MODEL
                bad=self.review_decision();bad['reason']='x'*1300
                second=self.review_decision() if good else bad
                with patch.object(proxy,'MAX_CALLS',cap),patch.object(proxy,'forward',side_effect=[
                        (200,self.wire(bad,name=REVIEW_NAME),'application/json'),
                        (200,self.wire(second,name=REVIEW_NAME),'application/json')]) as forward:
                    reply=f.request(body)
                self.assertEqual(reply.status,400 if cap==1 else 502)
                self.assertEqual(forward.call_count,cap)
                self.assertEqual(proxy.load_calls(),cap)
            finally:f.doCleanups()
    def recovery_body(self):
        return schema({'messages':[{'role':'user','content':
            'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_EXECUTION_REPAIR_V1\n'
            'DELIVERY_WORKER_INTERRUPTION_RECOVERY_V1\nDELIVERY_TYPED_WORKER_RECOVERY_V1:'+ 'a'*64+'\n'}]})

    def test_worker_recovery_uses_distinct_nonexecuting_submission(self):
        from typed_decision_contract import RECOVERY_NAME,length_feedback_enabled
        body=apply(self.recovery_body())
        self.assertEqual(body['tool_choice']['function']['name'],RECOVERY_NAME)
        self.assertTrue(length_feedback_enabled(body))
        decision=dict(action='retry_author',reason='Probe passed; preserve existing Red.',optional_files=[])
        out,_,receipt=translate(body,self.wire(decision,name=RECOVERY_NAME),'application/json')
        self.assertEqual(json.loads(json.loads(out)['choices'][0]['message']['content']),decision)
        self.assertFalse(receipt['worker_tool_executed']);self.assertFalse(receipt['author_retry_authorized'])
        self.assertEqual(receipt['recovery_evidence_sha256'],'a'*64)
        for bad in (dict(decision,action='approve'),dict(decision,optional_files=['test.py'])):
            with self.assertRaises(StructuredResponseRejected):translate(body,self.wire(bad,name=RECOVERY_NAME),'application/json')

    def test_worker_recovery_rejects_conflicting_markers_and_schema_widening(self):
        for mutation in ('missing_scope','generic_typed','extra_property'):
            body=self.recovery_body()
            if mutation=='missing_scope':body['messages'][0]['content']=body['messages'][0]['content'].replace('DELIVERY_WORKER_INTERRUPTION_RECOVERY_V1\n','')
            if mutation=='generic_typed':body['messages'][0]['content']+='DELIVERY_TYPED_DECISION_V1\n'
            if mutation=='extra_property':body['response_format']['json_schema']['schema']['properties']['write']={'type':'string'}
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):apply(body)

    def test_worker_recovery_feedback_keeps_distinct_tool_and_actual_arguments(self):
        from typed_decision_contract import RECOVERY_NAME
        body=apply(self.recovery_body());decision=dict(action='retry_author',reason='x'*1300,optional_files=[])
        with self.assertRaises(StructuredResponseRejected) as caught:
            translate(body,self.wire(decision,name=RECOVERY_NAME),'application/json')
        submission=caught.exception.length_feedback[0]['tool_calls'][0]['function']
        self.assertEqual(submission['name'],RECOVERY_NAME)
        self.assertEqual(json.loads(submission['arguments']),decision)

    def test_worker_recovery_proxy_records_request_without_executing_retry(self):
        import sqlite3
        from typed_decision_contract import RECOVERY_NAME
        fixture=fixtures.ReadStreamRecoveryTests();fixture.setUp()
        try:
            body=fixtures.request_body();body['messages']=self.recovery_body()['messages'][:1]
            decision=dict(action='retry_author',reason='Healthy isolated initialization.',optional_files=[])
            with patch.object(proxy,'forward',return_value=(200,self.wire(decision,name=RECOVERY_NAME),'application/json')) as forward:
                response=fixture.request(body)
            self.assertEqual(response.status,200);forward.assert_called_once()
            with sqlite3.connect(fixture.counter.with_name('deterministic-reads.sqlite')) as c:
                receipt=json.loads(c.execute('SELECT receipt FROM typed_decisions').fetchone()[0])
            self.assertEqual(receipt['mode'],'worker_recovery_request')
            self.assertFalse(receipt['author_retry_authorized']);self.assertFalse(receipt['worker_tool_executed'])
        finally:fixture.doCleanups()

    def test_runtime_diagnosis_enables_only_bounded_format_feedback(self):
        from typed_decision_contract import length_feedback_enabled
        note = ('DELIVERY_STRUCTURED_DECISION_V1:technical\n'
                'DELIVERY_EXECUTION_DIAGNOSIS_V1\nDELIVERY_TYPED_DECISION_V1\n')
        wire = apply(schema({'messages': [{'role': 'user', 'content': note}]}))
        self.assertTrue(length_feedback_enabled(wire))
        parameters = wire['tools'][0]['function']['parameters']
        self.assertEqual(parameters['properties']['reason']['maxLength'], 1200)
        self.assertEqual(parameters['properties']['action']['enum'], ['escalate_cto'])
        other = apply(schema({'messages': [{'role': 'user', 'content':
            'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'}]}))
        self.assertFalse(length_feedback_enabled(other))

    def test_bounded_technical_length_feedback_requires_new_valid_arguments(self):
        import sqlite3
        from typed_decision_contract import LENGTH_MARKER
        for good in (True,False):
            f=fixtures.ReadStreamRecoveryTests();f.setUp()
            try:
                body=fixtures.request_body();body['messages']=[{'role':'user','content':
                    'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'+LENGTH_MARKER+'\n'}]
                bad=dict(self.decision,reason='x'*1300)
                replies=[(200,self.wire(bad),'application/json'),(200,self.wire(self.decision if good else bad),'application/json')]
                with patch.object(proxy,'forward',side_effect=replies) as forward:
                    reply=f.request(body)
                self.assertEqual(reply.status,200 if good else 502);self.assertEqual(proxy.load_calls(),2)
                revised=forward.call_args_list[1].args[0]
                self.assertEqual(json.loads(revised['messages'][-2]['tool_calls'][0]['function']['arguments']),bad)
                feedback=json.loads(revised['messages'][-1]['content']);self.assertFalse(feedback['worker_tool_executed'])
                with sqlite3.connect(f.counter.with_name('deterministic-reads.sqlite')) as c:
                    self.assertEqual(c.execute('select count(*) from technical_length_feedback').fetchone()[0],1)
                    self.assertEqual(c.execute('select count(*) from typed_decision_rejections').fetchone()[0],1)
                with patch.object(proxy,'forward') as again:
                    self.assertEqual(f.request(body).status,502);again.assert_not_called()
                self.assertEqual(proxy.load_calls(),2)
            finally:f.doCleanups()

    def test_length_feedback_does_not_repair_other_schema_errors_or_unmarked_requests(self):
        from typed_decision_contract import LENGTH_MARKER
        for marked,decision in ((False,dict(self.decision,reason='x'*1300)),
                (True,dict(self.decision,reason='x'*1300,action='APPROVE'))):
            body=copy.deepcopy(self.body)
            if marked:body['messages'][0]['content']+=LENGTH_MARKER+'\n'
            with self.assertRaises(StructuredResponseRejected) as rejected:translate(body,self.wire(decision),'application/json')
            self.assertFalse(hasattr(rejected.exception,'length_feedback'))
    def test_length_feedback_supports_stream_and_cannot_exceed_call_cap(self):
        from typed_decision_contract import LENGTH_MARKER
        def stream(decision):
            frame={'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'type':'function',
                'function':{'name':NAME,'arguments':json.dumps(decision)}}]},'finish_reason':'tool_calls'}]}
            return (200,('data: '+json.dumps(frame)+'\n\ndata: [DONE]\n').encode(),'text/event-stream')
        for cap,expected_calls,status in ((2,2,200),(1,1,400)):
            f=fixtures.ReadStreamRecoveryTests();f.setUp()
            try:
                body=fixtures.request_body();body['messages']=[{'role':'user','content':
                    'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'+LENGTH_MARKER+'\n'}]
                with patch.object(proxy,'MAX_CALLS',cap),patch.object(proxy,'forward',side_effect=[stream(dict(self.decision,reason='x'*1300)),stream(self.decision)]) as forward:
                    reply=f.request(body)
                self.assertEqual(reply.status,status);self.assertEqual(forward.call_count,expected_calls)
                self.assertEqual(proxy.load_calls(),expected_calls)
            finally:f.doCleanups()

    def test_review_ascii_padding_preserves_arguments_and_all_verdict_checks(self):
        from typed_decision_contract import normalize_review_padding
        body=self.review_body();decision=dict(action='approve_test_revision',reason='Coverage checked',optional_files=[],manifest_sha256='a'*64)
        wire=json.loads(self.wire(decision,name=REVIEW_NAME));wire['choices'][0]['message']['content']=' '
        raw=json.dumps(wire).encode();normalized,receipt=normalize_review_padding(body,raw,'application/json')
        out,_,accepted=translate(body,normalized,'application/json')
        self.assertEqual(json.loads(json.loads(out)['choices'][0]['message']['content']),decision)
        self.assertEqual(receipt['padding_chars'],1)
        self.assertFalse(accepted['review_acceptance_by_proxy'])
        self.assertFalse(receipt['delivery_approval'])
        for content in ('prose','\u00a0',' '*17):
            wire['choices'][0]['message']['content']=content;raw=json.dumps(wire).encode()
            self.assertEqual(normalize_review_padding(body,raw,'application/json'),(raw,None))
        wire['choices'][0]['message']['content']=' '
        wire['choices'][0]['message']['tool_calls'][0]['function']['arguments']=json.dumps({**decision,'manifest_sha256':'b'*64})
        normalized,_=normalize_review_padding(body,json.dumps(wire).encode(),'application/json')
        with self.assertRaises(StructuredResponseRejected):translate(body,normalized,'application/json')

    def test_review_padding_is_not_applied_to_other_tools(self):
        from typed_decision_contract import normalize_review_padding
        wire=json.loads(self.wire());wire['choices'][0]['message']['content']=' '
        raw=json.dumps(wire).encode()
        self.assertEqual(normalize_review_padding(self.body,raw,'application/json'),(raw,None))

    def test_review_padding_proxy_is_opt_in_and_preserves_rejection(self):
        import os,sqlite3
        for enabled,invalid,status in ((False,False,502),(True,False,200),(True,True,502)):
            f=fixtures.ReadStreamRecoveryTests();f.setUp()
            try:
                body=fixtures.request_body();body['messages']=copy.deepcopy(self.review_body()['messages'])
                decision=dict(action='approve_test_revision',reason='Coverage checked',optional_files=[],manifest_sha256='a'*64)
                wire=json.loads(self.wire(decision,name=REVIEW_NAME));wire['choices'][0]['message']['content']=' '
                if invalid:wire['choices'][0]['message']['tool_calls'][0]['function']['arguments']='PRIVATE'
                raw=json.dumps(wire).encode()
                with patch.dict(os.environ,{'MODEL_PROXY_REVIEW_PADDING':'1' if enabled else '0'}),patch.object(proxy,'forward',return_value=(200,raw,'application/json')) as forward:
                    reply=f.request(body)
                self.assertEqual(reply.status,status);forward.assert_called_once()
                table='typed_decisions' if status==200 else 'typed_decision_rejections'
                with sqlite3.connect(f.counter.with_name('deterministic-reads.sqlite')) as con:
                    receipt=json.loads(con.execute('SELECT receipt FROM '+table).fetchone()[0])
                self.assertEqual('transport_padding' in receipt,enabled)
                if enabled:self.assertFalse(receipt['transport_padding']['review_acceptance_by_proxy'])
            finally:f.doCleanups()

    def test_proxy_padding_is_opt_in_and_preserves_rejected_origin(self):
        import os,sqlite3
        for enabled,invalid,status in ((False,False,502),(True,False,200),(True,True,502)):
            f=fixtures.ReadStreamRecoveryTests();f.setUp()
            try:
                body=fixtures.request_body();body['messages'][0]['content']='DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'
                wire=json.loads(self.wire());wire['choices'][0]['message']['content']='\n\n'
                if invalid:wire['choices'][0]['message']['tool_calls'][0]['function']['arguments']='PRIVATE'
                raw=json.dumps(wire).encode()
                with patch.dict(os.environ,{'MODEL_PROXY_TECHNICAL_PADDING':'1' if enabled else '0'}), \
                     patch.object(proxy,'forward',return_value=(200,raw,'application/json')) as forward:
                    reply=f.request(body)
                self.assertEqual(reply.status,status);forward.assert_called_once()
                table='typed_decisions' if status==200 else 'typed_decision_rejections'
                with sqlite3.connect(f.counter.with_name('deterministic-reads.sqlite')) as con:
                    receipt=json.loads(con.execute('SELECT receipt FROM '+table).fetchone()[0])
                self.assertEqual('transport_padding' in receipt,enabled)
                if enabled:
                    import hashlib
                    self.assertEqual(receipt['transport_padding']['original_upstream_sha256'],hashlib.sha256(raw).hexdigest())
                    self.assertFalse(receipt['transport_padding']['delivery_approval'])
            finally:f.doCleanups()

    def test_padding_normalizes_only_bounded_ascii_without_changing_arguments(self):
        wire=json.loads(self.wire());wire['choices'][0]['message']['content']='\n\n'
        raw=json.dumps(wire).encode();normalized,receipt=normalize_technical_padding(self.body,raw,'application/json')
        out,_,accepted=translate(self.body,normalized,'application/json')
        self.assertEqual(json.loads(json.loads(out)['choices'][0]['message']['content']),self.decision)
        self.assertEqual(receipt['padding_chars'],2);self.assertNotEqual(receipt['original_upstream_sha256'],receipt['normalized_upstream_sha256'])
        self.assertFalse(accepted['delivery_approval'])
        for content in ('PRIVATE',' '*17,'\u00a0'):
            wire['choices'][0]['message']['content']=content;raw=json.dumps(wire).encode()
            self.assertEqual(normalize_technical_padding(self.body,raw,'application/json'),(raw,None))
        wire['choices'][0]['message']['content']='\n';raw=json.dumps(wire).encode()
        self.assertEqual(normalize_technical_padding(self.review_body(),raw,'application/json'),(raw,None))

    def test_padding_does_not_bypass_stream_terminal_or_invalid_arguments(self):
        raw=self.terminal_stream({'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls'}]})
        prefix=b'data: '+json.dumps({'choices':[{'index':0,'delta':{'content':'\n\n'},'finish_reason':None}]}).encode()+b'\n\n'
        normalized,receipt=normalize_technical_padding(self.body,prefix+raw,'text/event-stream')
        self.assertEqual(receipt['padding_chars'],2);translate(self.body,normalized,'text/event-stream')
        late=raw.replace(b'data: [DONE]',prefix+b'data: [DONE]')
        self.assertEqual(normalize_technical_padding(self.body,late,'text/event-stream'),(late,None))
        wire=json.loads(self.wire());wire['choices'][0]['message']['content']='\n'
        wire['choices'][0]['message']['tool_calls'][0]['function']['arguments']='PRIVATE'
        normalized,_=normalize_technical_padding(self.body,json.dumps(wire).encode(),'application/json')
        with self.assertRaises(StructuredResponseRejected):translate(self.body,normalized,'application/json')

    def setUp(self):
        self.body=apply(schema({'messages':[{'role':'user','content':
            'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'}]}))
        self.decision={'action':'request_test_revision','reason':'Add actual negative-control tests','optional_files':[]}

    def review_body(self,findings=False,observed=False):
        sha='a'*64;path='/evidence/candidate/tests/test_new.py'
        body={'messages':[{'role':'user','content':'DELIVERY_STRUCTURED_DECISION_V1:test_review:'+sha+'\nDELIVERY_TYPED_REVIEW_V1:'+sha+'\nDELIVERY_REVIEW_READ_PATH:'+path+'\n'+('DELIVERY_TEST_FINDINGS_V1\n' if findings else '')+('DELIVERY_OBSERVED_FINDINGS_V1\n' if observed else '')},
            {'role':'assistant','tool_calls':[{'id':'r','function':{'name':'read_file','arguments':json.dumps({'path':path})}}]},
            {'role':'tool','tool_call_id':'r','content':json.dumps({'content':'1|assert value\n','total_lines':1})}]}
        return apply(schema(body))

    def test_typed_review_preserves_actual_verdict_but_does_not_accept_it(self):
        body=self.review_body();decision=dict(action='approve_test_revision',reason='Observed complete coverage',optional_files=[],manifest_sha256='a'*64)
        output,_,receipt=translate(body,self.wire(decision,name=REVIEW_NAME),'application/json')
        self.assertEqual(json.loads(json.loads(output)['choices'][0]['message']['content']),decision)
        self.assertEqual(receipt['manifest_sha256'],'a'*64)
        self.assertFalse(receipt['review_acceptance_by_proxy']);self.assertFalse(receipt['delivery_approval'])
        for key,value in [('manifest_sha256','b'*64),('action','request_test_revision'),('optional_files',['x'])]:
            with self.assertRaises(StructuredResponseRejected):translate(body,self.wire({**decision,key:value},name=REVIEW_NAME),'application/json')

    def test_review_marker_must_match_exact_structured_snapshot(self):
        body={'messages':[{'role':'user','content':'DELIVERY_STRUCTURED_DECISION_V1:test_review:'+'a'*64+'\nDELIVERY_TYPED_REVIEW_V1:'+'b'*64+'\n'}]}
        with self.assertRaises(ValueError):apply(schema(body))

    def test_review_inspection_cannot_be_replaced_by_verdict_tool(self):
        sha='a'*64
        body={'messages':[{'role':'user','content':'DELIVERY_STRUCTURED_DECISION_V1:test_review:'+sha+'\nDELIVERY_TYPED_REVIEW_V1:'+sha+'\nDELIVERY_REVIEW_READ_PATH:/evidence/candidate/test.py\n'}],
            'tools':[{'type':'function','function':{'name':'read_file','parameters':{'type':'object'}}}]}
        result=apply(schema(body))
        self.assertEqual(result['tool_choice']['function']['name'],'read_file')
        self.assertNotIn('response_format',result)

    def test_findings_schema_is_not_removed_by_typed_review(self):
        body=self.review_body(findings=True)
        decision=dict(action='approve_test_revision',reason='Observed complete coverage',optional_files=[],manifest_sha256='a'*64)
        with self.assertRaises(StructuredResponseRejected):translate(body,self.wire(decision,name=REVIEW_NAME),'application/json')
        _,_,receipt=translate(body,self.wire({**decision,'findings':[]},name=REVIEW_NAME),'application/json')
        self.assertFalse(receipt['review_acceptance_by_proxy'])
        with self.assertRaises(StructuredResponseRejected):
            translate(body,self.wire({**decision,'action':'reject_test_revision','findings':[]},name=REVIEW_NAME),'application/json')

    def test_typed_review_stream_preserves_verdict_with_duplicate_terminal(self):
        body=self.review_body();before=self.decision
        self.decision=dict(action='reject_test_revision',reason='Observed missing scenario',optional_files=[],manifest_sha256='a'*64)
        try:
            raw=self.terminal_stream({'choices':[{'index':0,'delta':{'role':'assistant','content':''},'finish_reason':'tool_calls'}]})
            raw=raw.replace(NAME.encode(),REVIEW_NAME.encode())
            output,_,receipt=translate(body,raw,'text/event-stream')
            self.assertFalse(receipt['review_acceptance_by_proxy'])
            frame=json.loads(output.decode().splitlines()[0][5:])
            self.assertEqual(json.loads(frame['choices'][0]['delta']['content']),self.decision)
            with self.assertRaises(StructuredResponseRejected):
                translate(body,raw.replace(b'data: [DONE]',b''),'text/event-stream')
        finally:self.decision=before

    def test_proxy_records_real_review_arguments_without_running_worker_tool(self):
        f=fixtures.ReadStreamRecoveryTests();f.setUp();self.addCleanup(f.doCleanups)
        wire=self.review_body(findings=True);wire['model']=proxy.MODEL
        decision=dict(action='approve_test_revision',reason='Observed complete coverage',optional_files=[],manifest_sha256='a'*64,findings=[])
        with patch.object(proxy,'forward',return_value=(200,self.wire(decision,name=REVIEW_NAME),'application/json')) as forward:
            reply=f.request(wire)
        self.assertEqual(reply.status,200);forward.assert_called_once()
        parsed=json.loads(reply.wfile.getvalue())
        self.assertNotIn('tool_calls',parsed['choices'][0]['message'])
        self.assertEqual(json.loads(parsed['choices'][0]['message']['content']),decision)
        # Transport carries the verdict unchanged; identity, actual reads and
        # snapshot/evidence acceptance remain the independent controller's job.
        import sqlite3
        with sqlite3.connect(f.counter.with_name('deterministic-reads.sqlite')) as con:
            receipt=json.loads(con.execute('SELECT receipt FROM typed_decisions').fetchone()[0])
        self.assertFalse(receipt['review_acceptance_by_proxy'])
        self.assertFalse(receipt['worker_tool_executed'])

    def wire(self,decision=None,name=NAME):
        args=json.dumps(self.decision if decision is None else decision)
        return json.dumps({'choices':[{'message':{'content':None,'tool_calls':[{'type':'function',
            'function':{'name':name,'arguments':args}}]},'finish_reason':'tool_calls'}]}).encode()

    def test_only_explicit_technical_marker_selects_typed_operation(self):
        self.assertEqual(len(self.body['tools']),1)
        self.assertNotIn('response_format',self.body)
        plain={'messages':[{'role':'user','content':'ordinary chat'}]}
        self.assertIs(apply(plain),plain)

    def test_typed_technical_diagnosis_preserves_mandatory_artifact_reads(self):
        path='/evidence/candidate/tests/test_new.py'
        body={'messages':[{'role':'user','content':
            'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'
            'DELIVERY_REVIEW_READ_PATH:'+path+'\n'}],
            'tools':[{'type':'function','function':{'name':'read_file'}}]}
        inspecting=schema(body)
        self.assertEqual(inspecting['tool_choice']['function']['name'],'read_file')
        self.assertIs(apply(inspecting),inspecting)
        self.assertNotIn('response_format',inspecting)
        self.assertNotIn(NAME,[t['function']['name'] for t in inspecting['tools']])

    def test_valid_arguments_preserved_not_tool_execution_or_approval(self):
        output,media,receipt=translate(self.body,self.wire(),'application/json')
        self.assertEqual(json.loads(json.loads(output)['choices'][0]['message']['content']),self.decision)
        self.assertFalse(receipt['worker_tool_executed']);self.assertFalse(receipt['delivery_approval'])
        self.assertTrue(receipt['model_values_preserved'])

    def test_wrong_tool_schema_permissions_and_prose_rejected(self):
        for raw in [self.wire(name='terminal'),self.wire({**self.decision,'action':'approve'}),
            self.wire({**self.decision,'optional_files':['tests/old.py']}),self.wire({**self.decision,'reason':'x'*1201})]:
            with self.assertRaises(StructuredResponseRejected):translate(self.body,raw,'application/json')
        prose=json.dumps({'choices':[{'message':{'content':json.dumps(self.decision)},'finish_reason':'stop'}]}).encode()
        with self.assertRaises(StructuredResponseRejected):translate(self.body,prose,'application/json')

    def test_typed_rejection_exports_constraints_without_values_or_paths(self):
        body=copy.deepcopy(self.body)
        spec=body['tools'][0]['function']['parameters']
        spec['properties']['reason']={'anyOf':[{'type':'string','maxLength':2},
            {'type':'integer'}]}
        raw=self.wire({**self.decision,'reason':'PRIVATE_SENTINEL_VALUE'})
        with self.assertRaises(StructuredResponseRejected) as caught:
            translate(body,raw,'application/json')
        diagnostic=caught.exception.diagnostic
        self.assertEqual(diagnostic['constraints'],['anyOf','maxLength','type'])
        self.assertEqual(diagnostic['version'],'typed-constraint-v1')
        self.assertEqual(diagnostic['upstream_sha256'],caught.exception.receipt['upstream_sha256'])
        self.assertEqual(caught.exception.receipt['constraint_diagnostic'],diagnostic)
        encoded=json.dumps(caught.exception.receipt)
        self.assertNotIn('PRIVATE_SENTINEL_VALUE',encoded)
        self.assertNotIn('reason',encoded)
        self.assertFalse(caught.exception.receipt['worker_tool_executed'])
        self.assertFalse(caught.exception.receipt['delivery_approval'])

    def test_rejection_distinguishes_root_failures_without_exporting_instance_paths(self):
        from typed_decision_contract import constraint_diagnostic
        from jsonschema import Draft202012Validator
        schema={'type':'object','properties':{
            'findings':{'type':'array','maxItems':3,'items':{'anyOf':[
                {'type':'object','properties':{'quote':{'enum':['PRIVATE_EXPECTED']}},'required':['quote']}]}}
        }}
        bad={'findings':[{'quote':'PRIVATE_ACTUAL'}]*4}
        d=constraint_diagnostic(list(Draft202012Validator(schema).iter_errors(bad)),schema,b'private-wire')
        self.assertEqual(d['root_constraints'],['anyOf','maxItems'])
        self.assertEqual(d['locations'],['finding_count','finding_location_selection'])
        encoded=json.dumps(d)
        for private in ('PRIVATE_EXPECTED','PRIVATE_ACTUAL','quote','private-wire'):
            self.assertNotIn(private,encoded)

    def test_alternative_branch_failures_are_not_reported_as_root_finding_count(self):
        from typed_decision_contract import constraint_diagnostic
        from jsonschema import Draft202012Validator
        schema={'anyOf':[{'properties':{'findings':{'maxItems':0},'action':{'enum':['approve']}}},
            {'properties':{'action':{'enum':['reject']}}}]}
        bad={'action':'unknown','findings':[{}]}
        d=constraint_diagnostic(list(Draft202012Validator(schema).iter_errors(bad)),schema,b'wire')
        self.assertEqual(d['root_constraints'],['anyOf'])
        self.assertIn('maxItems',d['constraints'])
        self.assertEqual(d['locations'],[])

    def test_constraint_receipt_is_durable_and_never_repairs_a_decision(self):
        from typed_decision_contract import record
        from deterministic_read_dispatch import ledger
        with self.assertRaises(StructuredResponseRejected) as caught:
            translate(self.body,self.wire({**self.decision,'action':'PRIVATE_INVALID'}),'application/json')
        self.assertEqual(caught.exception.diagnostic['constraints'],['enum'])
        self.assertFalse(hasattr(caught.exception,'length_feedback'))
        f=fixtures.ReadStreamRecoveryTests();f.setUp();self.addCleanup(f.doCleanups)
        execution='19372d53-18ed-4104-b534-c03a556ad353'
        record(f.counter,execution,caught.exception.receipt)
        record(f.counter,execution,caught.exception.receipt)
        with ledger(f.counter) as con:
            rows=con.execute('SELECT receipt FROM typed_decision_rejections').fetchall()
        self.assertEqual(len(rows),1)
        self.assertEqual(json.loads(rows[0][0]),caught.exception.receipt)
        self.assertNotIn('PRIVATE_INVALID',json.dumps(caught.exception.receipt))

    def test_no_review_approval_schema_can_be_converted_to_typed_submission(self):
        body={'messages':[{'role':'user','content':'DELIVERY_TYPED_DECISION_V1\n'}],
            'response_format':{'type':'json_schema','json_schema':{'name':'delivery_decision_v1','schema':{
                'properties':{'action':{'enum':['approve_test_revision']}}}}}}
        with self.assertRaises(ValueError):apply(body)

    def test_streamed_arguments_are_assembled_and_missing_terminal_rejected(self):
        args=json.dumps(self.decision)
        frames=[{'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'type':'function','function':{'name':NAME,'arguments':args[:20]}}]},'finish_reason':None}]},
            {'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'function':{'arguments':args[20:]}}]},'finish_reason':None}]},
            {'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls'}]}]
        raw=(''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n').encode()
        output,_,receipt=translate(self.body,raw,'text/event-stream')
        self.assertTrue(receipt['model_values_preserved']);self.assertIn(b'"finish_reason": "stop"',output)
        with self.assertRaises(StructuredResponseRejected):translate(self.body,raw.replace(b'data: [DONE]',b''),'text/event-stream')

    def terminal_stream(self,terminal):
        frames=[{'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'function':{'name':NAME,'arguments':json.dumps(self.decision)}}]},'finish_reason':None}]},
                {'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls'}]},terminal]
        return (''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n').encode()

    def test_repeated_empty_identical_terminal_is_transport_idempotence(self):
        raw=self.terminal_stream({'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls'}]})
        output,_,receipt=translate(self.body,raw,'text/event-stream')
        self.assertTrue(receipt['model_values_preserved'])
        frames=[json.loads(line[5:]) for line in output.decode().splitlines() if line.startswith('data: {')]
        self.assertEqual(json.loads(frames[0]['choices'][0]['delta']['content']),self.decision)
        self.assertEqual(len(frames),2)

    def test_different_repeated_terminal_and_terminal_payload_remain_rejected(self):
        for terminal in [{'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]},
                         {'choices':[{'index':0,'delta':{'role':'system'},'finish_reason':'tool_calls'}]},
                         {'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'function':{'arguments':'{}'}}]},'finish_reason':'tool_calls'}]}]:
            with self.assertRaises(StructuredResponseRejected):
                translate(self.body,self.terminal_stream(terminal),'text/event-stream')

    def test_nullable_empty_terminal_fields_do_not_constitute_new_payload(self):
        terminal={'choices':[{'index':0,'delta':{'role':'assistant','content':None,'tool_calls':[], 'function_call':None},'finish_reason':'tool_calls'}]}
        _,_,receipt=translate(self.body,self.terminal_stream(terminal),'text/event-stream')
        self.assertTrue(receipt['model_values_preserved'])
        for delta in [{'content':'new payload'},{'tool_calls':[{}]},{'unknown':None}]:
            terminal['choices'][0]['delta']=delta
            with self.assertRaises(StructuredResponseRejected):
                translate(self.body,self.terminal_stream(terminal),'text/event-stream')

    def test_proxy_records_typed_arguments_before_forwarding_without_worker_tool(self):
        f=fixtures.ReadStreamRecoveryTests();f.setUp();self.addCleanup(f.doCleanups)
        wire=fixtures.request_body();wire['messages'][0]['content']='DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'
        with patch.object(proxy,'forward',return_value=(200,self.wire(),'application/json')) as forward:
            reply=f.request(wire)
        self.assertEqual(reply.status,200);forward.assert_called_once()
        parsed=json.loads(reply.wfile.getvalue())
        self.assertNotIn('tool_calls',parsed['choices'][0]['message'])
        self.assertEqual(json.loads(parsed['choices'][0]['message']['content']),self.decision)
        import sqlite3
        with sqlite3.connect(f.counter.with_name('deterministic-reads.sqlite')) as con:
            rows=con.execute('SELECT receipt FROM typed_decisions').fetchall()
        self.assertEqual(len(rows),1)
        self.assertFalse(json.loads(rows[0][0])['worker_tool_executed'])
        self.assertNotIn(self.decision['reason'],rows[0][0])

    def test_proxy_rejects_prose_under_typed_contract_without_retry(self):
        f=fixtures.ReadStreamRecoveryTests();f.setUp();self.addCleanup(f.doCleanups)
        wire=fixtures.request_body();wire['messages'][0]['content']='DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'
        raw=json.dumps({'choices':[{'message':{'content':'PRIVATE_PROVIDER_ERROR'},'finish_reason':'stop'}]}).encode()
        with patch.object(proxy,'forward',return_value=(200,raw,'application/json')) as forward:
            reply=f.request(wire)
        self.assertEqual(reply.status,502);forward.assert_called_once()

    def test_rejection_categories_are_precise_and_do_not_leak_values(self):
        cases=[(self.wire(name='PRIVATE_TOOL'),'typed_wrong_tool_name'),
            (self.wire({**self.decision,'reason':'PRIVATE'*200}),'typed_schema_maxLength'),
            (self.wire({**self.decision,'optional_files':['PRIVATE']}),'typed_schema_maxItems'),
            (self.wire({**self.decision,'action':'PRIVATE'}),'typed_schema_enum')]
        for raw,expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaises(StructuredResponseRejected) as raised:
                    translate(self.body,raw,'application/json')
                self.assertEqual(raised.exception.category,expected)
                self.assertNotIn('PRIVATE',json.dumps(raised.exception.receipt))
                self.assertFalse(raised.exception.receipt['delivery_approval'])

    def test_mixed_content_is_still_rejected_even_with_valid_tool_arguments(self):
        wire=json.loads(self.wire());wire['choices'][0]['message']['content']='PRIVATE'
        with self.assertRaises(StructuredResponseRejected) as raised:
            translate(self.body,json.dumps(wire).encode(),'application/json')
        self.assertEqual(raised.exception.category,'typed_mixed_content')
        shape=raised.exception.receipt['response_shape']
        self.assertTrue(shape['arguments_schema_valid']);self.assertTrue(shape['expected_tool'])
        self.assertEqual(shape['content_shape'],'nonempty')
        self.assertNotIn('PRIVATE',json.dumps(raised.exception.receipt))

    def test_shape_metrics_distinguish_absent_and_invalid_submission_without_acceptance(self):
        wire=json.loads(self.wire());wire['choices'][0]['message']['tool_calls']=[]
        shape=response_shape(self.body,json.dumps(wire).encode(),'application/json')
        self.assertEqual(shape['submissions'],0);self.assertIsNone(shape['arguments_json_valid'])
        wire=json.loads(self.wire());wire['choices'][0]['message']['tool_calls'][0]['function']['arguments']='PRIVATE'
        shape=response_shape(self.body,json.dumps(wire).encode(),'application/json')
        self.assertFalse(shape['arguments_json_valid']);self.assertNotIn('PRIVATE',json.dumps(shape))
        wire=json.loads(self.wire());wire['choices'][0]['message']['content']=' \n'
        shape=response_shape(self.body,json.dumps(wire).encode(),'application/json')
        self.assertEqual(shape['content_shape'],'whitespace_only')
        with self.assertRaises(StructuredResponseRejected):translate(self.body,json.dumps(wire).encode(),'application/json')

    def test_stream_shape_assembles_arguments_but_still_rejects_extra_text(self):
        raw=self.terminal_stream({'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls'}]})
        prefix=b'data: '+json.dumps({'choices':[{'index':0,'delta':{'content':'PRIVATE'},'finish_reason':None}]}).encode()+b'\n\n'
        with self.assertRaises(StructuredResponseRejected) as raised:translate(self.body,prefix+raw,'text/event-stream')
        shape=raised.exception.receipt['response_shape']
        self.assertTrue(shape['terminal']);self.assertTrue(shape['arguments_schema_valid'])
        self.assertEqual(shape['submissions'],1);self.assertNotIn('PRIVATE',json.dumps(shape))

    def test_invalid_arguments_and_invalid_envelope_are_distinguishable(self):
        wire=json.loads(self.wire());wire['choices'][0]['message']['tool_calls'][0]['function']['arguments']='PRIVATE'
        for raw,category in [(json.dumps(wire).encode(),'typed_arguments_invalid'),
                             (b'PRIVATE','typed_envelope_invalid')]:
            with self.assertRaises(StructuredResponseRejected) as raised:
                translate(self.body,raw,'application/json')
            self.assertEqual(raised.exception.category,category)

    def test_proxy_rejection_has_durable_receipt_but_no_accepted_decision(self):
        f=fixtures.ReadStreamRecoveryTests();f.setUp();self.addCleanup(f.doCleanups)
        wire=fixtures.request_body();wire['messages'][0]['content']='DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'
        with patch.object(proxy,'forward',return_value=(200,self.wire(name='PRIVATE'),'application/json')) as forward:
            reply=f.request(wire)
        self.assertEqual(reply.status,502);forward.assert_called_once()
        import sqlite3
        with sqlite3.connect(f.counter.with_name('deterministic-reads.sqlite')) as con:
            rows=con.execute('SELECT receipt FROM typed_decision_rejections').fetchall()
            accepted=con.execute("SELECT name FROM sqlite_master WHERE name='typed_decisions'").fetchall()
        self.assertEqual(len(rows),1);self.assertFalse(accepted)
        self.assertEqual(json.loads(rows[0][0])['category'],'typed_wrong_tool_name')
        self.assertNotIn('PRIVATE',rows[0][0])

    def test_rejection_receipt_failure_does_not_forward_response_or_retry(self):
        f=fixtures.ReadStreamRecoveryTests();f.setUp();self.addCleanup(f.doCleanups)
        wire=fixtures.request_body();wire['messages'][0]['content']='DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'
        with patch.object(proxy,'forward',return_value=(200,self.wire(name='PRIVATE'),'application/json')) as forward, \
             patch.object(proxy.typed_decision_contract,'record',side_effect=OSError('PRIVATE')):
            reply=f.request(wire)
        self.assertEqual(reply.status,503);forward.assert_called_once()
        self.assertNotIn(b'PRIVATE',reply.wfile.getvalue())
