import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from product_graph import audit

class ProductGraphTests(unittest.TestCase):
    def proposal(self):
        return '\n'.join(
            [f'- **TDD-{i:02d}** — Task | backend_data → techlead | depends on: '+('—' if i==1 else f'TDD-{i-1:02d}')+' | verification: Red Green regression' for i in range(1,22)]+
            [f'| LOB-{i:02d} | TDD-{i:02d} | acceptance |' for i in range(1,8)]+
            [f'| V01-{i:02d} | continuation |' for i in range(1,11)])
    def test_valid_never_unlocks(self):
        r=audit(self.proposal());self.assertEqual(len(r['nodes']),21);self.assertFalse(r['implementation_allowed']);self.assertFalse(r['native_cards_created'])
    def test_missing_acceptance(self):
        with self.assertRaises(ValueError):audit(self.proposal().replace('| LOB-07 |','| XXX-07 |'))
    def test_unknown_coverage(self):
        with self.assertRaises(ValueError):audit(self.proposal().replace('| LOB-01 | TDD-01','| LOB-01 | TDD-99'))
    def test_missing_continuation(self):
        with self.assertRaises(ValueError):audit(self.proposal().replace('| V01-07 |','| XXX-07 |'))
    def test_cycle(self):
        with self.assertRaises(ValueError):audit(self.proposal().replace('depends on: —','depends on: TDD-21'))
    def test_self_review(self):
        with self.assertRaises(ValueError):audit(self.proposal().replace('backend_data → techlead','backend_data → backend_data',1))
