import copy
import json
from unittest.mock import patch
import unittest

import deterministic_read_dispatch as dispatch
from artifact_read_evidence import observations
from artifact_response_contract import validate
import model_proxy as proxy
import test_read_stream_recovery as fixtures
request_body=fixtures.request_body
EXECUTION=fixtures.EXECUTION


class DeterministicReadTests(unittest.TestCase):
    def test_seeded_200_line_read_is_supported_end_to_end_without_paid_call(self):
        wire=self.author_body();target='/workspace/tests/test_new.py'
        wire['messages'][0]['content']+='DELIVERY_TEST_REVISION_V1:'+target+'\nDELIVERY_SEEDED_EDIT_REQUIRED_V1:'+target+'\n'
        wire['tools'].append({'type':'function','function':{'name':'patch','parameters':{}}})
        with patch.object(proxy,'forward') as forward:reply=self.f.request(wire)
        self.assertEqual(reply.status,200);forward.assert_not_called()
        prepared=proxy.validate_request(copy.deepcopy(wire))
        self.assertIsNotNone(dispatch.artifact_identity(prepared,EXECUTION))
        validate(prepared,reply.wfile.getvalue(),'text/event-stream')
        self.assertEqual(proxy.load_calls(),0)

    def test_200_line_read_without_exact_seeded_marker_is_rejected(self):
        prepared=proxy.validate_request(self.author_body())
        read=next(t['function'] for t in prepared['tools'] if t['function']['name']=='read_file')
        read['parameters']['properties']['limit']['enum']=[200]
        self.assertIsNone(dispatch.artifact_identity(prepared,EXECUTION))
    def author_body(self):
        body=request_body()
        body['messages']=[{'role':'user','content':'DELIVERY_TEST_ARTIFACT_V1:/workspace/tests/test_new.py\nDELIVERY_TEST_SOURCE_V1:/workspace/app.py\nDELIVERY_DETERMINISTIC_READ_V1\n'}]
        body['tools']=[{'type':'function','function':{'name':n,'parameters':{}}} for n in ('read_file','write_file')]
        body['tools'][1]['function']['parameters']=dict(type='object',properties=dict(path=dict(type='string'),content=dict(type='string')))
        return body

    def test_author_fixed_read_is_real_tool_request_without_model_or_read_evidence(self):
        wire=self.author_body()
        with patch.object(proxy,'forward') as forward:reply=self.f.request(wire)
        self.assertEqual(reply.status,200);forward.assert_not_called()
        prepared=proxy.validate_request(copy.deepcopy(wire));validate(prepared,reply.wfile.getvalue(),'text/event-stream')
        self.assertEqual(observations([{'role':'assistant','content':reply.wfile.getvalue().decode()}],wire=True),{})
        self.assertEqual(proxy.load_calls(),0)

    def test_author_write_still_requires_actual_read_and_calls_model(self):
        wire=self.author_body();args=dict(path='/workspace/app.py',offset=1,limit=50)
        wire['messages'] += [dict(role='assistant',tool_calls=[dict(id='read',function=dict(name='read_file',arguments=json.dumps(args)))]),
                            dict(role='tool',tool_call_id='read',content=json.dumps(dict(content='1|VALUE=0',total_lines=1)))]
        body=proxy.validate_request(copy.deepcopy(wire))
        self.assertEqual(body['tool_choice']['function']['name'],'write_file')
        self.assertIsNone(dispatch.make(body,EXECUTION))
        data=json.dumps({'choices':[{'message':{'tool_calls':[{'function':{'name':'write_file','arguments':json.dumps(dict(path='/workspace/tests/test_new.py',content='def test_value():\n    assert False\n'))}}]},'finish_reason':'tool_calls'}]}).encode()
        with patch.object(proxy,'forward',return_value=(200,data,'application/json')) as forward:reply=self.f.request(wire)
        self.assertEqual(reply.status,200);forward.assert_called_once();self.assertEqual(proxy.load_calls(),1)

    def seeded_body(self):
        body=self.author_body()
        target='/workspace/tests/test_new.py'
        body['messages'][0]['content']+='DELIVERY_TEST_REVISION_V1:'+target+'\n'
        body['messages'] += [dict(role='assistant',tool_calls=[dict(id='src',function=dict(name='read_file',
            arguments=json.dumps(dict(path='/workspace/app.py',offset=1,limit=50))))]),
            dict(role='tool',tool_call_id='src',content=json.dumps(dict(content='1|VALUE=0',total_lines=1)))]
        return body

    def test_seeded_target_read_executes_locally_without_upstream_call(self):
        wire=self.seeded_body()
        with patch.object(proxy,'forward') as forward:reply=self.f.request(wire)
        self.assertEqual(reply.status,200);forward.assert_not_called()
        body=proxy.validate_request(copy.deepcopy(wire))
        dispatch.make(body,EXECUTION)
        self.assertEqual(body['tools'][0]['function']['parameters']['properties']['path']['enum'],
            ['/workspace/tests/test_new.py'])
        self.assertEqual(proxy.load_calls(),0)

    def test_after_complete_seed_read_requests_go_to_real_model(self):
        wire=self.seeded_body()
        wire['messages'] += [dict(role='assistant',tool_calls=[dict(id='seed',function=dict(name='read_file',
            arguments=json.dumps(dict(path='/workspace/tests/test_new.py',offset=1,limit=50))))]),
            dict(role='tool',tool_call_id='seed',content=json.dumps(dict(content='1|def test_old(): pass',total_lines=1)))]
        prepared=proxy.validate_request(copy.deepcopy(wire))
        self.assertIsNone(dispatch.make(prepared,EXECUTION))
        with patch.object(proxy,'forward',return_value=(200,
            b'{"choices":[{"message":{"content":"fixture model response"},"finish_reason":"stop"}]}',
            'application/json')) as forward:reply=self.f.request(wire)
        self.assertEqual(reply.status,200);forward.assert_called_once()
        self.assertEqual(proxy.load_calls(),1)

    def test_seed_revision_cannot_whitelist_other_paths_or_mismatched_markers(self):
        body=proxy.validate_request(self.seeded_body())
        body['tools'][0]['function']['parameters']['properties']['path']['enum']=['/workspace/tests/test_secret.py']
        with self.assertRaisesRegex(ValueError,'contract'):dispatch.make(body,EXECUTION)
        body=proxy.validate_request(self.seeded_body())
        body['messages'][0]['content']=body['messages'][0]['content'].replace(
            'DELIVERY_TEST_REVISION_V1:/workspace/tests/test_new.py',
            'DELIVERY_TEST_REVISION_V1:/workspace/tests/test_other.py')
        with self.assertRaisesRegex(ValueError,'contract'):dispatch.make(body,EXECUTION)

    def test_seeded_revision_paging_stays_local_until_full_historic_test_read(self):
        wire=self.seeded_body()
        wire['messages'] += [dict(role='assistant',tool_calls=[dict(id='seed1',function=dict(name='read_file',
            arguments=json.dumps(dict(path='/workspace/tests/test_new.py',offset=1,limit=50))))]),
            dict(role='tool',tool_call_id='seed1',content=json.dumps(dict(
                content='\n'.join(str(i)+'|fixture' for i in range(1,51)),total_lines=51)))]
        prepared=proxy.validate_request(copy.deepcopy(wire))
        self.assertEqual(prepared['tool_choice']['function']['name'],'read_file')
        self.assertEqual(prepared['tools'][0]['function']['parameters']['properties']['offset']['enum'],[51])
        with patch.object(proxy,'forward') as forward:reply=self.f.request(wire)
        self.assertEqual(reply.status,200);forward.assert_not_called()
        self.assertEqual(proxy.load_calls(),0)

    def test_author_exact_read_rejects_other_paths_pages_and_missing_authorization(self):
        body=proxy.validate_request(self.author_body())
        for key,value in [('path','/workspace/secret'),('offset',0),('limit',100)]:
            changed=copy.deepcopy(body);changed['tools'][0]['function']['parameters']['properties'][key]['enum']=[value]
            with self.assertRaisesRegex(ValueError,'contract'):dispatch.make(changed,EXECUTION)
        body['messages'][0]['content']=body['messages'][0]['content'].replace('DELIVERY_DETERMINISTIC_READ_V1\n','')
        self.assertIsNone(dispatch.make(body,EXECUTION))

    def setUp(self):
        f=fixtures.ReadStreamRecoveryTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f
        self.body=request_body()
        self.body['messages'][0]['content']+='DELIVERY_DETERMINISTIC_READ_V1\n'

    def test_controller_dispatch_executes_no_model_call_and_is_not_inspection_evidence(self):
        with patch.object(proxy,'forward') as forward:
            reply=self.f.request(self.body)
        self.assertEqual(reply.status,200);forward.assert_not_called();self.assertEqual(proxy.load_calls(),0)
        body=proxy.validate_request(copy.deepcopy(self.body));validate(body,reply.wfile.getvalue(),'text/event-stream')
        self.assertEqual(observations([{'role':'assistant','content':reply.wfile.getvalue().decode()}],wire=True),{})
        self.assertEqual(dispatch.status(str(self.f.counter),EXECUTION)['controller_read_requests'],1)

    def test_decision_opens_only_after_actual_result_and_still_calls_the_model(self):
        self.f.request(self.body)
        read={'path':'/evidence/candidate/app.py','offset':1,'limit':100}
        self.body['messages'] += [
            {'role':'assistant','tool_calls':[{'id':'r','function':{'name':'read_file','arguments':json.dumps(read)}}]},
            {'role':'tool','tool_call_id':'r','content':json.dumps({'content':'1|VALUE=0','total_lines':1})}]
        value=(200,json.dumps({'choices':[{'message':{'content':json.dumps({
            'action':'request_test_revision','reason':'Fixture requires a new test revision','optional_files':[]})},
            'finish_reason':'stop'}]}).encode(),'application/json')
        with patch.object(proxy,'forward',return_value=value) as forward:reply=self.f.request(self.body)
        self.assertEqual(reply.status,200);forward.assert_called_once();self.assertEqual(proxy.load_calls(),1)
        self.assertEqual(forward.call_args.args[0]['tool_choice'],'none')
        self.assertIn('response_format',forward.call_args.args[0])

    def test_dispatches_are_idempotent_and_no_payload_or_source_is_persisted(self):
        body=proxy.validate_request(copy.deepcopy(self.body));d=dispatch.make(body,EXECUTION)
        dispatch.record(str(self.f.counter),d);dispatch.record(str(self.f.counter),d)
        self.assertEqual(dispatch.status(str(self.f.counter),EXECUTION)['controller_read_requests'],1)
        raw=self.f.counter.with_name('deterministic-reads.sqlite').read_bytes()
        self.assertNotIn(b'/evidence/candidate/app.py',raw)
        with self.assertRaisesRegex(ValueError,'identity drift'):dispatch.record(str(self.f.counter),{**d,'data':b'changed'})

    def test_paging_advances_only_from_real_read_receipts(self):
        body=proxy.validate_request(copy.deepcopy(self.body))
        first=dispatch.make(body,EXECUTION)
        read={'path':'/evidence/candidate/app.py','offset':1,'limit':100}
        wire=copy.deepcopy(self.body)
        wire['messages'] += [{'role':'assistant','tool_calls':[{'id':'r','function':{'name':'read_file','arguments':json.dumps(read)}}]},
            {'role':'tool','tool_call_id':'r','content':json.dumps({'content':'\n'.join(str(i)+'|line' for i in range(1,101)),'total_lines':101})}]
        next_body=proxy.validate_request(wire)
        self.assertEqual(next_body['tools'][0]['function']['parameters']['properties']['offset']['enum'],[101])
        second=dispatch.make(next_body,EXECUTION)
        self.assertNotEqual(first['dispatch_id'],second['dispatch_id'])

    def test_old_contracts_and_writes_are_not_synthesized_and_bad_read_fails_closed(self):
        old=proxy.validate_request(request_body());self.assertIsNone(dispatch.make(old,EXECUTION))
        body=proxy.validate_request(copy.deepcopy(self.body))
        for choice in ('auto','none',{'type':'function','function':{'name':'write_file'}}):
            self.assertIsNone(dispatch.make({**body,'tool_choice':choice},EXECUTION))
        with self.assertRaisesRegex(ValueError,'contract'):dispatch.make(body,None)
        body['tools'][0]['function']['parameters']['properties']['path']['enum']=['/workspace/key']
        with self.assertRaisesRegex(ValueError,'contract'):dispatch.make(body,EXECUTION)

    def test_no_durable_storage_means_no_dispatch_even_during_payment_pause(self):
        with patch.object(proxy,'COUNTER_PATH',None),patch.object(proxy,'forward') as forward:
            h=self.f.request(self.body)
        self.assertEqual(h.status,503);forward.assert_not_called()
        with patch.object(proxy,'PROVIDER_PAUSE',{'category':'fixture_pause'}),patch.object(proxy,'forward') as forward:
            h=self.f.request(self.body)
        self.assertEqual(h.status,200);forward.assert_not_called()

    def test_nonstream_dispatch_has_the_same_exact_read_parameters(self):
        self.body['stream']=False
        body=proxy.validate_request(copy.deepcopy(self.body));d=dispatch.make(body,EXECUTION)
        self.assertEqual(d['media_type'],'application/json');validate(body,d['data'],d['media_type'])
        call=json.loads(d['data'])['choices'][0]['message']['tool_calls'][0]
        self.assertEqual(json.loads(call['function']['arguments']),{'path':'/evidence/candidate/app.py','offset':1,'limit':100})
