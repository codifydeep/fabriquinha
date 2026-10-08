import copy
import unittest
from broker.review_provider_recovery import prepare


class ReviewProviderRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.red={'task_id':'author-task','volume':'frozen-volume','red':{'manifest_sha256':'a'*64,'test_sha256':{'tests/new.py':'b'*64}}}
        self.task={'id':'failed-review','status':'failed','failure_reason':'agent_error.provider_server_error',
            'agent_id':'reviewer','wakeup_id':'old-wakeup'}
        self.state={'status':'blocked','terminal_contract':'typed-review-v1','source_task':'author-task',
            'candidate_volume':'frozen-volume','manifest_sha256':'a'*64,'wakeup_id':'old-wakeup',
            'review_failure':{'task_id':'failed-review','detail':'independent test review did not complete'},
            'transport_observation_recovery':{'failed_task':'earlier-review'}}
        self.reads={'/evidence/candidate/tests/new.py':{'lines':10,'total_lines':10}}
        self.proof={'operation':'provider_review_transport_qualification_v1','model':'anthropic/claude-haiku-5.5',
            'delivery_approval':False,'actual_artifact_read':False}

    def call(self):return prepare(self.state,self.red,self.task,'reviewer',self.reads,self.proof)

    def test_new_intent_preserves_old_failure_and_snapshot_without_approval(self):
        before=copy.deepcopy(self.state);result=self.call()
        self.assertEqual(self.state,before)
        self.assertEqual(result['status'],'dispatch_intent')
        self.assertNotIn('wakeup_id',result)
        self.assertEqual(result['transport_observation_recovery'],before['transport_observation_recovery'])
        self.assertFalse(result['provider_schema_recovery']['approval'])
        self.assertFalse(result['provider_schema_recovery']['author_restarted'])
        self.assertEqual(result['manifest_sha256'],before['manifest_sha256'])

    def test_wrong_task_snapshot_unobserved_reads_or_unqualified_model_fail_closed(self):
        for target,key,value in ((self.task,'status','completed'),(self.task,'agent_id','author'),
                (self.task,'failure_reason','functional_failure'),(self.state,'manifest_sha256','c'*64),
                (self.proof,'model','other/model'),(self.proof,'actual_artifact_read',True)):
            old=target[key];target[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.call()
            target[key]=old
        self.reads['/evidence/candidate/tests/new.py']['lines']=9
        with self.assertRaises(ValueError):self.call()

    def test_repeated_recovery_is_idempotent_and_cannot_reset_after_failure(self):
        self.state=self.call();self.assertEqual(self.call(),self.state)
        self.task['id']='new-failed-review'
        with self.assertRaises(ValueError):self.call()
