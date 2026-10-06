import unittest
from broker import lost_execution_preservation as preservation
from broker.lost_execution_preservation import qualify


class LostPreservationTests(unittest.TestCase):
    def setUp(self):
        self.task = dict(id='task', agent_id='author', issue_id='issue', status='completed')
        self.binding = dict(task_id='task', agent_id='author', issue_id='issue',
                            mode='implementation', status='lost')
        self.route = dict(author='author', issue_id='issue')

    def test_exact_lost_completed_author_qualifies_only_for_preservation(self):
        qualify(self.task, [self.task], self.binding, self.route, 0, False)
        self.assertEqual(self.binding['status'], 'lost')

    def test_live_or_unbound_worker_cannot_be_preserved(self):
        for active, exists in ((1, False), (0, True)):
            with self.assertRaises(ValueError):
                qualify(self.task, [self.task], self.binding, self.route, active, exists)
        for changes in (dict(status='closed'), dict(mode='review'), dict(task_id='other'), dict(issue_id='other')):
            with self.assertRaises(ValueError):
                qualify(self.task, [self.task], {**self.binding, **changes}, self.route, 0, False)

    def test_superseded_or_incomplete_native_task_is_rejected(self):
        with self.assertRaises(ValueError):
            qualify(self.task, [self.task, {**self.task, 'id':'z-new'}], self.binding, self.route, 0, False)
        with self.assertRaises(ValueError):
            qualify({**self.task, 'status':'running'}, [self.task], self.binding, self.route, 0, False)

    def test_diagnostic_requires_exact_preserved_candidate_and_never_approves(self):
        copy = dict(status='complete',task_id='task',volume='diagnostic',request_id='request',
                    issue_id='issue',author='author',lease_status='lost',submission=False,
                    delivery_approval=False,inspection=dict(manifest_sha256='a'*64,frozen_tests_unchanged=True))
        suite = dict(status='failed',task_id='task',volume='diagnostic',manifest_sha256='a'*64,
                     green_checkpoint=False,delivery_approval=False,
                     validation_failure=dict(category='executed_test_failure',source_task='task',
                         volume='diagnostic',output_sha256='b'*64,tests_executed=259,exit_code=1))
        route = dict(issue_id='issue',author='author',cto='cto',techlead='lead',reviewer='review',
                     contract_sha256='c'*64)
        data = preservation.diagnosis_data(copy,suite,route)
        self.assertFalse(data['lost_execution_diagnostic']['delivery_approval'])
        self.assertTrue(data['validation_failure']['diagnostic_only'])
        self.assertNotIn('green_validation',data)
        for bad in ({**suite,'manifest_sha256':'d'*64},{**suite,'status':'passed'},
                    {**suite,'green_checkpoint':True}):
            with self.assertRaises(ValueError):preservation.diagnosis_data(copy,bad,route)
