from pathlib import Path
import tempfile
import unittest
import calibration_harness_protocol_probe as probe


class HarnessProtocolTests(unittest.TestCase):
    def source(self):
        return '''PREFIX = "Newest matching: "
NODE_HARNESS = "controller unit-test harness literal"
class Client:
 def test_stale_response_never_overwrites_newer_query(self):
  self.assertEqual(self.report['stale_guard_text'], PREFIX + '#11')
 def test_poll_and_filter_change_request_latest(self):
  self.assertEqual(self.report['initial_requests'], 1)
  self.assertGreaterEqual(self.report['poll_requests'], 3)
'''

    def test_only_literal_harness_and_exact_assertion_operands_are_recognized(self):
        value=probe.bind(self.source())
        self.assertEqual(value['stale_expected'],'Newest matching: #11')
        self.assertEqual(value['poll_minimum'],3);self.assertEqual(value['initial_expected'],1)
        self.assertGreater(value['stale_assertion_line'],0)

    def test_changed_assertions_or_dynamic_harness_fail_closed_without_import(self):
        for source in (self.source().replace('PREFIX + \'#11\'','str(11)'),
                self.source().replace('self.assertEqual(self.report[\'stale_guard_text\'], PREFIX + \'#11\')','pass'),
                self.source().replace('NODE_HARNESS = "controller unit-test harness literal"','NODE_HARNESS = load()'),
                self.source().replace('PREFIX = "Newest matching: "','PREFIX = call()')):
            with self.assertRaises(ValueError):probe.bind(source)

    def test_counterexample_is_not_a_calibration_or_product_approval(self):
        value=probe.measurements(probe.bind(self.source()),
            {'executed':True,'initial_requests':1,'poll_requests':2,'stale_guard_text':'Newest matching: #11'},
            {'requests':3,'fresh_text':'Newest matching: #11','after_late_text':'Newest matching: #4'})
        self.assertTrue(value['unguarded_witness_satisfies_stale_comparison'])
        self.assertTrue(value['witness_really_accepts_stale_responses'])
        self.assertFalse(value['one_refresh_per_poll_satisfies_poll_comparison'])
        for k in probe.FALSE_FLAGS:self.assertIs(value[k],False)

    def test_failed_execution_or_counterfactual_cannot_be_replaced_by_claims(self):
        facts={'executed':True,'initial_requests':1,'poll_requests':2,'stale_guard_text':'Newest matching: #11'}
        race={'requests':3,'fresh_text':'Newest matching: #11','after_late_text':'Newest matching: #4'}
        for bad in ({**facts,'executed':False},{**facts,'initial_requests':True}):
            with self.assertRaises(ValueError):probe.measurements(probe.bind(self.source()),bad,race)
        for bad in ({**race,'requests':True},{**race,'fresh_text':None}):
            with self.assertRaises(ValueError):probe.measurements(probe.bind(self.source()),facts,bad)

    def test_real_node_confirms_the_diagnostic_driver_has_no_stale_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'driver.js';file.write_text(probe.witness('Newest matching: '))
            result=probe.node(probe.RACE,str(file))
        self.assertEqual(result,dict(requests=3,fresh_text='Newest matching: #11',after_late_text='Newest matching: #4'))
