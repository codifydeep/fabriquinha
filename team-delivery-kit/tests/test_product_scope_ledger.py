import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path
import test_product_scope_revision as fixtures
from broker import product_scope_ledger as ledger
from broker.product_scope_revision import digest


class ProductScopeLedgerTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.ProductScopeRevisionTests();fixture.setUp()
        self.original,self.context,self.proposal=fixture.original,fixture.context,fixture.proposal
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'ledger.sqlite'

    def connect(self):return sqlite3.connect(self.path)

    def task(self,actor,identifier):
        return dict(agent_id=actor,id=identifier,issue_id='issue',status='completed')

    def test_restart_preserves_idempotent_intent_and_proposal_with_no_permissions(self):
        with self.connect() as con:
            first=ledger.open_plan(con,self.original,self.context)
            submitted=ledger.record_proposal(con,first['key'],self.proposal,self.task('cto','cto-task'))
        with self.connect() as con:
            self.assertEqual(ledger.open_plan(con,self.original,self.context),submitted)
            self.assertEqual(ledger.record_proposal(con,first['key'],self.proposal,self.task('cto','cto-task')),submitted)
            with self.assertRaises(ValueError):
                ledger.record_proposal(con,first['key'],dict(self.proposal,reason='Another proposal'),self.task('cto','other'))
            self.assertEqual(ledger.load(con,first['key'])['stage'],'awaiting_review')
            self.assertTrue(ledger.load(con,first['key'])['author_blocked'])

    def test_qualified_review_is_durable_but_does_not_install_contract_or_release_author(self):
        review=dict(operation='review_product_scope_revision_v1',proposal_sha256=digest(self.proposal),
                    decision='approve',reason='Dependencies necessary; tests remain frozen.')
        with self.connect() as con:
            key=ledger.open_plan(con,self.original,self.context)['key']
            ledger.record_proposal(con,key,self.proposal,self.task('cto','cto-task'))
            approved=ledger.record_review(con,key,review,self.task('lead','review-task'),
                                          self.context['eligible_code_sha256'])
        with self.connect() as con:
            self.assertEqual(ledger.load(con,key),approved)
            self.assertEqual(ledger.record_review(con,key,review,self.task('lead','review-task'),
                             self.context['eligible_code_sha256']),approved)
            self.assertEqual(approved['stage'],'plan_approved')
            self.assertTrue(approved['author_blocked'])
            self.assertFalse(approved['qualification']['write_grant_issued'])
            self.assertNotIn('installed_contract',approved)

    def test_wrong_actor_stale_review_and_missing_reads_preserve_hold(self):
        with self.connect() as con:
            key=ledger.open_plan(con,self.original,self.context)['key']
            with self.assertRaises(ValueError):
                ledger.record_proposal(con,key,self.proposal,self.task('backend','bad-task'))
            self.assertEqual(ledger.load(con,key)['stage'],'awaiting_proposal')
            ledger.record_proposal(con,key,self.proposal,self.task('cto','cto-task'))
            review=dict(operation='review_product_scope_revision_v1',proposal_sha256=digest(self.proposal),
                        decision='approve',reason='Necessary.')
            for task,reads in ((self.task('cto','review-task'),self.context['eligible_code_sha256']),
                               (self.task('lead','review-task'),{})):
                with self.assertRaises(ValueError):ledger.record_review(con,key,review,task,reads)
            self.assertEqual(ledger.load(con,key)['stage'],'awaiting_review')

    def test_context_drift_is_not_an_idempotent_retry(self):
        with self.connect() as con:
            ledger.open_plan(con,self.original,self.context)
            changed=copy.deepcopy(self.context);changed['frozen_test_sha256']['tests/test_new.py']='0'*64
            with self.assertRaises(ValueError):ledger.open_plan(con,self.original,changed)
