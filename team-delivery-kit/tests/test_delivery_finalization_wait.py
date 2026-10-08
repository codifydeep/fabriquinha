import json
import unittest
import test_delivery_handoffs as fixtures
from broker import handoffs


class DeliveryFinalizationTests(unittest.TestCase):
    setUp=fixtures.HandoffTests.setUp
    connect=fixtures.HandoffTests.connect
    tick=fixtures.HandoffTests.tick

    def test_pending_lease_never_freezes_or_wakes_diagnoser(self):
        self.effects.test_source_finalization=lambda *_:'pending'
        self.effects.freeze=lambda _:self.fail('must not freeze before lease finalization')
        self.assertEqual(self.tick(),'validation_pending')
        self.assertEqual(self.tick(now=110),'validation_pending')
        saved=json.loads(handoffs.load(self.con,'source')['data'])
        self.assertEqual(saved['attempts'],0)
        self.assertEqual(saved['lease_finalization_wait']['first_seen'],100)
        self.assertFalse(self.effects.created)

    def test_finalized_same_task_enters_real_validation(self):
        self.effects.test_source_finalization=lambda *_:'pending'
        self.tick()
        self.effects.test_source_finalization=lambda *_:'ready'
        self.assertEqual(self.tick(now=110),'awaiting_acceptance')
        saved=json.loads(handoffs.load(self.con,'source')['data'])
        self.assertEqual(saved['snapshot']['task_id'],'source')
        self.assertEqual(saved['dispatch_stage'],'ready_review')

    def test_historical_admission_race_is_preserved_not_restarted(self):
        self.effects.test_source_finalization=lambda *_:'ready'
        prior=dict(source_task='source',contract_sha256=self.route['contract_sha256'],attempts=1,
            error='no completed implementation lease',dispatch_stage='diagnose_cto',target='cto')
        handoffs.save(self.con,'source','issue','diagnose_cto','cto',prior,90)
        self.assertEqual(self.tick(),'awaiting_acceptance')
        saved=json.loads(handoffs.load(self.con,'source')['data'])
        proof=saved['lease_finalization_recovery']
        self.assertEqual(proof['prior_data'],prior)
        self.assertFalse(proof['approval']);self.assertFalse(proof['author_restarted'])
        self.assertEqual(saved['dispatch_stage'],'ready_review')

    def test_functional_failure_cannot_use_admission_race_recovery(self):
        self.effects.test_source_finalization=lambda *_:'ready'
        prior=dict(source_task='source',contract_sha256=self.route['contract_sha256'],attempts=1,
            error='no completed implementation lease',validation_failure={'category':'executed_test_failure'})
        handoffs.save(self.con,'source','issue','technical_decision_required','cto',prior,90)
        self.assertEqual(self.tick(),'technical_decision_required')
        self.assertNotIn('lease_finalization_recovery',json.loads(handoffs.load(self.con,'source')['data']))
