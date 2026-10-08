import copy
import hashlib
from pathlib import Path
import unittest
from service_mode_timer_background_qualification import validate,INDICATOR_TIMERS,POLL,BACKGROUND
from service_mode_harness_qualification import CASES,fixture


class TimerControlTests(unittest.TestCase):
    def test_distributed_image_includes_dependency_and_import_preflight(self):
        text=(Path(__file__).resolve().parents[1]/'Dockerfile.timer-background-qualification').read_text()
        self.assertIn('COPY service_mode_background_qualification.py',text)
        self.assertIn('import service_mode_timer_background_qualification',text)
    def fixture(self):
        good=dict(tests=15,failures=0,errors=0,skipped=0,unexpected_successes=0,expected_failures=0)
        return good,{k:{**good,'tests':1,'failures':1} for k in set(CASES)|set(INDICATOR_TIMERS)}

    def test_polling_is_legitimate_but_all_probe_timer_behaviors_are_detected(self):
        good,bad=self.fixture();validate(good,bad)
        self.assertIn("fetch('/feedback')",POLL)
        self.assertNotIn('/service-mode',POLL)
        self.assertEqual(len(bad),16)
        self.assertIn('2000',INDICATOR_TIMERS['probe_interval_board_delay'])
        self.assertIn('setTimeout',POLL)

    def test_cannot_ignore_timers_or_count_all_timers(self):
        for field,value in [('failures',0),('errors',1),('skipped',1),('tests',0)]:
            good,bad=self.fixture();bad['indicator_timeout'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):validate(good,bad)
        good,bad=self.fixture();good['failures']=2
        with self.assertRaises(ValueError):validate(good,bad)

    def test_old_receipt_or_missing_indicator_only_control_rejected(self):
        good,bad=self.fixture();bad.pop('indicator_interval')
        with self.assertRaises(ValueError):validate(good,bad)
        with self.assertRaises(ValueError):validate(good,{})

    def test_controller_cannot_upgrade_traffic_only_receipt_to_timer_policy(self):
        import test_harness_qualification_job as helper
        from broker import harness_qualification as job
        h=helper.HarnessJobTests();h.setUp();value=h.result()
        with self.assertRaises(ValueError):job.validate_result(value,h.prepared,require_timers=True)
        good,bad=self.fixture()
        value.update(timer_background_policy='behavioral_timer_attribution_v1',timer_background_control=good,
            timer_negative_controls=bad,timer_positive_fixture_sha256=hashlib.sha256((BACKGROUND+fixture('positive')+POLL).encode()).hexdigest(),
            timer_negative_fixture_sha256={case:hashlib.sha256((BACKGROUND+INDICATOR_TIMERS.get(case,'')+
                fixture(case if case in CASES else 'positive')+POLL).encode()).hexdigest() for case in bad})
        job.validate_result(value,h.prepared,require_timers=True)
        for key in ('timer_background_policy','timer_positive_fixture_sha256','timer_negative_fixture_sha256'):
            wrong=copy.deepcopy(value);wrong[key]='wrong'
            with self.subTest(key=key),self.assertRaises(ValueError):job.validate_result(wrong,h.prepared,require_timers=True)
