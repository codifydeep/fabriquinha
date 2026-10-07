import copy,json,sqlite3,unittest
from unittest.mock import patch
import model_proxy as proxy
import test_read_stream_recovery as fixtures
from plan_length_feedback import MARKER,NAME


class PlanLengthFeedbackTests(unittest.TestCase):
    def body(self,marked=True):
        body=fixtures.request_body();body['messages'][0]['content']=(
            'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_REMEDIATION_PLAN_V1:'+'a'*64+
            '\nDELIVERY_TYPED_REMEDIATION_V1:plan:'+'a'*64+
            '\nDELIVERY_REMEDIATION_CRITERION:A01\nDELIVERY_REMEDIATION_CRITERION:A02\n'+(MARKER+'\n' if marked else ''))
        return body

    def decision(self):
        return dict(action='propose_remediation_plan',evidence_sha256='a'*64,reason='Compile harness, preserve coverage and gates.',
            execution_authorized=False,release_homologated=False,steps=[dict(id='R'+str(i),depends_on=[] if i==1 else ['R'+str(i-1)],
                edit_scope=scope,objective='Validated unchanged scope',criteria=['A01','A02'])
                for i,scope in enumerate(('new_tests_only','product_only','controller_only'),1)])

    def wire(self,decision):
        return 200,json.dumps(dict(choices=[dict(message=dict(content=None,tool_calls=[dict(id='call',type='function',
            function=dict(name=NAME,arguments=json.dumps(decision)))]),finish_reason='tool_calls')])).encode(),'application/json'

    def test_all_overlong_prose_fields_are_corrected_once_without_accepting_previous_plan(self):
        f=fixtures.ReadStreamRecoveryTests();f.setUp();self.addCleanup(f.doCleanups)
        good=self.decision();bad=copy.deepcopy(good);bad['reason']='x'*700
        for step in bad['steps']:step['objective']='x'*300
        with patch.object(proxy,'forward',side_effect=[self.wire(bad),self.wire(good)]) as forward:
            response=f.request(self.body())
        self.assertEqual(response.status,200);self.assertEqual(forward.call_count,2)
        first,revised=[c.args[0] for c in forward.call_args_list]
        self.assertEqual(first['tools'],revised['tools'])
        feedback=json.loads(revised['messages'][-1]['content'])
        self.assertEqual(len(feedback['fields']),4);self.assertFalse(feedback['plan_acceptance_by_proxy'])
        with sqlite3.connect(f.counter.with_name('deterministic-reads.sqlite')) as c:
            receipt=json.loads(c.execute('SELECT receipt FROM technical_length_feedback').fetchone()[0])
            self.assertEqual(receipt['operation'],'remediation_plan_length_feedback_v1')
            self.assertFalse(receipt['plan_acceptance_by_proxy'])
        with patch.object(proxy,'forward') as again:
            self.assertEqual(f.request(self.body()).status,502);again.assert_not_called()

    def test_feedback_cannot_change_criteria_dependencies_scopes_or_unlisted_prose(self):
        for field in ('criteria','dependency','scope','evidence','prose'):
            f=fixtures.ReadStreamRecoveryTests();f.setUp()
            try:
                bad=self.decision();bad['reason']='x'*700;good=self.decision()
                if field=='criteria':good['steps'][0]['criteria']=['A01']
                if field=='dependency':good['steps'][1]['depends_on']=[]
                if field=='scope':good['steps'][0]['edit_scope']='product_only'
                if field=='evidence':good['evidence_sha256']='b'*64
                if field=='prose':good['steps'][0]['objective']='Changed unlisted objective'
                with patch.object(proxy,'forward',side_effect=[self.wire(bad),self.wire(good)]) as forward:
                    response=f.request(self.body())
                self.assertEqual(response.status,502);self.assertEqual(forward.call_count,2)
            finally:f.doCleanups()

    def test_no_retry_for_unmarked_or_other_invalid_fields(self):
        for field in ('unmarked','permission','missing','oversized'):
            f=fixtures.ReadStreamRecoveryTests();f.setUp()
            try:
                bad=self.decision();bad['reason']='x'*700
                if field=='permission':bad['execution_authorized']=True
                if field=='missing':del bad['steps'][0]['criteria']
                if field=='oversized':bad['reason']='x'*4001
                with patch.object(proxy,'forward',return_value=self.wire(bad)) as forward:
                    response=f.request(self.body(field!='unmarked'))
                self.assertEqual(response.status,502);forward.assert_called_once()
            finally:f.doCleanups()

    def test_correction_cannot_exceed_call_cap(self):
        f=fixtures.ReadStreamRecoveryTests();f.setUp();self.addCleanup(f.doCleanups)
        bad=self.decision();bad['reason']='x'*700
        with patch.object(proxy,'MAX_CALLS',1),patch.object(proxy,'forward',return_value=self.wire(bad)) as forward:
            self.assertNotEqual(f.request(self.body()).status,200);forward.assert_called_once()
