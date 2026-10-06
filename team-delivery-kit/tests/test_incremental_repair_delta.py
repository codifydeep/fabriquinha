import unittest
from broker.incremental_supervisor import require_repair_delta


class RepairDeltaTests(unittest.TestCase):
    def setUp(self):
        self.unit={'test_repair':dict(parent_issue='parent',decision_task='cto')}
        self.trial=dict(parent_issue='parent',cto_decision='cto',old_red={'red':{'test_sha256':{'tests/new.py':'a'*64}}})

    def test_identical_seed_cannot_be_a_repair_even_after_textual_approval(self):
        with self.assertRaisesRegex(ValueError,'changed NEW-test'):
            require_repair_delta(self.unit,{'red':{'test_sha256':{'tests/new.py':'a'*64}}},self.trial)

    def test_scope_and_sponsorship_cannot_drift(self):
        with self.assertRaises(ValueError):
            require_repair_delta(self.unit,{'red':{'test_sha256':{'tests/other.py':'b'*64}}},self.trial)
        with self.assertRaises(ValueError):
            require_repair_delta(self.unit,{'red':{'test_sha256':{'tests/new.py':'b'*64}}},{**self.trial,'cto_decision':'stale'})

    def test_real_delta_only_allows_following_gates_not_delivery(self):
        self.assertIsNone(require_repair_delta(self.unit,{'red':{'test_sha256':{'tests/new.py':'b'*64}}},self.trial))
        self.assertIsNone(require_repair_delta({},None,None))
