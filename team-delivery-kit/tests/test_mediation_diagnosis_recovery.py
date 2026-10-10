import copy
import unittest
from broker import mediation_diagnosis_recovery as recovery


class MediationDiagnosisTests(unittest.TestCase):
    def test_completed_reader_revalidation_preserves_same_task_and_never_approves(self):
        import json
        from broker.handoff_runtime import Effects
        from test_review_reconsideration import ReconsiderationTests
        state,red,route,task,decision,reads,report=ReconsiderationTests().fixture()
        task.update(handoff_note='DELIVERY_REVIEW_RECONSIDERATION_V1\nDELIVERY_TYPED_TEST_DIAGNOSIS_V1\nDELIVERY_TEST_FINDINGS_V1\n',
            result={'output':json.dumps(decision)})
        decision=Effects(None,{}).decision(task)
        state['rejection_diagnosis'].update(status='blocked',failure={'operation':'structured_decision',
            'detail':'invalid technical decision','task_id':task['id']})
        updated=recovery.prepare_completed(state,red,route,{},task,decision,reads,report)
        proof=updated['review_reconsideration']['reader_recovery']
        self.assertEqual(proof['same_task'],task['id']);self.assertFalse(proof['new_model_call'])
        self.assertFalse(proof['delivery_approval']);self.assertEqual(updated['status'],'dispatch_intent')
        state['rejection_diagnosis']['failure']['operation']='artifact_reads'
        with self.assertRaises(ValueError):recovery.prepare_completed(state,red,route,{},task,decision,reads,report)
    def fixture(self):
        from test_review_reconsideration import ReconsiderationTests
        state,red,route,task,decision,reads,report=ReconsiderationTests().fixture()
        state['rejection_diagnosis'].update(status='blocked',failure={'operation':'task_completion','task_id':task['id']},
            schema_recovery={'failed_task':'old-failure','attempt_limit':1})
        task.update(status='failed',failure_reason='agent_error.provider_server_error')
        q={'operation':'provider_mediation_transport_qualification_v1','proxy_image':recovery.PROXY,
           'model':'anthropic/claude-haiku-5.5','actual_artifact_read':False,'worker_tool_executed':False,'delivery_approval':False}
        failure={'version':'acp-failure-receipt-v1','method':'session/prompt','cause':'unknown','categories':[],'approval':False}
        return [state,red,route,{'reviewer':'reviewer'},task,reads,q,failure]

    def test_preserves_unknown_cause_history_and_consumed_recoveries(self):
        args=self.fixture();before=copy.deepcopy(args[0]);updated=recovery.prepare(*args)
        self.assertEqual(args[0],before)
        d=updated['rejection_diagnosis'];self.assertEqual(d['status'],'dispatch_intent')
        self.assertEqual(d['schema_recovery'],before['rejection_diagnosis']['schema_recovery'])
        proof=d['provider_mediation_recovery'];self.assertEqual(proof['prior_diagnosis'],before['rejection_diagnosis'])
        for k in ('historical_http_cause_proven','author_restarted','delivery_approval'):self.assertFalse(proof[k])
        self.assertEqual(proof['attempt_limit'],1)
        args[0]=updated;self.assertEqual(recovery.prepare(*args),updated)
        args[4]['id']='another-failure'
        with self.assertRaises(ValueError):recovery.prepare(*args)

    def test_wrong_actor_snapshot_qualification_or_incomplete_reads_cannot_resume(self):
        for mutation in ('actor','wakeup','snapshot','read','qualification','approval','failure','mediation'):
            args=copy.deepcopy(self.fixture())
            if mutation=='actor':args[4]['agent_id']='author'
            if mutation=='wakeup':args[4]['wakeup_id']='other'
            if mutation=='snapshot':args[1]['red']['manifest_sha256']='b'*64
            if mutation=='read':args[5]['/evidence/previous/tests/test_new.py']['lines']=1
            if mutation=='qualification':args[6]['proxy_image']='sha256:'+'a'*64
            if mutation=='approval':args[6]['delivery_approval']=True
            if mutation=='failure':args[7]['approval']=True
            if mutation=='mediation':args[0]['rejection_diagnosis'].pop('mediation_contract')
            with self.assertRaises(ValueError,msg=mutation):recovery.prepare(*args)
