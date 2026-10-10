import copy
import unittest
import contextlib
import io
import json
import pathlib
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch
from broker.review_successor_withdrawal import prepare
from broker.technical_remediation_plan import digest


class SuccessorWithdrawalTests(unittest.TestCase):
    def fixture(self):
        review={'review_task':'review','decision':{'action':'reject_test_revision'},
                'technical_replan_certificate':{'manifest':'a'*64},
                'rejection_diagnosis':{'decision':{'action':'request_test_revision'}}}
        parent_contract={'source_task':'parent','run_id':'parent-run'}
        parent={'stage':'r1_base_qualified','issue_id':'original','execution_authorized':False,
                'contract_sha256':digest(parent_contract)}
        config={'intake_kind':'rejected_remediation_r1_v1','source_task':'author','source_issue':'original',
                'volume':'frozen','cto':'cto','reviewer':'lead',
                'diagnostic_decision':review['rejection_diagnosis']['decision'],
                'r1_feedback':{'previous_source':'parent','round':2,'operation':'remediation_r1_review_feedback_v1',
                    'execution_authorized':False,'revision_depth_reset':False,'review_task':'review',
                    'review_decision_sha256':digest(review['decision']),
                    'certificate':review['technical_replan_certificate'],
                    'previous_run':'parent-run','previous_execution_sha256':digest(parent_contract)}}
        parent['superseded_by_feedback']={'source_task':'author','config_sha256':digest(config)}
        admission={'stage':'blocked','category':'superseded_by_r1_feedback','next_source':'author',
                   'superseded_admission':{'stage':'await_delivery_gates'}}
        route={'enabled':False,'issue_id':'original','cto':'cto','techlead':'lead'}
        red={'task_id':'author','volume':'frozen'}
        state={'stage':'plan_dispatch','owner':'cto','issue_id':'successor','identifier':'EVAL-X',
               'execution_authorized':False,'release_homologated':False}
        return [config,state,route,red,review,'parent',parent,admission,[],[],parent_contract]

    def test_preserve_every_prior_record_and_consumed_budget_without_author_restart(self):
        args=self.fixture();before=copy.deepcopy(args);held,proof=prepare(*args)
        self.assertEqual(args,before)
        self.assertEqual(held['stage'],'blocked')
        self.assertEqual(proof['prior_state'],args[1]);self.assertEqual(proof['prior_config'],args[0])
        self.assertEqual(proof['prior_parent'],args[6]);self.assertEqual(proof['prior_admission'],args[7])
        self.assertEqual(proof['consumed_feedback_round'],2)
        for key in ('revision_depth_reset','author_restarted','delivery_approval'):self.assertFalse(proof[key])

    def test_pending_remote_effects_changed_lineage_or_unheld_parent_are_rejected(self):
        for kind in ('task','wakeup','dispatch_intent','unknown_field','enabled','volume','parent','admission','round','contract'):
            args=copy.deepcopy(self.fixture())
            if kind=='task':args[8]=[{'status':'completed'}]
            if kind=='wakeup':args[9]=[{'enabled':False}]
            if kind=='dispatch_intent':args[1]['stage']='observe_dispatch'
            if kind=='unknown_field':args[1]['marker']='uncertain'
            if kind=='enabled':args[2]['enabled']=True
            if kind=='volume':args[3]['volume']='other'
            if kind=='parent':args[6]['r1_gate']={'approved':True}
            if kind=='admission':args[7]['stage']='requested'
            if kind=='round':args[0]['r1_feedback']['round']=0
            if kind=='contract':args[10]['run_id']='changed'
            with self.assertRaises(ValueError,msg=kind):prepare(*args)

    def test_atomic_migration_and_failure_rollback_keep_parent_admission_held(self):
        from broker import review_reconsideration as migration,controller_maintenance,native,handoff_runtime
        from broker import test_revision_review,test_review_replan_certificate,handoffs
        for fail in (True,False,'execution_effect'):
            with self.subTest(fail=fail),tempfile.TemporaryDirectory() as directory:
                config,state,route,red,review,parent_source,parent,admission,_,_,parent_contract=self.fixture()
                review.update(status='blocked',source_task=red['task_id'],manifest_sha256='a'*64)
                review['rejection_diagnosis'].update(status='revision_required',decision_task='cto-task',target='cto')
                red.update(issue_id='original',red={'manifest_sha256':'a'*64})
                root=pathlib.Path(directory);path=root/'state.sqlite'
                (root/'native.json').write_text(json.dumps({'token':'fixture','workspace_id':'fixture'}))
                @contextlib.contextmanager
                def db():
                    con=sqlite3.connect(path);con.row_factory=sqlite3.Row
                    try:
                        with con:yield con
                    finally:con.close()
                b=SimpleNamespace(LOCK=threading.RLock(),STATE=root,db=db)
                with db() as con:
                    for sql in ('CREATE TABLE test_revision_trials(issue_id TEXT,config TEXT,state TEXT)',
                                'CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)',
                                'CREATE TABLE test_first_red(issue_id TEXT,receipt TEXT)',
                                'CREATE TABLE technical_remediation_plans(source_task TEXT,config TEXT,state TEXT)',
                                'CREATE TABLE remediation_executions(source_task TEXT,contract TEXT,state TEXT)',
                                'CREATE TABLE remediation_admissions(source_task TEXT,state TEXT)',
                                'CREATE TABLE leases(status TEXT)'):con.execute(sql)
                    handoffs.initialize(con)
                    con.execute('INSERT INTO test_revision_trials VALUES(?,?,?)',('original',json.dumps({'reviewer':'lead'}),json.dumps(review)))
                    con.execute('INSERT INTO delivery_routes VALUES(?,?)',('original',json.dumps(route)))
                    con.execute('INSERT INTO test_first_red VALUES(?,?)',('original',json.dumps(red)))
                    con.execute('INSERT INTO technical_remediation_plans VALUES(?,?,?)',('author',json.dumps(config),json.dumps(state)))
                    con.execute('INSERT INTO remediation_executions VALUES(?,?,?)',('parent',json.dumps(parent_contract),json.dumps(parent)))
                    con.execute('INSERT INTO remediation_admissions VALUES(?,?)',('parent',json.dumps(admission)))
                    if fail=='execution_effect':
                        con.execute('INSERT INTO remediation_admissions VALUES(?,?)',('author',json.dumps({'stage':'requested'})))
                task={'id':'cto-task','status':'completed'}
                reviewer={'id':'review','status':'completed','issue_id':'original'}
                fx=SimpleNamespace(decision=lambda t:review['decision'] if t['id']=='review' else review['rejection_diagnosis']['decision'],read_evidence=lambda _: {})
                original_save=handoffs.save
                with patch.object(controller_maintenance,'current',return_value={'stage':'sealed','operation_id':'op'}), \
                        patch.object(controller_maintenance,'native_active',return_value=False), \
                        patch.object(native,'task_record',side_effect=[task,reviewer]), \
                        patch.object(native,'issue_task_runs',return_value=[]), \
                        patch.object(handoff_runtime,'Effects',return_value=fx), \
                        patch.object(test_revision_review,'validate_evidence'), \
                        patch.object(test_review_replan_certificate,'qualify',return_value=review['technical_replan_certificate']), \
                        patch.object(migration.urllib.request,'urlopen',return_value=io.BytesIO(b'[]')), \
                        patch.object(handoffs,'save',side_effect=RuntimeError('simulated write failure') if fail else original_save):
                    if fail=='execution_effect':
                        with self.assertRaises(ValueError):migration.upgrade(b,'original','op',withdraw_pending_successor=True)
                    elif fail:
                        with self.assertRaises(RuntimeError):migration.upgrade(b,'original','op',withdraw_pending_successor=True)
                    else:
                        result=migration.upgrade(b,'original','op',withdraw_pending_successor=True)
                        self.assertFalse(result['delivery_approval'])
                with db() as con:
                    installed_route=json.loads(con.execute('SELECT config FROM delivery_routes').fetchone()[0])
                    installed_trial=json.loads(con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
                    installed_successor=json.loads(con.execute('SELECT state FROM technical_remediation_plans').fetchone()[0])
                    self.assertEqual(json.loads(con.execute('SELECT state FROM remediation_admissions').fetchone()[0]),admission)
                    self.assertEqual(json.loads(con.execute('SELECT state FROM remediation_executions').fetchone()[0]),parent)
                    if fail:
                        self.assertEqual(installed_route,route);self.assertEqual(installed_trial,review)
                        self.assertEqual(installed_successor,state)
                        self.assertEqual(con.execute('SELECT count(*) FROM delivery_handoff_events').fetchone()[0],0)
                    else:
                        self.assertTrue(installed_route['enabled'])
                        self.assertEqual(installed_trial['rejection_diagnosis']['status'],'dispatch_intent')
                        self.assertEqual(installed_successor['stage'],'blocked')
                        self.assertEqual(installed_successor['review_mediation_withdrawal']['consumed_feedback_round'],2)
                        self.assertEqual(con.execute('SELECT stage FROM delivery_handoffs').fetchone()[0],'test_review_cto_diagnosis')
