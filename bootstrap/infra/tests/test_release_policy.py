import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release_policy import validate_report

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.report = dict(state='HOMOLOGADA', commit='a'*40, deployed_commit='a'*40,
            brief_approval={'evidence':'kanban:event:1'}, acceptance=[{'criterion':'lobby','cards':['t_fe']}],
            qa={'profile':'quality_security','commit':'a'*40,'card':'t_qa','evidence':'test.log'},
            deployment={'profile':'devops','commit':'a'*40,'card':'t_do','evidence':'deploy.log'},
            url='http://localhost:3000', rollback='previous compose revision', platforms=['web'], limitations=[])
        self.tasks = dict(t_fe='done', t_qa='done', t_do='done')

    def test_web_only_does_not_require_mobile(self):
        self.assertTrue(validate_report(self.report, self.tasks))

    def test_missing_evidence_blocks(self):
        for key in ('brief_approval','acceptance','qa','deployment','url','rollback','limitations'):
            report = copy.deepcopy(self.report)
            del report[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_report(report, self.tasks)

    def test_commit_and_dependency_must_match(self):
        self.report['deployed_commit'] = 'b'*40
        with self.assertRaises(ValueError): validate_report(self.report, self.tasks)

    def test_attempt_and_approved_criteria_are_not_omittable(self):
        baseline = dict(attempt='r2', approved_criteria=['lobby','privacy'], brief_sha256='c'*64, platforms=['web'])
        self.report.update(attempt='r2')
        self.report['brief_approval']['sha256'] = 'c'*64
        with self.assertRaises(ValueError):
            validate_report(self.report, self.tasks, baseline)
        self.report['acceptance'].append({'criterion':'privacy','cards':['t_fe']})
        self.assertTrue(validate_report(self.report, self.tasks, baseline))
        self.report['attempt'] = 'r1'
        with self.assertRaises(ValueError):
            validate_report(self.report, self.tasks, baseline)
        self.report['deployed_commit'] = 'a'*40
        self.tasks['t_fe'] = 'blocked'
        with self.assertRaises(ValueError): validate_report(self.report, self.tasks)
