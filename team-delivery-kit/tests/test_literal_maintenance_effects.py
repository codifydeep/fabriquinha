import contextlib
import copy
import io
import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from broker import literal_maintenance_effects as effects
from broker import literal_maintenance_workflow as flow
from broker import harness_repair_task
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

    def test_scheduler_does_not_depend_on_enabled_original_product_route(self):
        self.save()
        broker=SimpleNamespace(db=lambda:self.con)
        with patch.object(effects,'handle') as handle:effects.tick(broker)
        handle.assert_called_once_with(broker,'source')
