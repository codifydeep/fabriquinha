import copy
import unittest
from jsonschema import ValidationError
from broker.remediation_execution import contract,issue_spec
from broker.technical_remediation_plan import digest


class RemediationExecutionContractTests(unittest.TestCase):
    def setUp(self):
        self.c=dict(source_task='source',source_issue='old',root_issue='root',cto='cto',reviewer='lead',original_author='author',
            original_depth=2,criteria={'A01':'criterion'},base={'base_sha':'f'*40},contract_sha256='c'*64,
            context_sha256='d'*64,revision_lineage=['r2','r1'])
        p=dict(action='propose_remediation_plan',evidence_sha256=digest(self.c),reason='Scoped correction',
            execution_authorized=False,release_homologated=False,steps=[dict(id='R'+str(i),depends_on=[] if i==1 else ['R'+str(i-1)],
                edit_scope=scope,objective='Verified step',criteria=['A01']) for i,scope in enumerate(('new_tests_only','product_only','controller_only'),1)])
        self.s=dict(stage='plan_approved',plan=p,plan_sha256=digest(p),plan_task='plan',review_task='review',review=dict(
            decision='approve_plan',evidence_sha256=digest(p),plan_sha256=digest(p),reason='Complete gates',
            execution_authorized=False,release_homologated=False))

    def test_exact_approved_contract_preserves_scope_depth_and_terminal_gates(self):
        result=contract(self.c,self.s,['tests/test_new.py'],['app.js'])
        self.assertEqual(result['original_depth'],2)
        self.assertEqual(result['revision_lineage'],['r2','r1'])
        self.assertEqual(result['steps'][0]['editable_files'],['tests/test_new.py'])
        self.assertEqual(result['steps'][1]['editable_files'],['app.js'])
        self.assertEqual(result['steps'][2]['editable_files'],[])
        self.assertIn('browser_qa_exact_sha',result['steps'][2]['gates'])
        self.assertFalse(result['release_homologated'])
        self.assertFalse(result['historical_snapshots_editable'])

    def test_stale_self_rejected_or_missing_approval_cannot_create_execution_contract(self):
        for mutate in (lambda s:s.update(stage='awaiting_review'),lambda s:s.update(review_task='plan'),
                       lambda s:s['review'].update(decision='request_changes'),lambda s:s.update(plan_sha256='a'*64),
                       lambda s:s['review'].update(plan_sha256='b'*64)):
            s=copy.deepcopy(self.s);mutate(s)
            with self.assertRaises((ValueError,ValidationError)):contract(self.c,s,['tests/test_new.py'],['app.js'])

    def test_product_and_test_permissions_never_overlap(self):
        with self.assertRaises(ValueError):contract(self.c,self.s,['app.js'],['app.js'])
        with self.assertRaises(ValueError):contract(self.c,self.s,[],['app.js'])
        with self.assertRaises(ValueError):contract(self.c,self.s,['tests/test_new.py'],['tests/test_old.py'])
        with self.assertRaises(ValueError):contract(self.c,self.s,['tests/test_new.py'],['../app.js'])

    def test_r1_issue_preserves_all_criteria_without_assignment_or_dispatch(self):
        value=contract(self.c,self.s,['tests/test_new.py'],['app.js'])
        spec=issue_spec(value,dict(project_id='project'))
        self.assertEqual(spec['parent_issue_id'],'root')
        self.assertEqual(spec['status'],'todo')
        self.assertNotIn('assignee_id',spec)
        self.assertIn('A01: criterion',spec['description'])
        self.assertIn('no worker dispatch yet',spec['description'])
        self.assertIn('Do not edit product',spec['description'])

    def test_uncertain_creation_is_observed_without_another_post(self):
        import sqlite3
        import threading
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import patch
        from broker import remediation_execution as execution
        con=sqlite3.connect(':memory:');self.addCleanup(con.close);con.row_factory=sqlite3.Row
        execution.initialize(con)
        value=contract(self.c,self.s,['tests/test_new.py'],['app.js'])
        state=dict(stage='r1_issue_intent',execution_authorized=False,steps={'R1':{'stage':'provision_pending'}})
        import json
        con.execute('INSERT INTO remediation_executions VALUES(?,?,?)',('source',json.dumps(value),json.dumps(state)))
        @contextmanager
        def db():
            yield con
            con.commit()
        b=SimpleNamespace(LOCK=threading.RLock(),db=db)
        calls=[]
        def ensure(spec,*,allow_create):
            calls.append(allow_create)
            if allow_create:raise TimeoutError()
            return None if len(calls)==2 else dict(id='r1',identifier='EVAL-R1')
        fx=SimpleNamespace(issues=SimpleNamespace(request=lambda _:dict(project_id='project'),ensure=ensure))
        with patch.object(execution,'register'),patch.object(execution.planning,'Effects',return_value=fx):
            result=execution.provision_issue(b,'source')
            self.assertEqual(result['stage'],'r1_issue_observe')
            self.assertEqual(execution.provision_issue(b,'source')['stage'],'r1_issue_observe')
            result=execution.provision_issue(b,'source')
            self.assertEqual(result['stage'],'r1_provision_pending')
            self.assertFalse(result['execution_authorized'])
            self.assertEqual(execution.provision_issue(b,'source'),result)
        self.assertEqual(calls,[True,False,False])
