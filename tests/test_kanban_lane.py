"""Boundary tests for the S1 deterministic lane; no model or Docker calls."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fabriquinha.kanban_lane import verdict


class LaneBoundaries(unittest.TestCase):
    def setUp(self):
        self.context = dict(task='t_fixture', run=7, actor='reviewer',
                            implementer='author', mode='review', sha='a' * 64)

    def test_reviewer_must_be_independent(self):
        self.context['actor'] = 'author'
        with self.assertRaises(ValueError):
            verdict(self.context, dict(action='approve', sha='a' * 64))

    def test_author_cannot_approve(self):
        self.context.update(mode='implementation', actor='author')
        with self.assertRaises(ValueError):
            verdict(self.context, dict(action='approve', sha='a' * 64))

    def test_changed_delivery_invalidates_approval(self):
        with self.assertRaises(ValueError):
            verdict(self.context, dict(action='approve', sha='b' * 64))

    def test_no_extra_command_is_accepted(self):
        with self.assertRaises(ValueError):
            verdict(self.context, dict(action='approve', sha='a' * 64, command='anything'))

    def test_review_and_rework_are_distinct(self):
        self.assertEqual(verdict(self.context, dict(action='changes', sha='a' * 64)), 'changes')
        self.assertEqual(verdict(self.context, dict(action='approve', sha='a' * 64)), 'approve')

    def test_unknown_phase_is_refused(self):
        self.context['mode'] = 'administrator'
        with self.assertRaises(ValueError):
            verdict(self.context, dict(action='finish', sha='a' * 64))

    def test_implementer_cannot_submit_review_change_request(self):
        self.context.update(mode='implementation', actor='author')
        with self.assertRaises(ValueError):
            verdict(self.context, dict(action='changes', sha='a' * 64))


if __name__ == '__main__':
    unittest.main()
