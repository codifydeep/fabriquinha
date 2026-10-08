import copy
import unittest
from test_portable_contract import contract
from broker import product_scope_revision as policy


class ProductScopeRevisionTests(unittest.TestCase):
    def setUp(self):
        self.original=contract()
        self.original['files'] += ['app/db.py','app/store.py']
        self.original['protected_files'] += ['app/db.py','app/store.py']
        self.context=dict(issue_id='issue',source_task='source',author='backend',cto='cto',reviewer='lead',
            contract_sha256=policy.digest(self.original),snapshot_sha256='a'*64,
            failure_output_sha256='b'*64,eligible_code_sha256={'app/db.py':'c'*64,'app/store.py':'d'*64},
            frozen_test_sha256={'tests/test_new.py':'e'*64})
        self.proposal=dict(operation='propose_product_scope_revision_v1',issue_id='issue',source_task='source',
            contract_sha256=self.context['contract_sha256'],snapshot_sha256='a'*64,
            failure_output_sha256='b'*64,write_files=['app/db.py','app/store.py'],
            reason='Add the missing persistence operation; keep all acceptance criteria and frozen tests.')

    def test_proposal_cannot_apply_permissions_and_preserves_the_entire_other_contract(self):
        saved=copy.deepcopy(self.original)
        proposal=policy.validate_proposal(self.original,self.context,self.proposal)
        candidate=policy.candidate_contract(self.original,self.context,proposal)
        self.assertEqual(self.original,saved)
        self.assertEqual(set(candidate['editable_files'])-set(saved['editable_files']),{'app/db.py','app/store.py'})
        self.assertEqual(set(saved['protected_files'])-set(candidate['protected_files']),{'app/db.py','app/store.py'})
        for field in saved.keys()-{'editable_files','protected_files'}:
            self.assertEqual(candidate[field],saved[field],field)
        self.assertIn('tests/test_old.py',candidate['protected_files'])
        self.assertEqual(candidate['test_files'],saved['test_files'])

    def test_tests_governance_unknown_paths_and_stale_bindings_are_rejected(self):
        for paths in (['tests/test_old.py'],['tests/test_new.py'],['AGENTS.md'],['.github/workflows/ci.yml'],
                      ['../secret.py'],['app/missing.py'],['app/db.py','app/db.py'],[]):
            with self.subTest(paths=paths),self.assertRaises(ValueError):
                policy.validate_proposal(self.original,self.context,dict(self.proposal,write_files=paths))
        for field in ('contract_sha256','snapshot_sha256','failure_output_sha256','source_task','issue_id'):
            with self.subTest(field=field),self.assertRaises(ValueError):
                policy.validate_proposal(self.original,self.context,dict(self.proposal,**{field:'wrong'}))

    def test_independent_review_is_exact_proposal_bound_not_delivery_approval(self):
        proposal=policy.validate_proposal(self.original,self.context,self.proposal)
        review=dict(operation='review_product_scope_revision_v1',proposal_sha256=policy.digest(proposal),
            decision='approve',reason='Scope is necessary and tests, acceptance and quality gates remain unchanged.')
        receipt=policy.qualify_review(self.context,proposal,review,
            dict(id='cto-task',agent_id='cto',issue_id='issue',status='completed'),
            dict(id='lead-task',agent_id='lead',issue_id='issue',status='completed'),
            {'app/db.py':'c'*64,'app/store.py':'d'*64})
        self.assertFalse(receipt['delivery_approval'])
        self.assertFalse(receipt['write_grant_issued'])
        self.assertEqual(receipt['proposal_sha256'],policy.digest(proposal))
        for actor in ('cto','backend'):
            with self.subTest(actor=actor),self.assertRaises(ValueError):
                policy.qualify_review(self.context,proposal,review,
                    dict(id='cto-task',agent_id='cto',issue_id='issue',status='completed'),
                    dict(id='lead-task',agent_id=actor,issue_id='issue',status='completed'),
                    {'app/db.py':'c'*64,'app/store.py':'d'*64})
        with self.assertRaises(ValueError):
            policy.qualify_review(self.context,proposal,dict(review,proposal_sha256='f'*64),
                dict(id='cto-task',agent_id='cto',issue_id='issue',status='completed'),
                dict(id='lead-task',agent_id='lead',issue_id='issue',status='completed'),
                {'app/db.py':'c'*64,'app/store.py':'d'*64})

    def test_incomplete_inspection_and_nonterminal_tasks_cannot_qualify(self):
        review=dict(operation='review_product_scope_revision_v1',proposal_sha256=policy.digest(self.proposal),
            decision='approve',reason='Necessary scope.')
        for reads,status in (({},'completed'),({'app/db.py':'c'*64},'completed'),
                             ({'app/db.py':'wrong','app/store.py':'d'*64},'completed'),
                             ({'app/db.py':'c'*64,'app/store.py':'d'*64},'running')):
            with self.subTest(reads=reads,status=status),self.assertRaises(ValueError):
                policy.qualify_review(self.context,self.proposal,review,
                    dict(id='cto-task',agent_id='cto',issue_id='issue',status='completed'),
                    dict(id='lead-task',agent_id='lead',issue_id='issue',status=status),reads)
