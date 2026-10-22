"""Real local Git/export bridge, synthetic capture authority; no native approval."""
from contextlib import contextmanager
import copy
import json
import sqlite3
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import quality_delivery_candidate as bridge
import test_quality_git_candidate as git_fixture
import test_quality_delivery_export as export_fixture


class DeliveryCandidateTests(unittest.TestCase):
    def setUp(self):
        f=git_fixture.GitCandidateTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f
        e=export_fixture.DeliveryExportTests();e.setUp();self.addCleanup(e.doCleanups)
        self.packet=dict(descriptor=copy.deepcopy(e.descriptor),plan=f.plan,frozen_tests=f.frozen,
            repository='codifydeep/descartavel2')
        d=self.packet['descriptor'];d.update(request_id=f.request,task_id=f.task,run_id=f.plan['run_id'],
            issue_id=f.plan['issue_id'],manifest_sha256=f.f.sha,plan_sha256=bridge.binding.quality.digest(f.plan),
            file_inventory=json.loads((f.f.snapshot/'manifest.json').read_bytes())['files'])
        d['volume_identity']['Name']=d['namespace']+'-quality-delivery-'+f.task
        d['volume_identity']['Labels'].update({'delivery-kit.source-task':f.task,'delivery-kit.quality-run':f.plan['run_id']})
        self.fx=export_fixture.Effects(f.f.snapshot,d)
        self.context=dict(namespace=d['namespace'],admission=dict(request_id=f.request))
        self.state=dict(stage='awaiting_git_binding',execution_authorized=False,green_approved=False,delivery_approval=False)
        d.update(capture_context_sha256=bridge.binding.quality.digest(self.context),
            capture_state_sha256=bridge.binding.quality.digest(self.state))
        database=f.f.f.root/'bridge.sqlite'
        @contextmanager
        def db():
            con=sqlite3.connect(database);con.row_factory=sqlite3.Row
            try:
                with con:yield con
            finally:con.close()
        self.b=SimpleNamespace(PREFIX=d['namespace'],db=db,LOCK=threading.RLock(),
            QUALITY_V2_ENABLED=True,QUALITY_IMPLEMENTATION_ENABLED=True)
        with db() as con:
            bridge.binding.maintenance.initialize(con)
            bridge.binding.delivery.initialize(con)
            con.execute('INSERT INTO quality_delivery_captures VALUES(?,?,?,?,?)',(f.request,
                json.dumps(self.context),json.dumps(self.state),d['capture_context_sha256'],d['capture_state_sha256']))
        self.f.f.git('remote','add','origin','https://github.com/codifydeep/descartavel2.git')
        p=patch.object(bridge.binding.delivery,'candidate_packet',side_effect=lambda *_:copy.deepcopy(self.packet))
        p.start();self.addCleanup(p.stop)

    def call(self):return bridge.advance(self.b,self.f.request,self.f.f.repo,self.f.private,effects=self.fx)

    def test_export_real_git_and_durable_binding_keep_main_and_tests_intact(self):
        before=(self.f.f.git('rev-parse','HEAD'),self.f.f.git('write-tree'))
        result=self.call()
        self.assertEqual(result['stage'],'awaiting_green');self.assertFalse(result['green_approved'])
        self.assertFalse(result['delivery_approval'])
        self.assertEqual(before,(self.f.f.git('rev-parse','HEAD'),self.f.f.git('write-tree')))
        self.assertEqual(result['candidate']['git_proof']['frozen_tests'],self.f.frozen)
        with patch.object(bridge.exporter,'export',side_effect=AssertionError('no second export')),\
                patch.object(bridge.candidate,'materialize',side_effect=AssertionError('no second candidate')):
            self.assertEqual(self.call(),result)

    def test_wrong_repository_is_rejected_before_export_or_git_objects(self):
        self.f.f.git('remote','set-url','origin','https://github.com/codifydeep/truco-online.git')
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.fx.creates,0)
        self.assertEqual(self.f.f.git('for-each-ref','--format=%(refname)','refs/delivery-kit/quality/'),'')

    def test_unknown_export_ack_resumes_same_helper_then_same_candidate(self):
        self.fx.unknown_copy=True
        with self.assertRaises(bridge.exporter.Pending):self.call()
        self.assertEqual(self.call()['stage'],'awaiting_green')
        self.assertEqual((self.fx.creates,self.fx.copies,self.fx.removes),(1,1,1))

    def test_lost_database_ack_reads_binding_without_repeating_local_effects(self):
        original=bridge.binding.record
        def uncertain(*args):
            original(*args);raise TimeoutError('DB commit acknowledgement lost')
        with patch.object(bridge.binding,'record',side_effect=uncertain):
            with self.assertRaises(TimeoutError):self.call()
        with patch.object(bridge.candidate,'materialize',side_effect=AssertionError('must not replay')):
            self.assertEqual(self.call()['stage'],'awaiting_green')

    def test_capture_changed_between_candidate_and_record_never_registers_stale_proof(self):
        original=bridge.candidate.materialize
        def mutate(*args):
            result=original(*args);self.packet['descriptor']['capture_state_sha256']='f'*64;return result
        with patch.object(bridge.candidate,'materialize',side_effect=mutate):
            with self.assertRaises(ValueError):self.call()
        self.assertIsNone(bridge.binding.load(self.b,self.f.request))
        self.assertNotEqual(self.f.f.git('for-each-ref','--format=%(refname)','refs/delivery-kit/quality/'),'')

    def test_maintenance_blocks_before_export_and_fake_approval_cannot_be_recorded(self):
        with self.b.db() as con:
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',('pause','sealed',json.dumps(dict(stage='sealed'))))
        with self.assertRaises(bridge.binding.validation_job.Pending):self.call()
        self.assertEqual(self.fx.creates,0)
        with self.b.db() as con:con.execute('DELETE FROM controller_maintenance')
        receipt=self.call();identity=bridge.binding.load(self.b,self.f.request)[0]
        receipt['green_approved']=True
        with self.assertRaises(ValueError):bridge.binding.validate(identity,receipt)


if __name__=='__main__':unittest.main()
