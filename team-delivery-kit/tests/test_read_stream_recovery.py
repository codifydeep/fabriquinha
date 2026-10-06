import copy
from contextlib import redirect_stdout
from io import BytesIO,StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import model_proxy as proxy
import read_stream_recovery as recovery

EXECUTION='11111111-1111-4111-8111-111111111111'


def request_body():
    return {'model':proxy.MODEL,'stream':True,'messages':[{'role':'user','content':
        'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_REVIEW_READ_PATH:/evidence/candidate/app.py\n'}],
        'tools':[{'type':'function','function':{'name':'read_file','parameters':{'type':'object'}}}]}


def response(error=False,arguments=None):
    if error:return 200,b'data: {"error":{"message":"PRIVATE_PROVIDER_ERROR"}}\n\ndata: [DONE]\n','text/event-stream'
    args=arguments or {'path':'/evidence/candidate/app.py','offset':1,'limit':100}
    frame={'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'function':{
        'name':'read_file','arguments':json.dumps(args)}}]},'finish_reason':'tool_calls'}]}
    return 200,('data: '+json.dumps(frame)+'\n\ndata: [DONE]\n').encode(),'text/event-stream'


class ReadStreamRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.counter=Path(self.temp.name)/'calls.json';self.counter.write_text('{"calls":0}')
        for field,value in [('COUNTER_PATH',str(self.counter)),('CALLS',0),('MAX_CALLS',10),('PROVIDER_PAUSE',None)]:
            patcher=patch.object(proxy,field,value);patcher.start();self.addCleanup(patcher.stop)

    def request(self,body=None):
        data=json.dumps(body or request_body()).encode()
        h=object.__new__(proxy.Handler)
        h.path='/executions/'+EXECUTION+'/api/v1/chat/completions'
        h.headers={'Content-Length':str(len(data)),'Authorization':proxy.PLACEHOLDER}
        h.rfile,h.wfile=BytesIO(data),BytesIO();h.send_response=lambda n:setattr(h,'status',n)
        h.send_header=lambda *a:None;h.end_headers=lambda:None
        with redirect_stdout(StringIO()) as logs:h.do_POST()
        self.assertNotIn('PRIVATE_PROVIDER_ERROR',logs.getvalue());self.assertNotIn(b'PRIVATE_PROVIDER_ERROR',h.wfile.getvalue())
        return h

    def rows(self):
        with recovery.connect(str(self.counter)) as con:return con.execute('SELECT first_call,retry_call,stage,outcome FROM recovery').fetchall()

    def test_error_then_valid_read_reserves_both_calls_and_forwards_only_validated_response(self):
        with patch.object(proxy,'forward',side_effect=[response(True),response()]) as forward:
            h=self.request()
        self.assertEqual(h.status,200);self.assertEqual(forward.call_count,2)
        self.assertEqual(forward.call_args_list[0],forward.call_args_list[1])
        self.assertEqual(proxy.load_calls(),2);self.assertEqual(self.rows(),[(1,2,'passed','validated_read')])

    def test_two_stream_errors_block_replay_without_spending_more_calls(self):
        with patch.object(proxy,'forward',return_value=response(True)) as forward:
            first=self.request();second=self.request()
        self.assertEqual(first.status,502);self.assertEqual(second.status,400)
        self.assertEqual(forward.call_count,2);self.assertEqual(proxy.load_calls(),2)
        self.assertEqual(self.rows(),[(1,2,'blocked','upstream_stream_error')])

    def test_invalid_arguments_are_not_transport_retries(self):
        with patch.object(proxy,'forward',return_value=response(arguments={'path':'/other','offset':1,'limit':100})) as forward:
            h=self.request()
        self.assertEqual(h.status,502);forward.assert_called_once();self.assertEqual(self.rows(),[])

    def test_budget_and_payment_pause_are_preserved_on_retry(self):
        with patch.object(proxy,'MAX_CALLS',1),patch.object(proxy,'forward',return_value=response(True)) as forward:
            h=self.request()
        self.assertEqual(h.status,400);forward.assert_called_once();self.assertEqual(proxy.load_calls(),1)
        self.assertEqual(self.rows()[0][2],'blocked')
        # A different immutable page is a separate scope, not a reset of this one.
        body=request_body();body['messages'][0]['content']=body['messages'][0]['content'].replace('app.py','other.py')
        with patch.object(proxy,'forward',side_effect=[response(True),(402,b'{}','application/json')]) as forward:
            h=self.request(body)
        self.assertEqual(h.status,402);self.assertEqual(forward.call_count,2)
        self.assertTrue(proxy.provider_pause());self.assertEqual(proxy.load_calls(),3)

    def test_claim_survives_restart_and_cannot_be_rearmed(self):
        body=proxy.validate_request(request_body());scope=recovery.identity(body,EXECUTION)
        self.assertIsNotNone(recovery.claim(str(self.counter),scope,1,'upstream_stream_error','text/event-stream'))
        with self.assertRaisesRegex(ValueError,'exhausted'):recovery.preflight(str(self.counter),scope)
        self.assertIsNone(recovery.claim(str(self.counter),scope,1,'upstream_stream_error','text/event-stream'))
        changed={**scope,'request_sha256':'a'*64}
        self.assertIsNone(recovery.claim(str(self.counter),changed,2,'upstream_stream_error','text/event-stream'))

    def test_only_correlated_exact_structured_read_is_eligible(self):
        body=proxy.validate_request(request_body());self.assertIsNotNone(recovery.identity(body,EXECUTION))
        for mutation in ('write','unforced','offset','path','stream','strict','marker'):
            bad=copy.deepcopy(body)
            if mutation=='write':bad['tool_choice']['function']['name']='write_file'
            if mutation=='unforced':bad['tool_choice']='auto'
            if mutation=='offset':bad['tools'][0]['function']['parameters']['properties']['offset']['enum']=[1,2]
            if mutation=='path':bad['tools'][0]['function']['parameters']['properties']['path']['enum']=['/workspace/app.py']
            if mutation=='stream':bad['stream']=False
            if mutation=='strict':bad['tools'][0]['function']['strict']=False
            if mutation=='marker':bad['messages']=[]
            self.assertIsNone(recovery.identity(bad,EXECUTION),mutation)
        self.assertIsNone(recovery.identity(body,None))
        self.assertIsNone(recovery.claim(str(self.counter),recovery.identity(body,EXECUTION),1,'invalid_forced_argument','text/event-stream'))

    def test_corrupt_or_symlink_ledger_fails_closed_before_provider_call(self):
        path=self.counter.with_name('read-stream-recovery.sqlite');path.write_bytes(b'corrupt')
        with patch.object(proxy,'forward') as forward:h=self.request()
        self.assertEqual(h.status,503);forward.assert_not_called();self.assertEqual(proxy.load_calls(),0)
        path.unlink();path.symlink_to(self.counter)
        with self.assertRaises(RuntimeError):recovery.preflight(str(self.counter),recovery.identity(proxy.validate_request(request_body()),EXECUTION))

    def test_concurrent_claims_consume_only_one_retry_slot(self):
        from concurrent.futures import ThreadPoolExecutor
        scope=recovery.identity(proxy.validate_request(request_body()),EXECUTION)
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims=list(pool.map(lambda _:recovery.claim(str(self.counter),scope,1,'upstream_stream_error','text/event-stream'),range(4)))
        self.assertEqual(sum(x is not None for x in claims),1)

    def test_real_http_canary_and_fresh_process_preserve_the_retry_limit(self):
        from read_stream_recovery_probe import run
        result=run()
        self.assertEqual(result['status'],'passed')
        self.assertEqual(result['real_model_calls'],0)
        self.assertTrue(result['restart_blocked']);self.assertTrue(result['write_retry_forbidden'])
