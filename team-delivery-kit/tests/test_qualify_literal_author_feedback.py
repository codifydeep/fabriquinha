import copy
import hashlib
import json
from pathlib import Path
import unittest
import literal_author_feedback as feedback
import qualify_literal_author_feedback as qualify
import test_literal_poll_capture_experiment as fixtures
from generic_harness_calibration import digest


class FeedbackQualificationTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.PollCaptureExperimentTests();self.addCleanup(fixture.doCleanups)
        root,manifest,raw=fixture.fixture();sha=hashlib.sha256(raw).hexdigest()
        facts=feedback.run(root,root,manifest,'tests/test.py',sha)
        self.context=dict(previous_manifest=manifest,test_path='tests/test.py',
            candidates=[dict(revision=i,sha256=sha,reports=facts['reports']) for i in range(3)])
        self.value=dict(operation='qualified_literal_author_feedback_v1',context_sha256=digest(self.context),
            identity=dict(script_sha256=hashlib.sha256(Path(feedback.__file__).read_bytes()).hexdigest()),
            facts={str(i):copy.deepcopy(facts) for i in range(3)},**{k:False for k in feedback.FALSE_FLAGS})

    def test_three_real_feedback_results_reproduce_failed_gate_without_approval(self):
        self.assertEqual(qualify.validate(self.value,self.context),self.value)
        compile(qualify.QUERY,'qualification-query','exec')

    def test_stale_source_script_report_or_extra_authority_cannot_qualify(self):
        for key,value in (('candidate_sha256','f'*64),('feedback_sha256','f'*64),
                ('checks_passed',True),('non_target_verification','passed')):
            changed=copy.deepcopy(self.value);changed['facts']['2'][key]=value
            with self.assertRaises(ValueError):qualify.validate(changed,self.context)
        for flag in feedback.FALSE_FLAGS:
            changed=copy.deepcopy(self.value);changed[flag]=True
            with self.assertRaises(ValueError):qualify.validate(changed,self.context)
        with self.assertRaises(ValueError):qualify.validate({**self.value,'release_approved':True},self.context)

    def test_incomplete_or_duplicate_revision_inventory_is_not_qualification(self):
        changed=copy.deepcopy(self.value);changed['facts'].pop('1')
        with self.assertRaises(ValueError):qualify.validate(changed,self.context)
        context=copy.deepcopy(self.context);context['candidates'][1]['revision']=0
        changed=copy.deepcopy(self.value);changed['context_sha256']=digest(context)
        with self.assertRaises(ValueError):qualify.validate(changed,context)
