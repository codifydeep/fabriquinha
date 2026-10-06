import contextlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from broker import u3_work_proposal as work
from broker import qa_cleanup_observer as observer


class WorkTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'state.sqlite';self.b=SimpleNamespace(db=self.db)
        with self.db() as con:
            con.execute('CREATE TABLE qa_cleanup_followups(config TEXT,state TEXT)')
            con.execute('CREATE TABLE u3_product_intakes(config TEXT,state TEXT)')
            con.execute('CREATE TABLE test_decompositions(source_task TEXT,config TEXT)')
            con.execute('INSERT INTO qa_cleanup_followups VALUES(?,?)',(
                json.dumps(dict(cause='historical_tdd_red_missing',request=dict(task_id='qa',issue_id='parent',source_sha='a'*40))),
                json.dumps(dict(stage='diagnostic_recorded',issue_id='diagnostic-issue',diagnostics=[
                    dict(task_id='diagnostic',decision=dict(action='request_correction',reason='test first',optional_files=[]))]))))
            con.execute('INSERT INTO u3_product_intakes VALUES(?,?)',(
                json.dumps(dict(certificate={'root':'root'},proof=dict(classification='existing_behavior_coverage_only',previous_files_unchanged=True,new_code_required=False))),
                json.dumps(dict(stage='coverage_classification_approved'))))
            con.execute('INSERT INTO test_decompositions VALUES(?,?)',('root',json.dumps({'criteria':{k:k for k in ('C08','C09','C10')}})))
        self.fx=SimpleNamespace(ready=Mock(return_value=True),issue=Mock(return_value=dict(id='issue',identifier='proposal')),
            wake=Mock(return_value=dict(id='wake')),task=self.task,work_item=Mock(return_value=dict(id='maintenance',identifier='EVAL-maintenance')))
    @contextlib.contextmanager
    def db(self):
        con=sqlite3.connect(self.path);con.row_factory=sqlite3.Row
        try:
            with con:yield con
        finally:con.close()
    def value(self,config):
        return dict(evidence_sha256=observer.digest(config),kind='lifecycle_reconciliation',title='Reconcile lifecycle',
            reason='Coverage already passes; preserve historical hold',criteria=['C08','C09','C10'],
            historical_disposition='preserve_blocked_history',dependency_policy='do_not_release_dependents',
            product_edit_paths=[],historical_tdd_red=False,release_homologated=False,execution_authorized=False)
    def task(self,state):
        with self.db() as con:config=json.loads(con.execute('SELECT config FROM u3_work_proposals').fetchone()[0])
        value=self.value(config) if state['role']=='cto_proposal' else dict(decision='ACCEPT_EVIDENCE',
            evidence_sha256=state['proposal']['proposal_sha256'],reason='Independent exact-scope review',
            limitations=['Not release or execution approval'],historical_tdd_red=False,
            release_homologated=False,product_admission_authorized=False)
        return dict(id=state['role']+'-task',status='completed',agent_id=state['target'],
            issue_id=state['issue_id'],wakeup_id=state['wakeup_id'],result={'output':json.dumps(value)})
    def test_complete_independent_proposal_review_and_card_creation_is_idempotent(self):
        first=work.tick(self.b,effects=self.fx,now=1)
        self.assertEqual(first['stage'],'issue_intent');self.assertEqual(first['target'],work.diagnostic.TECHLEAD)
        second=work.tick(self.b,effects=self.fx,now=10)
        self.assertEqual(second['stage'],'work_contract_validated');self.assertFalse(second['execution_authorized'])
        self.fx.work_item.assert_called_once();self.assertEqual(self.fx.wake.call_count,2)
        work.tick(self.b,effects=self.fx,now=20);self.fx.work_item.assert_called_once()
    def test_invalid_proposal_never_creates_card_or_changes_product(self):
        config={'evidence':'bound'};state=dict(issue_id='issue',wakeup_id='wake')
        task=dict(id='t',status='completed',agent_id=work.diagnostic.CTO,issue_id='issue',wakeup_id='wake',result={})
        for key,value in [('kind','new_behavior_tdd'),('historical_tdd_red',True),('product_edit_paths',['app/static/app.js'])]:
            task['result']['output']=json.dumps(dict(self.value(config),**{key:value}))
            with self.assertRaises(Exception):work.proposal(config,state,task)
    def test_author_cannot_review_own_proposal_or_review_stale_digest(self):
        state=dict(issue_id='issue',wakeup_id='wake',proposal={'proposal_sha256':'a'*64})
        task=dict(status='completed',agent_id=work.diagnostic.CTO,issue_id='issue',wakeup_id='wake')
        with self.assertRaises(ValueError):work.review({},state,task)
    def test_unclassified_scope_never_dispatches(self):
        with self.db() as con:con.execute('UPDATE u3_product_intakes SET state=?',(json.dumps({'stage':'pending'}),))
        with self.assertRaises(ValueError):work.tick(self.b,effects=self.fx,now=1)
        self.fx.wake.assert_not_called()
