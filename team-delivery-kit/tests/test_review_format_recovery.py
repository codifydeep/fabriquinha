import copy
import ast
import contextlib
import io
import inspect
import json
import unittest
from broker.review_format_recovery import prepare, qualify_proxy


class ReviewFormatRecoveryTests(unittest.TestCase):
    def test_fixed_canary_rejects_oversize_and_changed_verdict_without_provider(self):
        function=ast.parse(inspect.getsource(qualify_proxy)).body[0]
        script=next(ast.literal_eval(node.value) for node in function.body
            if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='script' for t in node.targets))
        output=io.StringIO()
        with contextlib.redirect_stdout(output):exec(script,{})
        proof=json.loads(output.getvalue())
        self.assertTrue(proof['canary']);self.assertEqual(proof['model_calls'],0)
        self.assertEqual(len(proof['source_sha256']),64)

    def setUp(self):
        self.state=dict(status='blocked',terminal_contract='typed-review-v1',bootstrap_retry=1,
            source_task='author',candidate_volume='candidate',manifest_sha256='a'*64,wakeup_id='wake',
            review_failure=dict(task_id='review',detail='independent test review did not complete'))
        self.red=dict(task_id='author',volume='candidate',red=dict(manifest_sha256='a'*64))
        self.task=dict(id='review',status='failed',agent_id='reviewer',wakeup_id='wake')
        self.rejection=dict(operation='rejected_typed_decision_adapter_v1',category='typed_schema_maxLength',
            delivery_approval=False,worker_tool_executed=False,upstream_sha256='b'*64,
            response_shape=dict(parsed=True,terminal=True,expected_tool=True,arguments_json_valid=True,
                arguments_schema_valid=False,submissions=1))
        self.reads={'candidate':dict(lines=641,total_lines=641),'previous':dict(lines=51,total_lines=51)}

    def run_prepare(self):
        return prepare(self.state,self.red,self.task,'reviewer',self.rejection,self.reads,
                       ['candidate','previous'],'sha256:'+'c'*64)

    def test_preserves_original_failure_and_retry_counters_without_approval(self):
        before=copy.deepcopy(self.state);updated=self.run_prepare()
        self.assertEqual(self.state,before)
        self.assertEqual(updated['bootstrap_retry'],1)
        self.assertEqual(updated['format_recovery']['prior_state'],before)
        self.assertEqual(updated['status'],'dispatch_intent')
        self.assertNotIn('wakeup_id',updated)
        self.assertFalse(updated['format_recovery']['delivery_approval'])
        self.assertFalse(updated['format_recovery']['author_restarted'])
        self.state=updated
        with self.assertRaises(ValueError):self.run_prepare()

    def test_snapshot_task_failure_and_read_drift_fail_closed(self):
        for target,key,value in ((self.state,'manifest_sha256','d'*64),
                (self.task,'status','completed'),(self.task,'agent_id','author'),
                (self.rejection,'category','typed_schema_enum'),
                (self.rejection['response_shape'],'expected_tool',False),
                (self.reads['candidate'],'lines',640)):
            old=target[key];target[key]=value
            with self.assertRaises(ValueError):self.run_prepare()
            target[key]=old
