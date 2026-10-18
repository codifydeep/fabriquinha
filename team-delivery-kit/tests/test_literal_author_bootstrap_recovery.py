import copy
import json
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from execution_context import freeze,reference
from generic_harness_calibration import digest
from broker import literal_author_bootstrap_recovery as recovery
from broker import literal_maintenance_effects as lane,literal_maintenance_workflow as flow
import recover_literal_author_bootstrap as cli


class AuthorBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.cfg=dict(source=dict(author_task='original',issue_id='parent',prepared=dict(test_sha256={'tests/test.py':'a'*64})),
            author='author',cto='cto',reviewer='lead',test_path='tests/test.py',literal='NODE_HARNESS',counterexample={'qualified':True})
        self.s=dict(stage='blocked',category='native_author_failed',issue_id='child',revision=0,history=[],
            author_task=None,decisions={p:{} for p in ('triage','plan','permit')},marker='bound',wakeup_id='wake',
            canonical_base_recovery='base-proof',prepared=dict(volume='canonical-base'),
            source_reset=False,functional_red=False,delivery_approval=False)
        self.task=dict(id='failed',agent_id='author',issue_id='child',wakeup_id='wake',status='failed',error=recovery.ERROR,
            handoff_note=lane.expected_note(self.cfg,self.s,'author'))
        capsule=freeze('Product brief.','Product review.')
        self.parent=dict(issue_id='parent',enabled=True,author='author',reviewer='lead',techlead='lead',cto='cto',
            execution_context=capsule,review_instruction=reference(capsule,'review'),test_first=True,test_first_files=['tests/test.py'])
        self.old=dict(self.parent,issue_id='child',enabled=False)
        self.trial=dict(harness_maintenance_only=True,historic_functional_red=False,seed_previous_tests=True,
            seeded_edit_required=True,literal_maintenance=dict(source_task='original',config_sha256=digest(self.cfg)))
        self.binding=dict(task_id='failed',status='closed',agent_id='author',issue_id='child',
            request_id='request',scope='workspace:author:implementation:failed')
        self.events=[dict(method='initialize',success=1),dict(method='session/new',success=1)]

    def qualify(self,**changes):
        values=dict(cfg=self.cfg,s=self.s,task=self.task,binding=self.binding,events=self.events,
            tool_count=0,old_route=self.old,parent=self.parent,trial=self.trial);values.update(changes)
        recovery.qualify(**values)

    def test_exact_pre_prompt_failure_qualifies_without_source_retry_or_fake_red(self):
        self.qualify()
        for change in (dict(status='completed'),dict(agent_id='lead'),dict(wakeup_id='other'),dict(error='different'),
                dict(handoff_note='untrusted '+self.task['handoff_note'])):
            with self.assertRaises(ValueError):self.qualify(task={**self.task,**change})
        for change in (dict(author_bootstrap_recovery='used'),dict(author_task='already-delivered'),
                dict(revision=1),dict(stage='author_wait'),dict(delivery_approval=True)):
            with self.assertRaises(ValueError):self.qualify(s={**self.s,**change})

    def test_prompt_tools_live_lease_or_changed_route_prevent_recovery(self):
        for change in (dict(tool_count=1),dict(events=self.events+[dict(method='session/prompt',success=0)]),
                dict(binding={**self.binding,'status':'running'}),dict(old_route=lane.maintenance_route(self.parent,'child')),
                dict(trial={**self.trial,'old_red':{}})):
            with self.assertRaises(ValueError):self.qualify(**change)

    def test_constructor_reproduces_old_guard_and_passes_corrected_actual_contract(self):
        b=SimpleNamespace(__file__=str(Path(__file__).resolve().parents[1]/'broker/server.py'))
        issue=dict(id='child',title='Literal maintenance',description='An isolated controller-owned maintenance card.')
        with patch.dict('os.environ',{'BROKER_WORKER_IMAGE':'sha256:'+'b'*64,'BROKER_TEST_ARTIFACT_GATE':'1'}):
            proof=recovery.probe(b,self.cfg,self.s,self.task,self.old,lane.maintenance_route(self.parent,'child'),
                self.trial,['/workspace/tests/test.py','/workspace/app.js'],issue)
        self.assertEqual(proof['old_guard_rejection'],'execution context role or route mismatch')
        self.assertFalse(proof['native_execution']);self.assertFalse(proof['delivery_approval'])
        self.assertLessEqual(proof['new_prompt_characters'],10000)
        self.assertIn('execution_context',self.parent)

    def database(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        con.executescript('CREATE TABLE literal_maintenance_workflows(source_task PRIMARY KEY,config,state);'
            'CREATE TABLE delivery_routes(issue_id PRIMARY KEY,config);CREATE TABLE test_revision_trials(issue_id,config);'
            'CREATE TABLE issue_editables(issue_id,path);CREATE TABLE native_bindings(task_id,agent_id,issue_id,request_id,scope);'
            'CREATE TABLE leases(request_id,status);CREATE TABLE acp_events(request_id,method,success);'
            'CREATE TABLE tool_events(request_id);CREATE TABLE snapshots(task_id);CREATE TABLE test_first_red(issue_id);')
        con.execute('INSERT INTO literal_maintenance_workflows VALUES(?,?,?)',('original',json.dumps(self.cfg),json.dumps(self.s)))
        for route in (self.parent,self.old):con.execute('INSERT INTO delivery_routes VALUES(?,?)',(route['issue_id'],json.dumps(route)))
        con.execute('INSERT INTO test_revision_trials VALUES(?,?)',('child',json.dumps(self.trial)))
        con.executemany('INSERT INTO issue_editables VALUES(?,?)',[('child','/workspace/tests/test.py'),('child','/workspace/app.js')])
        con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',tuple(self.binding[k] for k in ('task_id','agent_id','issue_id','request_id','scope')))
        con.execute('INSERT INTO leases VALUES(?,?)',('request','closed'))
        con.executemany('INSERT INTO acp_events VALUES(?,?,?)',[('request',e['method'],e['success']) for e in self.events]);con.commit()
        return con,SimpleNamespace(LOCK=threading.RLock(),db=lambda:con,issue_base=lambda issue:dict(volume='canonical-base'))

    def test_registration_preserves_old_route_and_failure_and_cannot_rearm_again(self):
        con,b=self.database();fx=Mock();fx.plans.task.return_value=self.task
        with patch.object(recovery.maintenance,'current',return_value=dict(stage='sealed',operation_id='window')),\
                patch.object(recovery.maintenance,'native_active',return_value=[]),patch.object(lane,'Effects',return_value=fx),\
                patch.object(flow,'authenticate'),patch.object(recovery,'probe',return_value={'native_execution':False,'new_prompt_characters':3000}) as probe:
            receipt=recovery.register(b,'original','failed')
            self.assertEqual(recovery.register(b,'original','failed'),receipt)
            with self.assertRaises(ValueError):recovery.register(b,'original','different-failure')
        probe.assert_called_once();fx.plans.task.assert_called_once()
        actual=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id="child"').fetchone()[0])
        self.assertEqual(actual,lane.maintenance_route(self.parent,'child'))
        self.assertEqual(json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id="parent"').fetchone()[0]),self.parent)
        self.assertEqual(receipt['old_route'],self.old);self.assertEqual(receipt['previous_state'],self.s)
        state=json.loads(con.execute('SELECT state FROM literal_maintenance_workflows').fetchone()[0])
        self.assertEqual(state['stage'],'author_dispatch');self.assertEqual(state['decisions'],self.s['decisions'])
        self.assertFalse(receipt['source_author_retry_authorized']);self.assertFalse(receipt['historical_http_absence_proven'])
        self.assertTrue(receipt['pre_transport_guard_rejection_proven'])
        self.assertEqual(con.execute('SELECT count(*) FROM literal_author_bootstrap_recoveries').fetchone()[0],1)

    def test_repaired_author_note_gets_distinct_marker_without_changing_other_phase_contracts(self):
        fixed={**self.s,'author_bootstrap_recovery':'c'*64}
        self.assertNotEqual(flow.instruction(self.cfg,self.s,'author'),flow.instruction(self.cfg,fixed,'author'))
        self.assertEqual(flow.instruction(self.cfg,self.s,'triage'),flow.instruction(self.cfg,fixed,'triage'))
        self.assertLessEqual(len(flow.instruction(self.cfg,fixed,'author')),3800)
        compile(cli.PROGRAM,'operator-program','exec')
