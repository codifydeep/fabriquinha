import copy
import json
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from broker import failed_candidate_admission as admission


class FailedCandidateAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
        self.addCleanup(self.con.close)
        for sql in ('CREATE TABLE delivery_handoffs(source_task,issue_id,stage,data,updated)',
                'CREATE TABLE delivery_routes(issue_id,config)',
                'CREATE TABLE native_bindings(request_id,issue_id)',
                'CREATE TABLE leases(request_id,status)',
                'CREATE TABLE snapshots(task_id,volume,status)'):
            self.con.execute(sql)
        self.route=dict(issue_id='issue',author='author',cto='cto',techlead='lead',enabled=True,contract_sha256='c'*64)
        self.decision=dict(action='request_correction',reason='Wire the existing loader',optional_files=[])
        self.data=dict(source_task='source',failed_execution_diagnostic={'volume':'frozen'},
            failed_candidate_plan=dict(cto_task='cto-task',edit_files=['app.js'],
                proposal=self.decision,read_paths=['/evidence/candidate/app.js']),
            failed_candidate_plan_review=dict(techlead_task='lead-task',decision=self.decision))
        self.con.execute('INSERT INTO delivery_handoffs VALUES(?,?,?,?,?)',
            ('source','issue','technical_decision_required',json.dumps(self.data),2))
        self.con.execute('INSERT INTO delivery_routes VALUES(?,?)',('issue',json.dumps(self.route)))
        self.con.execute('INSERT INTO delivery_handoffs VALUES(?,?,?,?,?)',
            ('prior','issue','superseded','{}',1))
        self.con.execute('INSERT INTO snapshots VALUES(?,?,?)',('prior','old-volume','complete'))
        self.con.execute('INSERT INTO delivery_handoffs VALUES(?,?,?,?,?)',('prior2','issue','superseded','{}',1))
        self.con.execute('INSERT INTO snapshots VALUES(?,?,?)',('prior2','old-volume2','complete'))
        self.tasks={task:dict(id=task,issue_id='issue',agent_id=actor,status=status,created_at=created)
            for task,actor,status,created in [('source','author','failed','2'),('prior','author','completed','1'),
                ('prior2','author','completed','1'),
                ('cto-task','cto','completed','3'),('lead-task','lead','completed','4')]}
        self.effects=SimpleNamespace(settings={},b=SimpleNamespace(OWNER='owned',OFFLINE_IMAGE='fixed',
            docker=lambda *_:{'Labels':{'delivery-kit.owner':'owned','delivery-kit.source-task':'source'}}),
            decision=lambda _:self.decision,
            read_evidence=lambda _:{'/evidence/candidate/app.js':{'lines':2,'total_lines':2}},
            author_edit_scope=lambda _:['app.js'],test_first_red=lambda *a,**k:{'red':{'frozen':'red'}})
        def inventory(con,source,*args):
            return dict(manifest_sha256='a'*64,product_sha256={'app.js':('b' if source.startswith('prior') else 'c')*64},
                test_sha256={'tests/test_new.py':'d'*64},baseline_test_sha256={'tests/test_old.py':'e'*64})
        for target,value in [('native.task_record',lambda settings,task,actor:self.tasks[task]),
                ('native.issue_task_runs',lambda *_:list(self.tasks.values())),
                ('bound_failure_context.verified_failed_diagnostic',lambda *_:True),
                ('handoffs.repeated_corrections',lambda *_:2),('execution.validator_inventory',inventory)]:
            patcher=patch('broker.failed_candidate_admission.'+target,side_effect=value)
            patcher.start();self.addCleanup(patcher.stop)

    def test_facts_come_from_installed_scope_native_tasks_and_fixed_receipts(self):
        facts=admission.facts(self.con,self.route,self.data,self.effects)
        self.assertEqual(facts['identical_corrections'],2)
        self.assertEqual(facts['volume'],'frozen')
        self.assertEqual(facts['previous_product_sha256'],[{'app.js':'b'*64},{'app.js':'b'*64}])
        self.assertTrue(facts['independent_tasks_verified'])

    def test_missing_prior_snapshot_does_not_invent_changed_preconditions(self):
        self.con.execute('DELETE FROM snapshots WHERE task_id=?',('prior2',))
        with self.assertRaisesRegex(ValueError,'complete snapshot inventory'):
            admission.facts(self.con,self.route,self.data,self.effects)

    def test_new_native_author_active_lease_or_incomplete_reads_reject_admission(self):
        self.tasks['new']=dict(id='new',agent_id='author',issue_id='issue',status='queued',created_at='5')
        with self.assertRaises(ValueError):admission.facts(self.con,self.route,self.data,self.effects)
        self.tasks.pop('new')
        self.con.execute('INSERT INTO native_bindings VALUES(?,?)',('request','issue'))
        self.con.execute('INSERT INTO leases VALUES(?,?)',('request','running'))
        with self.assertRaises(ValueError):admission.facts(self.con,self.route,self.data,self.effects)
        self.con.execute('DELETE FROM leases')
        self.effects.read_evidence=lambda _:{'/evidence/candidate/app.js':{'lines':1,'total_lines':2}}
        with self.assertRaises(ValueError):admission.facts(self.con,self.route,self.data,self.effects)

    def test_stale_durable_data_wrong_role_or_volume_ownership_rejected(self):
        data=copy.deepcopy(self.data);data['altered']=True
        with self.assertRaises(ValueError):admission.facts(self.con,self.route,data,self.effects)
        self.tasks['cto-task']['agent_id']='author'
        with self.assertRaises(ValueError):admission.facts(self.con,self.route,self.data,self.effects)
        self.tasks['cto-task']['agent_id']='cto'
        self.effects.b.docker=lambda *_:{'Labels':{'delivery-kit.owner':'external'}}
        with self.assertRaises(ValueError):admission.facts(self.con,self.route,self.data,self.effects)
