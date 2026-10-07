import copy
import unittest
from service_mode_request_scope_experiment import ANCHOR,REPLACEMENT,change,supported
from service_mode_harness_qualification import CASES


class RequestScopeExperimentTests(unittest.TestCase):
    def test_only_unique_helper_changes_and_all_assertions_remain(self):
        template='assertion before;\n'+ANCHOR+'\nassertion after;'
        self.assertEqual(change(template),'assertion before;\n'+REPLACEMENT+'\nassertion after;')
        for value in (None,'missing',ANCHOR+'\n'+ANCHOR,REPLACEMENT):
            with self.assertRaises(ValueError):change(value)

    def fixture(self):
        good=dict(tests=15,failures=0,errors=0,skipped=0,unexpected_successes=0,expected_failures=0,failed_methods=[])
        bad={**good,'tests':1,'failures':1}
        baseline={**good,'failures':3,'failed_methods':sorted([
            'test_client_requests_service_mode_once_at_load',
            'test_exactly_one_request_per_page_load_across_all_loads',
            'test_pending_probe_shows_checking_then_terminal_demo'])}
        return dict(baseline=baseline,scoped=good,background_control=good,
            negative_controls={case:bad for case in CASES},actual_duplicate_control=bad)

    def test_supported_requires_causal_failure_and_all_negative_controls(self):
        supported(self.fixture())
        for key,field,value in [('baseline','failures',0),('scoped','tests',1),
            ('scoped','errors',1),('background_control','failures',1),
            ('actual_duplicate_control','failures',0),('actual_duplicate_control','errors',1)]:
            result=copy.deepcopy(self.fixture());result[key][field]=value
            with self.subTest(key=key,field=field),self.assertRaises(ValueError):supported(result)
        result=self.fixture();result['negative_controls']={}
        with self.assertRaises(ValueError):supported(result)
