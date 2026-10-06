import unittest
from broker.test_capture_constraints import inspect


class CaptureConstraintsTests(unittest.TestCase):
    def source(self, second="'oldest_state'", last='11'):
        return f'''OLDEST_IDS = [1, 2, 3, 10]
class Direction:
 def test_initial(self):
  ids = self.ids('oldest_state')
  self.assertEqual(ids, OLDEST_IDS)
class Creation:
 def test_after_create(self):
  ids = self.ids({second})
  self.assertEqual(ids[-1], {last})
'''

    def test_incompatible_shared_capture_has_exact_source_witness(self):
        facts = inspect(self.source())
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]['implied_element'], 10)
        self.assertEqual(facts[0]['element']['expected'], 11)
        self.assertEqual(facts[0]['whole']['line'], 5)

    def test_distinct_capture_and_consistent_expectation_have_no_witness(self):
        self.assertEqual(inspect(self.source("'after_create_oldest'")), [])
        self.assertEqual(inspect(self.source(last='10')), [])

    def test_dynamic_or_reassigned_alias_is_not_used_as_proof(self):
        self.assertEqual(inspect(self.source(last='compute_expected()')), [])
        self.assertEqual(inspect(self.source().replace(
            'self.assertEqual(ids[-1]', 'ids = transformed(ids)\n  self.assertEqual(ids[-1]')), [])
