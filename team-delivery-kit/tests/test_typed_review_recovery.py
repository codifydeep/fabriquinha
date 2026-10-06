import copy
import unittest
from broker.test_revision_review import prepare_typed_terminal_recovery


class TypedReviewRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.red={'task_id':'author','red':{'manifest_sha256':'a'*64}}
        self.task={'id':'failed-review','status':'failed','agent_id':'reviewer','wakeup_id':'wake'}
        self.state={'status':'blocked','source_task':'author','manifest_sha256':'a'*64,'wakeup_id':'wake',
            'review_failure':{'task_id':'failed-review','detail':'independent test review did not complete'},
            'comparison':{'candidate_manifest':'a'*64},'evidence_policy':1,'reason':'failure'}

    def test_one_recovery_preserves_evidence_and_does_not_manufacture_verdict(self):
        before=copy.deepcopy(self.state)
        new=prepare_typed_terminal_recovery(self.state,self.red,self.task,'reviewer')
        self.assertEqual(self.state,before)
        self.assertEqual(new['comparison'],before['comparison'])
        self.assertEqual(new['manifest_sha256'],before['manifest_sha256'])
        self.assertEqual(new['typed_terminal_recovery']['prior_failure'],before['review_failure'])
        self.assertFalse(new['typed_terminal_recovery']['delivery_approval'])
        self.assertEqual(new['typed_terminal_recovery']['attempt_limit'],1)
        self.assertNotIn('wakeup_id',new);self.assertNotIn('decision',new)
        self.assertEqual(prepare_typed_terminal_recovery(new,self.red,self.task,'reviewer'),new)

    def test_wrong_profile_snapshot_or_task_cannot_resume(self):
        for key,value in [('status','completed'),('agent_id','author'),('wakeup_id','other')]:
            with self.assertRaises(ValueError):
                prepare_typed_terminal_recovery(self.state,self.red,{**self.task,key:value},'reviewer')
        with self.assertRaises(ValueError):
            prepare_typed_terminal_recovery({**self.state,'manifest_sha256':'b'*64},self.red,self.task,'reviewer')
        with self.assertRaises(ValueError):
            prepare_typed_terminal_recovery({**self.state,'decision':{'action':'approve'}},self.red,self.task,'reviewer')

    def test_repeated_failure_cannot_generate_another_recovery(self):
        new=prepare_typed_terminal_recovery(self.state,self.red,self.task,'reviewer')
        with self.assertRaises(ValueError):
            prepare_typed_terminal_recovery(new,self.red,{**self.task,'id':'second-failure'},'reviewer')

    def test_already_typed_failure_is_not_an_authorized_transport_delta(self):
        with self.assertRaises(ValueError):
            prepare_typed_terminal_recovery({**self.state,'terminal_contract':'typed-review-v1'},
                self.red,self.task,'reviewer')
