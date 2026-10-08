import copy
import json
import sqlite3
import unittest
from broker import calibration_observation as observation,calibration_rework
from service_mode_harness_qualification import CASES


class CalibrationObservationTests(unittest.TestCase):
    def setUp(self):
        self.counts=dict(tests=1,failures=1,errors=0,skipped=0,unexpected_successes=0,expected_failures=0)
        self.value=dict(status='rejected',phase='behavioral_controls',delivery_approval=False,
            facts=dict(manifest_sha256='a'*64,test_sha256='b'*64,
                positive=dict(self.counts,tests=15,failures=0),
                negative_controls={case:dict(self.counts) for case in CASES}))
        for case in ('probe_interval','probe_timeout'):
            self.value['facts']['negative_controls'][case]['failures']=0

    def test_measured_rejection_is_not_red_or_delivery(self):
        facts=observation.validate_result(self.value,'a'*64)
        index=calibration_rework.diagnostic_index(dict(facts,phase=self.value['phase']))
        self.assertEqual(index['negative_controls_total'],12)
        self.assertEqual(index['negative_controls_detected'],10)
        self.assertEqual(set(index['undetected_or_invalid_controls']),{'probe_interval','probe_timeout'})
        self.assertLess(len(json.dumps(index)),1000)
        self.assertNotIn('negative_controls',index)

    def test_same_candidate_all_controls_nonapproving_and_numeric_counts_required(self):
        for mutate in (lambda v:v.update(status='passed'),lambda v:v.update(delivery_approval=True),
                lambda v:v['facts'].update(manifest_sha256='wrong'),
                lambda v:v['facts']['negative_controls'].pop('probe_timeout'),
                lambda v:v['facts']['positive'].update(errors=True),
                lambda v:v['facts']['negative_controls']['probe_timeout'].update(tests=10001)):
            value=copy.deepcopy(self.value);mutate(value)
            with self.assertRaises(ValueError):observation.validate_result(value,'a'*64)

    def test_archive_identity_is_once_per_source_not_a_retry(self):
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        proof=dict(self.value['facts'],status='rejected',delivery_approval=False)
        self.assertEqual(observation.claim(con,'source','c'*64,proof),proof)
        self.assertEqual(observation.claim(con,'source','c'*64,proof),proof)
        with self.assertRaises(ValueError):observation.claim(con,'source','d'*64,proof)
        with self.assertRaises(ValueError):observation.claim(con,'source','c'*64,dict(proof,status='passed'))

    def test_timer_phase_reports_indicator_only_defects_to_both_planners(self):
        from service_mode_timer_background_qualification import INDICATOR_TIMERS
        facts=dict(self.value['facts'],phase='background_timer_control',
            negative_controls={case:dict(self.counts) for case in set(CASES)|set(INDICATOR_TIMERS)})
        for case in ('indicator_timeout','indicator_interval'):
            facts['negative_controls'][case]['failures']=0
        index=calibration_rework.diagnostic_index(facts)
        self.assertEqual(index['negative_controls_total'],16)
        self.assertEqual(index['negative_controls_detected'],14)
        self.assertEqual(index['undetected_or_invalid_controls'],['indicator_interval','indicator_timeout'])
        config=dict(diagnostic=facts,criteria={'C1':{}},paths=['/evidence/candidate/tests/test_service_mode_indicator.py'])
        for state in (dict(stage='cto_pending'),dict(stage='peer_pending',cto_decision={'reason':'Preserve all controls'})):
            note=calibration_rework.instruction(config,state)
            self.assertIn('indicator_interval',note)
            self.assertIn('indicator_timeout',note)
            self.assertIn('"negative_controls_total": 16',note)

    def test_timer_phase_cannot_hide_missing_controls(self):
        facts=dict(self.value['facts'],phase='background_timer_control',
            negative_controls={case:dict(self.counts) for case in CASES})
        index=calibration_rework.diagnostic_index(facts)
        self.assertEqual(index['negative_controls_total'],16)
        self.assertEqual(index['negative_controls_detected'],12)
        self.assertEqual(set(index['undetected_or_invalid_controls']),
            {'indicator_interval','indicator_timeout','probe_interval_board_delay','probe_timeout_board_delay'})

    def test_both_planners_receive_negative_evidence_and_all_read_requirements(self):
        config=dict(diagnostic=dict(self.value['facts'],phase=self.value['phase']),criteria={'C1':{}},
            paths=['/evidence/candidate/tests/test_service_mode_indicator.py','/evidence/candidate/app/static/app.js'])
        for state in (dict(stage='cto_pending'),dict(stage='peer_pending',cto_decision={'reason':'Inspect causal timer attribution'})):
            note=calibration_rework.instruction(config,state)
            self.assertIn('probe_interval',note)
            self.assertIn('probe_timeout',note)
            self.assertIn('Passing the positive reference alone is insufficient',note)
            self.assertIn('DELIVERY_REVIEW_READ_PATH:/evidence/candidate/app/static/app.js',note)
            self.assertLess(len(note)+100,4000)
