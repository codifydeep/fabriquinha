import unittest
from broker.negative_control_spike import proposed_template,PARSER,PARSER_FIX,PREDICATE,PREDICATE_FIX


class NegativeControlSpikeTests(unittest.TestCase):
    def test_separate_hypotheses_do_not_modify_original(self):
        source=PARSER+'\n'+PREDICATE
        self.assertEqual(proposed_template(source),source)
        self.assertEqual(proposed_template(source,True),PARSER_FIX+'\n'+PREDICATE)
        self.assertEqual(proposed_template(source,False,True),PARSER+'\n'+PREDICATE_FIX)
        self.assertEqual(proposed_template(source,True,True),PARSER_FIX+'\n'+PREDICATE_FIX)

    def test_ambiguous_or_missing_seed_fails_closed(self):
        for source in [PARSER,PREDICATE,PARSER*2+PREDICATE,PARSER+PREDICATE*2]:
            with self.assertRaises(ValueError):proposed_template(source,True,True)
