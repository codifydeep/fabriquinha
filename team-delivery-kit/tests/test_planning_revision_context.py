import copy
import json
import unittest

from broker.planning_revision_context import digest, expand, reference


class PlanningRevisionContextTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(source_task='source', cto='cto')
        plan = dict(reason='Full unchanged plan', steps=[dict(criteria=['A01', 'A02'])])
        sha = digest(plan)
        self.state = dict(stage='awaiting_plan', issue_id='issue', wakeup_id='wake',
            plan_revisions=[dict(plan=plan, plan_sha256=sha, plan_task='author',
                review_task='independent', review=dict(decision='request_changes',
                    reason='Attribute timer callbacks behaviorally, including equal delays.',
                    plan_sha256=sha, evidence_sha256=sha,
                    execution_authorized=False, release_homologated=False))])
        self.task = dict(agent_id='cto', wakeup_id='wake')

    def lookup(self, source):
        return dict(config=json.dumps(self.config), state=json.dumps(self.state)) if source == 'source' else None

    def test_lossless_expansion_preserves_entire_revision(self):
        result = expand(reference(self.config, self.state), 'issue', self.task, self.lookup)
        data = json.loads(result.split('DATA: ', 1)[1])
        self.assertEqual(data, self.state['plan_revisions'][-1])

    def test_wrong_actor_wakeup_issue_or_stage_rejected(self):
        marker = reference(self.config, self.state)
        for task, issue in [(dict(agent_id='lead', wakeup_id='wake'), 'issue'),
                            (dict(agent_id='cto', wakeup_id='old'), 'issue'), (self.task, 'other')]:
            with self.assertRaises(ValueError):
                expand(marker, issue, task, self.lookup)
        self.state['stage'] = 'blocked'
        with self.assertRaises(ValueError):
            expand(marker, 'issue', self.task, self.lookup)

    def test_drift_duplicates_and_oversized_context_rejected(self):
        marker = reference(self.config, self.state)
        with self.assertRaises(ValueError):
            expand(marker + marker, 'issue', self.task, self.lookup)
        self.state['plan_revisions'][-1]['review']['reason'] += ' drift'
        with self.assertRaises(ValueError):
            expand(marker, 'issue', self.task, self.lookup)
        marker = reference(self.config, self.state)
        with self.assertRaises(ValueError):
            expand('x' * 8000 + marker, 'issue', self.task, self.lookup)

    def test_approval_or_mismatched_plan_cannot_be_presented_as_rejection(self):
        for field, value in [('decision', 'approve_plan'), ('plan_sha256', '0' * 64),
                             ('execution_authorized', True)]:
            state = copy.deepcopy(self.state)
            state['plan_revisions'][-1]['review'][field] = value
            row = dict(config=json.dumps(self.config), state=json.dumps(state))
            with self.assertRaises(ValueError):
                expand(reference(self.config, state), 'issue', self.task, lambda _: row)
