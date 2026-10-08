import copy
import json
import sqlite3
import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from broker import timer_scope_replan as module,handoffs
from broker.timer_scope_replan import observation,config
from broker.technical_remediation_plan import digest,instruction
from test_request_scope_replan import RequestScopeReplanTests
from service_mode_harness_qualification import TEST,PRODUCT


def measured():
    return dict(source_task='source',issue_id='r2',snapshot_readonly=True,network='none',image='sha256:'+'1'*64,
        result=dict(operation='immutable_harness_timer_observation_v1',instrumentation_preserved_report=True,
            snapshot_modified=False,assertions_modified=False,test_edits_authorized=False,product_green=False,delivery_approval=False,
            manifest_sha256='f'*64,test_sha256='d'*64,product_sha256='e'*64,
            original_report=dict(interval_count=1,pending_interval_count=1,timer_count=0,pending_timer_count=0,
                after_ok={'calls':1},pending_observed={'calls':1},pending_issued=1,mode_request_total=9),
            original_suite=dict(tests=15,failures=2,errors=0,skipped=0,unexpected_successes=0,expected_failures=0,
                failed_methods=['test_no_timers_are_armed_for_the_probe','test_pending_probe_shows_checking_then_terminal_demo']),
            timer_observation=dict(timers=[dict(ms=2000,load_id=i,stack=['    at /delivery/app/static/app.js:686:1']) for i in range(1,10)],
                captures=[c for i in range(1,9) for c in [dict(kind='timeout',load_id=i,slice_start=0,total=0),
                    dict(kind='interval',load_id=i,slice_start=i-1,total=i)]])))


class TimerPlanTests(unittest.TestCase):
    def fixture(self):
        _,_,_,ref,previous,route,_=RequestScopeReplanTests().fixture()
        ref.update(original_depth=2,readonly_tests=[TEST],editable_files=[PRODUCT])
        data=dict(source_task='source',recipient_task='cto-task',wakeup_id='cto-wake',target='cto',
            decision={'action':'escalate_cto','optional_files':[]},unsupported_experiment_recovery={'preserved':True},
            validation_failure=dict(source_task='source',volume='frozen',phase='frozen_green',category='executed_test_failure',exit_code=1))
        task=dict(id='cto-task',agent_id='cto',issue_id='r2',status='completed',wakeup_id='cto-wake')
        route['enabled']=True
        reads={'/evidence/candidate/'+p:dict(lines=10,total_lines=10) for p in (TEST,PRODUCT)}
        return measured(),ref,previous,route,data,task,reads

    def test_new_plan_preserves_acceptance_ancestry_and_requires_new_controls(self):
        args=self.fixture();value=config(*args)
        self.assertEqual(value['criteria'],args[2]['criteria'])
        self.assertEqual(value['revision_lineage'],args[2]['revision_lineage'])
        self.assertEqual(value['amendment']['seed_red'],args[1]['red'])
        self.assertFalse(value['amendment']['execution_authorized'])
        self.assertFalse(value['amendment']['revision_depth_reset'])
        self.assertIn('probe_timer_behavioral_negative_controls',value['amendment']['required_gates'])
        note=instruction(value,{'stage':'plan_dispatch'})
        self.assertIn('indicator-only callbacks',note);self.assertIn('not subtract a constant',note)
        self.assertNotIn('fails Node syntax compilation',note)
        self.assertIn('A01',note)

    def test_unchanged_original_report_and_each_load_required(self):
        for change in ('timers','calls','permissions','slice','suite'):
            v=measured()
            if change=='timers':v['result']['timer_observation']['timers'][0]['stack']=['elsewhere']
            elif change=='calls':v['result']['original_report']['after_ok']['calls']=2
            elif change=='permissions':v['result']['test_edits_authorized']=True
            elif change=='slice':v['result']['timer_observation']['captures'][3]['slice_start']=0
            else:v['result']['original_suite']['skipped']=1
            with self.subTest(change=change),self.assertRaises(ValueError):observation(v)

    def test_independence_original_seed_and_full_reads_are_mandatory(self):
        for change in ('author','test','criteria','read','task','scope'):
            args=list(copy.deepcopy(self.fixture()))
            if change=='author':args[3]['cto']='author'
            elif change=='test':args[0]['result']['test_sha256']='0'*64
            elif change=='criteria':args[1]['criteria']={'A01':'weakened'}
            elif change=='read':args[6]['/evidence/candidate/'+TEST]['lines']=9
            elif change=='task':args[5]['status']='running'
            else:args[4]['validation_failure']['phase']='unknown'
            with self.subTest(change=change),self.assertRaises(ValueError):config(*args)
        args=list(self.fixture());args[2]['amendment']['kind']='timer_provenance'
        args[1]['execution_contract_sha256']=digest(args[2])
        with self.assertRaises(ValueError):config(*args)

    def test_intake_failure_is_visible_and_not_repeated(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        handoffs.initialize(con)
        con.execute('CREATE TABLE leases(status TEXT)')
        con.execute('CREATE TABLE frozen_harness_observations(source_task TEXT PRIMARY KEY,receipt TEXT)')
        con.execute('INSERT INTO frozen_harness_observations VALUES (?,?)',('source',json.dumps(measured())))
        handoffs.save(con,'source','r2','technical_decision_required','cto',dict(source_task='source'),0)
        @contextmanager
        def db():yield con
        b=SimpleNamespace(db=db,LOCK=threading.RLock())
        with patch.object(module,'register',side_effect=ValueError('qualified hold')) as register:
            module.tick(b);module.tick(b);register.assert_called_once_with(b,'source')
        row=handoffs.load(con,'source');data=json.loads(row['data'])
        self.assertEqual(row['stage'],'technical_decision_required')
        self.assertEqual(data['timer_plan_intake']['stage'],'blocked')
        self.assertIn('no identical retry',data['required_action'])

    def test_crash_before_local_registration_resumes_same_readonly_intent(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        handoffs.initialize(con)
        con.execute('CREATE TABLE leases(status TEXT)')
        con.execute('CREATE TABLE frozen_harness_observations(source_task TEXT PRIMARY KEY,receipt TEXT)')
        con.execute('CREATE TABLE timer_plan_intakes(source_task TEXT PRIMARY KEY,state TEXT)')
        con.execute('INSERT INTO frozen_harness_observations VALUES (?,?)',('source',json.dumps(measured())))
        con.execute('INSERT INTO timer_plan_intakes VALUES (?,?)',('source',json.dumps(dict(stage='qualification_intent',at=1))))
        handoffs.save(con,'source','r2','technical_decision_required','cto',dict(source_task='source'),0)
        @contextmanager
        def db():yield con
        b=SimpleNamespace(db=db,LOCK=threading.RLock())
        with patch.object(module,'register',return_value=dict(stage='issue_intent',execution_authorized=False)) as register:
            module.tick(b);module.tick(b);register.assert_called_once_with(b,'source')
        self.assertEqual(con.execute('SELECT count(*) FROM timer_plan_intakes').fetchone()[0],1)
