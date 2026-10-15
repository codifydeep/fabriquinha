import copy
import json
import unittest
import diagnostic_control_transport as transport
import calibration_response_contract as contract
from structured_response_contract import validate,StructuredResponseRejected
import test_calibration_response_contract as samples


class DiagnosticTransportTests(unittest.TestCase):
    def body(self,complete=True):
        body=samples.CalibrationContractTests().body(complete=complete);body['model']='anthropic/claude-haiku-5.5'
        body['messages'][0]['content']+='\n'+transport.MARKER+':'+'a'*64+'\n'
        return contract.apply(body)

    def response(self,value,*,name=None,stream=False,finish='tool_calls',content=None):
        args=value if isinstance(value,str) else json.dumps(value)
        call=dict(id='data-carrier',type='function',function=dict(name=name or transport.NAME,arguments=args))
        message=dict(role='assistant',content=content,tool_calls=[call])
        if not stream:return json.dumps(dict(choices=[dict(index=0,message=message,finish_reason=finish)])).encode(),'application/json'
        frame=dict(choices=[dict(index=0,delta={**message,'tool_calls':[{**call,'index':0}]},finish_reason=finish)])
        return ('data: '+json.dumps(frame)+'\n\ndata: [DONE]\n\n').encode(),'text/event-stream'

    def value(self):return dict(action='calibration_objection',reason='Synthetic only',execution_authorized=False,delivery_approval=False)

    def test_wire_projection_is_opt_in_after_full_reads_and_never_changes_canonical_schema(self):
        body=self.body();before=copy.deepcopy(body);wire=transport.project(body)
        self.assertEqual(body,before);self.assertEqual(wire['tool_choice'],'required')
        self.assertFalse(wire['parallel_tool_calls']);self.assertNotIn('response_format',wire)
        self.assertEqual([t['function']['name'] for t in wire['tools']],['read_file',transport.NAME])
        self.assertNotIn('anyOf',json.dumps(wire['tools'][-1]))
        self.assertIsNone(transport.project(self.body(False)))
        no_marker=copy.deepcopy(body);no_marker['messages'][0]['content']=no_marker['messages'][0]['content'].split('\n'+transport.MARKER)[0]
        self.assertIsNone(transport.project(no_marker))

    def test_validated_arguments_are_a_data_carrier_not_a_worker_tool_call(self):
        for stream in (False,True):
            body=self.body();arguments='  '+json.dumps(self.value())+'  '
            data,media=self.response(arguments,stream=stream)
            translated,out_media,receipt=transport.translate(body,data,media)
            validate(body,translated,out_media)
            if out_media=='application/json':text=json.loads(translated)['choices'][0]['message']['content']
            else:text=''.join(json.loads(line[5:])['choices'][0]['delta'].get('content','') for line in translated.decode().splitlines() if line.startswith('data: {'))
            self.assertEqual(text,arguments)
            self.assertFalse(receipt['worker_tool_executed']);self.assertFalse(receipt['execution_authorized']);self.assertFalse(receipt['delivery_approval'])

    def test_authority_forgery_invalid_json_and_mixed_or_nonterminal_data_are_refused(self):
        body=self.body()
        variants=[self.response({**self.value(),'delivery_approval':True}),self.response('not JSON'),
            self.response(self.value(),finish='length'),self.response(self.value(),content='extra prose'),
            self.response(self.value(),name='terminal'),self.response('{"action":"calibration_objection","action":"other"}')]
        for data,media in variants:
            with self.assertRaises((ValueError,StructuredResponseRejected)):transport.translate(body,data,media)

    def test_actual_extra_read_is_forwarded_unchanged_and_validated_normally(self):
        body=self.body();data,media=self.response(dict(path='/evidence/candidate/app/value.txt',offset=1,limit=100),name='read_file')
        result,out_media,receipt=transport.translate(body,data,media)
        self.assertEqual(result,data);self.assertEqual(out_media,media);self.assertIsNone(receipt)
        validate(body,result,out_media)

    def test_capsule_or_registry_forgery_cannot_select_the_transport(self):
        body=self.body();body['messages'][0]['content']=body['messages'][0]['content'].replace(transport.MARKER+':'+'a'*64,transport.MARKER+':'+'b'*64)
        with self.assertRaises(ValueError):transport.project(body)

    def test_truncated_stream_or_payload_after_terminal_cannot_be_a_data_submission(self):
        body=self.body();raw,media=self.response(self.value(),stream=True)
        for invalid in (raw.replace(b'data: [DONE]',b''),raw.replace(b'data: [DONE]',raw)):
            with self.assertRaises(StructuredResponseRejected):transport.translate(body,invalid,media)

    def test_readiness_cannot_be_forced_by_changing_only_the_tool_choice(self):
        body=self.body(False);body['tool_choice']='auto'
        with self.assertRaises(ValueError):transport.project(body)

    def test_real_proxy_handler_validates_carrier_and_restores_requested_stream_without_executing_it(self):
        import model_proxy as proxy
        import test_read_stream_recovery as fixtures
        from unittest.mock import patch
        for stream in (False,True):
            f=fixtures.ReadStreamRecoveryTests();f.setUp();self.addCleanup(f.doCleanups)
            body=self.body();body['stream']=stream;data,media=self.response(self.value())
            with patch.object(proxy,'MODEL','anthropic/claude-haiku-5.5'),patch.object(proxy,'forward',return_value=(200,data,media)) as upstream:
                response=f.request(body)
            self.assertEqual(response.status,200);upstream.assert_called_once()
            self.assertNotIn(transport.NAME.encode(),response.wfile.getvalue())
            if stream:self.assertIn(b'data: [DONE]',response.wfile.getvalue())

    def test_proxy_does_not_retry_or_forward_a_carrier_with_forged_approval(self):
        import model_proxy as proxy
        import test_read_stream_recovery as fixtures
        from unittest.mock import patch
        f=fixtures.ReadStreamRecoveryTests();f.setUp();self.addCleanup(f.doCleanups)
        body=self.body();data,media=self.response({**self.value(),'delivery_approval':True})
        with patch.object(proxy,'MODEL','anthropic/claude-haiku-5.5'),patch.object(proxy,'forward',return_value=(200,data,media)) as upstream:
            response=f.request(body)
        self.assertEqual(response.status,502);upstream.assert_called_once();self.assertNotIn(b'Synthetic only',response.wfile.getvalue())

    def test_fixed_probe_qualifies_only_the_adapter_not_model_execution_or_delivery(self):
        import diagnostic_control_transport_probe as probe
        result=probe.run();self.assertTrue(result['passed']);self.assertEqual(set(result['checks']),probe.CHECKS)
        self.assertEqual(result['model_calls'],0);self.assertFalse(result['historical_cause_proven']);self.assertFalse(result['delivery_approval'])

    def test_stream_fragments_with_null_optional_id_and_type_keep_literal_arguments(self):
        args=json.dumps(self.value());frames=[dict(choices=[dict(index=0,delta=dict(tool_calls=[dict(index=0,id='carrier',type='function',
            function=dict(name=transport.NAME,arguments=args[:20]))]),finish_reason=None)]),
            dict(choices=[dict(index=0,delta=dict(tool_calls=[dict(index=0,id=None,type=None,function=dict(name=None,arguments=args[20:]))]),finish_reason=None)]),
            dict(choices=[dict(index=0,delta={},finish_reason='tool_calls')])]
        raw=(''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n').encode()
        translated,media,receipt=transport.translate(self.body(),raw,'text/event-stream');validate(self.body(),translated,media)
        self.assertEqual(receipt['arguments_sha256'],__import__('hashlib').sha256(args.encode()).hexdigest())

    def test_durable_receipt_has_no_payload_text_and_cannot_drift_or_claim_execution(self):
        import tempfile
        from pathlib import Path
        execution='11111111-1111-4111-8111-111111111111';data,media=self.response(self.value())
        _,_,receipt=transport.translate(self.body(),data,media)
        with tempfile.TemporaryDirectory() as folder:
            counter=str(Path(folder)/'counter.json')
            Path(counter).write_text('{"calls":0}')
            transport.record(counter,execution,1,receipt);transport.record(counter,execution,1,receipt)
            rows=transport.read(counter,execution);self.assertEqual(len(rows),1);self.assertNotIn('Synthetic only',json.dumps(rows))
            self.assertEqual(rows[0]['payload_sha256'],contract.digest(self.value()))
            with self.assertRaises(ValueError):transport.record(counter,execution,1,{**receipt,'payload_sha256':'d'*64})
            with self.assertRaises(ValueError):transport.record(counter,execution,2,{**receipt,'worker_tool_executed':True})

    def test_streamed_real_read_keeps_actual_id_and_arguments_but_not_null_metadata(self):
        args=json.dumps(dict(path='/evidence/candidate/app/value.txt',offset=1,limit=100))
        frames=[dict(choices=[dict(index=0,delta=dict(tool_calls=[dict(index=0,id='actual-read-id',type='function',
            function=dict(name='read_file',arguments=args[:20]))]),finish_reason=None)]),
            dict(choices=[dict(index=0,delta=dict(tool_calls=[dict(index=0,id=None,type=None,
                function=dict(name=None,arguments=args[20:]))]),finish_reason='tool_calls')])]
        raw=(''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n').encode()
        out,media,receipt=transport.translate(self.body(),raw,'text/event-stream');validate(self.body(),out,media)
        frame=json.loads(out.decode().splitlines()[0][5:]);call=frame['choices'][0]['delta']['tool_calls'][0]
        self.assertEqual(call['id'],'actual-read-id');self.assertEqual(call['function']['arguments'],args);self.assertIsNone(receipt)
        bad,bad_media=self.response(dict(path='/secret/openrouter.key',offset=1,limit=100),name='read_file')
        with self.assertRaises(StructuredResponseRejected):transport.translate(self.body(),bad,bad_media)
        body=self.body();body['tools'].append(dict(type='function',function=dict(name='terminal')))
        with self.assertRaises(ValueError):transport.project(body)
