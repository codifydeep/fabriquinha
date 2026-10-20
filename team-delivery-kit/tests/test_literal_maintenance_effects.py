import contextlib
import copy
import io
import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch,Mock
from broker import literal_maintenance_effects as effects
from broker import literal_maintenance_workflow as flow
from broker import harness_repair_task
from broker import test_revision_review,author_feedback_admission
import literal_test_maintenance as inspector
import enroll_literal_maintenance as enrollment


class LiteralEffectsTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
        self.addCleanup(self.con.close)
        self.cfg=dict(source=dict(author_task='source',issue_id='original',criteria={}),
            author='author',cto='cto',reviewer='lead',parent_issue_id='diagnostic',
            test_path='tests/test.py',literal='NODE_HARNESS',counterexample={})
        flow.register(self.con,self.cfg)
        self.s=dict(stage='author_wait',issue_id='maintenance',owner='author',marker='bound',
            phase_started=100,wakeup_id='wake',revision=0,decisions={})

    def save(self):
        self.con.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',
            (json.dumps(self.s,sort_keys=True),'source'))

    def task(self):
        return dict(id='new-task',agent_id='author',issue_id='maintenance',wakeup_id='wake',
            handoff_note=effects.expected_note(self.cfg,self.s,'author'))

    def test_feedback_trial_uses_immediate_predecessor_without_relaxing_real_unique_parent_constraint(self):
        test_revision_review.initialize(self.con)
        self.con.execute('INSERT INTO test_revision_trials VALUES(?,?,?,?)',('old-maintenance','original','{}','{}'))
        self.con.execute('CREATE TABLE issue_editables(issue_id,path)')
        self.con.execute('CREATE TABLE issue_test_commands(issue_id,command)')
        self.con.execute('CREATE TABLE delivery_routes(issue_id,config)')
        self.con.execute('INSERT INTO issue_editables VALUES(?,?)',('original','/workspace/tests/test.py'))
        self.con.execute('INSERT INTO issue_test_commands VALUES(?,?)',('original','python -m unittest discover'))
        self.con.execute('INSERT INTO delivery_routes VALUES(?,?)',('original','{}'));self.con.commit()
        cfg=dict(self.cfg,workflow_key='rejected-author',parent_issue_id='old-maintenance',image='sha256:'+'a'*64,
            base=dict(base_sha='b'*40,manifest_sha256='c'*64,volume='owned-original-base'),
            feedback_strategy=dict(policy={'source_task':'rejected-author'},qualification={}))
        state=dict(self.s,issue_id='feedback-maintenance',decisions=dict(plan=dict(receipt={'task_id':'cto-plan'}),permit=dict(receipt={'task_id':'lead-sponsor'})))
        labels={'delivery-kit.owner':'owner','delivery-kit.issue-id':'feedback-maintenance','delivery-kit.base-sha':'b'*40}
        self.con.execute('CREATE TABLE literal_feedback_volumes(source_task TEXT PRIMARY KEY,identity TEXT,state TEXT)')
        self.con.execute('INSERT INTO literal_feedback_volumes VALUES(?,?,?)',('rejected-author',
            json.dumps(dict(name='delivery-kit-test-base-feedback-maintenance',labels=labels)),json.dumps(dict(stage='create_intent'))))
        self.con.commit()
        @contextlib.contextmanager
        def db():
            with self.con:yield self.con
        b=SimpleNamespace(db=db,OWNER='owner',PREFIX='delivery-kit-test',register_issue_base=Mock(),register_issue_editables=Mock(),
            docker=lambda *args:dict(Labels=labels))
        fx=object.__new__(effects.Effects);fx.b=b
        with patch.object(effects.validation_job,'run',return_value=dict(exit_code=0,output='base_copy_complete')),\
                patch.object(effects.handoff_runtime,'register'),patch.object(author_feedback_admission,'arm',return_value=dict(stage='armed')):
            fx.prepare(cfg,state);fx.prepare(cfg,state)
        rows=[tuple(r) for r in self.con.execute('SELECT issue_id,parent_issue FROM test_revision_trials ORDER BY issue_id')]
        self.assertEqual(rows,[('feedback-maintenance','old-maintenance'),('old-maintenance','original')])
        trial=json.loads(self.con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',('feedback-maintenance',)).fetchone()[0])
        self.assertEqual(trial['parent_issue'],'old-maintenance')
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute('INSERT INTO test_revision_trials VALUES(?,?,?,?)',('duplicate','old-maintenance','{}','{}'))

    def test_exact_author_note_identity_and_deadline_are_required(self):
        with patch.object(effects.flow,'instruction',return_value='phase-only'),patch.object(effects.time,'time',return_value=101):
            task=self.task();self.assertEqual(effects.authorize_phase(self.con,self.cfg,self.s,task,'author',{}),self.s)
            for altered in (dict(agent_id='cto'),dict(issue_id='original'),dict(wakeup_id='other'),
                    dict(handoff_note='untrusted '+task['handoff_note'])):
                with self.assertRaises(ValueError):effects.authorize_phase(self.con,self.cfg,self.s,{**task,**altered},'author',{})
            with patch.object(effects.time,'time',return_value=2000):
                with self.assertRaises(ValueError):effects.authorize_phase(self.con,self.cfg,self.s,task,'author',{})

    def test_lost_ack_only_observes_exact_intent_and_keeps_original_deadline(self):
        self.s['stage']='author_observe';self.s.pop('wakeup_id');self.save()
        with patch.object(effects.flow,'instruction',return_value='phase-only'),patch.object(effects.time,'time',return_value=101),\
                patch.object(effects.native,'ensure_unit_start',return_value={'id':'wake'}) as wake:
            result=effects.authorize_phase(self.con,self.cfg,self.s,self.task(),'author',{})
        self.assertEqual(result['stage'],'author_wait');self.assertEqual(result['phase_started'],100)
        self.assertFalse(wake.call_args.kwargs['allow_create'])
        self.assertEqual(effects.current(self.con,'maintenance')[1],result)

    def test_triage_and_scope_proposals_do_not_mount_author_artifacts(self):
        for phase in ('triage_wait','plan_wait','permit_wait','author_wait','blocked'):
            self.s['stage']=phase;self.save()
            self.assertEqual(effects.mounts(SimpleNamespace(db=lambda:self.con),
                dict(issue_id='maintenance',agent_id='lead',request_id='request')),[])

    def test_review_by_author_is_rejected_before_artifact_access(self):
        self.s['stage']='review_wait';self.save()
        with self.assertRaises(ValueError):effects.mounts(SimpleNamespace(db=lambda:self.con),
            dict(issue_id='maintenance',agent_id='author',request_id='request'))

    def test_cto_receives_only_two_rejected_readonly_snapshots_not_mutable_author_workspace(self):
        self.cfg['source']['candidate_volume']='original-frozen'
        self.s.update(stage='diagnose_wait',snapshot={'volume':'revision-one'},author_task='author-one',
            history=[{'snapshot':{'volume':'revision-zero'}}]);self.save()
        self.con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT)')
        self.con.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
        self.con.execute("INSERT INTO native_bindings VALUES('request','diagnose-task')")
        self.con.execute("INSERT INTO leases VALUES('request','running')")
        b=SimpleNamespace(db=lambda:self.con,OWNER='owner',docker=lambda *args:
            {'Labels':{'delivery-kit.owner':'owner','delivery-kit.source-task':'author-one'}})
        fx=SimpleNamespace(verify=lambda cfg:None,plans=SimpleNamespace(task=lambda *args:{'id':'diagnose-task'}),settings={})
        with patch.object(effects,'Effects',return_value=fx),patch.object(flow,'authenticate'),\
                patch.object(flow,'authenticate_rejections') as history,patch.object(effects,'authorize_phase',return_value=self.s) as auth:
            mounts=effects.mounts(b,dict(issue_id='maintenance',agent_id='cto',request_id='request'))
        history.assert_called_once();self.assertEqual(auth.call_args.args[4],'diagnose')
        self.assertEqual(mounts,[dict(Type='volume',Source='revision-zero',Target='/evidence/previous',ReadOnly=True),
            dict(Type='volume',Source='revision-one',Target='/evidence/candidate',ReadOnly=True)])
        with self.assertRaises(ValueError):effects.mounts(b,dict(issue_id='maintenance',agent_id='lead',request_id='request'))

    def test_cto_decision_requires_complete_actual_reads_of_both_frozen_tests(self):
        self.s['stage']='diagnose_wait';self.con.execute('CREATE TABLE tool_events(request_id TEXT,tool_count INTEGER)')
        fx=object.__new__(effects.Effects);fx.b=SimpleNamespace(db=lambda:self.con)
        fx.old=SimpleNamespace(binding=lambda *args:{'request_id':'request'})
        actual=dict(id='diagnose-task',agent_id='cto',issue_id='maintenance',wakeup_id='wake',status='completed',
            result={'output':json.dumps(dict(action='request_test_revision',reason='A hypothesis, not an executed experiment',optional_files=[]))})
        paths=['/evidence/'+r+'/tests/test.py' for r in ('candidate','previous')]
        reads={p:dict(lines=10,total_lines=10) for p in paths}
        fx.plans=SimpleNamespace(task=lambda *args:actual,reads=lambda *args:reads)
        with patch.object(flow,'instruction',return_value='diagnosis-only'):
            actual['handoff_note']=effects.expected_note(self.cfg,self.s,'diagnose')
            self.assertEqual(fx.decision(self.cfg,self.s,'diagnose',actual)['read_evidence'],reads)
            reads[paths[1]]['lines']=9
            with self.assertRaises(ValueError):fx.decision(self.cfg,self.s,'diagnose',actual)

    def test_registration_does_not_authorize_unrelated_or_pre_permit_work(self):
        self.save();self.assertFalse(effects.registered_author(self.con,'maintenance','author'))
        self.s['decisions']={p:{} for p in ('triage','plan','permit')};self.save()
        self.assertTrue(harness_repair_task.registered_author(self.con,'maintenance','author'))
        self.assertFalse(harness_repair_task.registered_author(self.con,'maintenance','cto'))
        self.assertFalse(harness_repair_task.registered_author(self.con,'original','author'))

    def test_current_context_uses_new_exact_binding_instead_of_archived_instructions(self):
        context=dict(title='current',description='phase-only',handoff_note='bound')
        with patch.object(effects,'author_context',return_value=context) as current:
            self.assertEqual(harness_repair_task.current_maintenance_context(self.con,{'id':'maintenance'},{'id':'new'}),context)
        current.assert_called_once()

    def test_inspector_error_is_bounded_json_without_exception_text_or_success(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):result=inspector.main([])
        self.assertEqual(result,1);value=json.loads(output.getvalue())
        self.assertEqual(value['failure'],'ValueError');self.assertFalse(value['delivery_approval'])
        self.assertFalse(value['python_assertions_executed'])

    def test_enrollment_accepts_only_exact_namespace_and_source_uuid(self):
        source='11111111-1111-4111-8111-111111111111'
        self.assertEqual(enrollment.target('delivery-kit-port2',source),'delivery-kit-port2-execution-broker-1')
        for namespace,identity in (('toso-one',source),('delivery-kit-../other',source),('delivery-kit-port2','source')):
            with self.assertRaises(ValueError):enrollment.target(namespace,identity)
        compile(enrollment.PROGRAM,'enrollment-program','exec')

    def test_backup_embedded_program_compiles_and_does_not_restore_into_memory(self):
        import importlib.util
        from pathlib import Path
        path=Path(__file__).resolve().parents[1]/'scripts/backup_sealed_controller.py'
        spec=importlib.util.spec_from_file_location('sealed_backup_test',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        compile(module.PROGRAM,'backup-program','exec')
        self.assertNotIn('sqlite3.connect(":memory:")',module.PROGRAM)
        self.assertIn('os.O_EXCL',module.PROGRAM)
        self.assertIn('observe_existing_backup',module.PROGRAM)
        self.assertIn('os.fsync',module.PROGRAM)

    def test_scheduler_does_not_depend_on_enabled_original_product_route(self):
        self.save()
        broker=SimpleNamespace(db=lambda:self.con)
        with patch.object(effects,'handle') as handle:effects.tick(broker)
        handle.assert_called_once_with(broker,'source')

    def test_seed_hashes_require_exact_author_context_without_inserting_old_red(self):
        self.save();trial={'literal_maintenance':{'source_task':'source'}}
        b=SimpleNamespace(db=lambda:self.con)
        selected={'tests/test.py':'a'*64}
        with patch.object(effects,'author_context',return_value={'title':'verified'}),\
                patch.object(effects,'seed_source',return_value={'selection':{'test_sha256':selected}}):
            self.assertEqual(effects.seeded_hashes(b,'maintenance',{'id':'task'},trial),selected)
        self.assertNotIn('old_red',trial)
        with patch.object(effects,'author_context',return_value=None),patch.object(effects,'seed_source') as seed:
            with self.assertRaises(ValueError):effects.seeded_hashes(b,'maintenance',{'id':'foreign'},trial)
            seed.assert_not_called()
