"""One frozen acceptance inventory for preview and deployed multi-user QA."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.browser import acceptance_manifest
from fabriquinha.config import Project
from fabriquinha.effects import write_json
from fabriquinha.executor import Runner,seal_validation
from fabriquinha.quality import CONTROL_CONTRACT,preview_evidence,suite_report
from test_delivery_core import configuration
from fabriquinha.runtime import Runtime


SOURCE='''from fabriquinha_acceptance import AcceptanceTest
class Rooms(AcceptanceTest):
    def test_shared(self):
        self.assertTrue(True)
'''


def coverage():
    return dict(version=2,criteria={
        'SHARED':dict(cases=['acceptance_rooms.Rooms.test_shared'],gates=[]),
        'REGRESSION':dict(cases=[],gates=['regression'])})


class AcceptanceInventory(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        (self.root/'acceptance_rooms.py').write_text(SOURCE)
        (self.root/'acceptance.rooms.json').write_text(json.dumps(coverage()))

    def test_cumulative_regressions_exceed_a_single_brief_without_weakening_coverage(self):
        original=(self.root/'acceptance.rooms.json').read_bytes()
        value=dict(version=2,criteria={f'REGRESSION_{n}':dict(cases=[],gates=['regression']) for n in range(254)})
        (self.root/'acceptance.next.json').write_text(json.dumps(value))
        self.assertEqual(len(acceptance_manifest(self.root)['criteria']),256)
        self.assertEqual((self.root/'acceptance.rooms.json').read_bytes(),original)
        value['criteria']['OVERFLOW']=dict(cases=[],gates=['regression'])
        (self.root/'acceptance.next.json').write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'criteria count 257 outside 1..256'):acceptance_manifest(self.root)

    def test_coverage_reads_source_without_executing_product_code_on_host(self):
        (self.root/'acceptance_rooms.py').write_text('raise RuntimeError("must not execute")\n'+SOURCE)
        value=acceptance_manifest(self.root)
        self.assertEqual(value['cases'],['acceptance_rooms.Rooms.test_shared'])
        self.assertEqual(value['criteria']['REGRESSION'],dict(cases=[],gates=['regression']))

    def test_partial_inventory_invented_cases_and_duplicate_criteria_fail(self):
        for case in ('invented.Test.test_fake',None):
            value=coverage()
            if case:value['criteria']['SHARED']['cases'].append(case)
            else:value['criteria']['SHARED']=dict(cases=[],gates=['full_suite'])
            (self.root/'acceptance.rooms.json').write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'every real acceptance case'):acceptance_manifest(self.root)
        (self.root/'acceptance.rooms.json').write_text(json.dumps(coverage()))
        (self.root/'acceptance.copy.json').write_text(json.dumps(coverage()))
        with self.assertRaisesRegex(ValueError,'distinct criteria'):acceptance_manifest(self.root)

    def test_duplicate_json_keys_or_dynamic_test_inheritance_are_refused(self):
        path=self.root/'acceptance.rooms.json'
        path.write_text('{"version":2,"version":2,"criteria":{}}')
        with self.assertRaisesRegex(ValueError,'duplicate'):acceptance_manifest(self.root)
        path.write_text(json.dumps(coverage()))
        (self.root/'acceptance_rooms.py').write_text(SOURCE.replace('Rooms(AcceptanceTest)','Rooms(UnknownMixin, AcceptanceTest)'))
        with self.assertRaisesRegex(ValueError,'explicit AcceptanceTest'):acceptance_manifest(self.root)

    def test_old_qa_files_cannot_disappear_from_the_new_discovery(self):
        (self.root/'qa.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'silently omitted'):acceptance_manifest(self.root)

    def test_later_increment_extends_the_same_criterion_without_editing_frozen_files(self):
        original=(self.root/'acceptance.rooms.json').read_bytes()
        (self.root/'acceptance_join.py').write_text(SOURCE.replace('Rooms','Join').replace('test_shared','test_join_nickname'))
        (self.root/'acceptance.join.json').write_text(json.dumps(dict(version=2,criteria={
            'SHARED':dict(cases=['acceptance_join.Join.test_join_nickname'],gates=[])})))
        result=acceptance_manifest(self.root)
        self.assertEqual(set(result['criteria']['SHARED']['cases']),
                         {'acceptance_join.Join.test_join_nickname','acceptance_rooms.Rooms.test_shared'})
        self.assertEqual((self.root/'acceptance.rooms.json').read_bytes(),original)
        self.assertEqual(len(result['cases']),2)


class PinnedAcceptanceRunner(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.store=Store(self.root/'private')
        self.project=Project.parse({**configuration(),'browser_tdd':True,'browser_image':'sha256:'+'b'*64,
            'coordination_roles':{'product':'backend','lead':'lead'},'delivery_roles':{'tests':'backend','integration':'lead'}})
        self.bundle=seal_validation(self.store)
        write_json(self.root/'installation.json',dict(project=self.project.fingerprint(),
            validation_bundle=self.bundle,control_contract=CONTROL_CONTRACT,browser_contract=2))
        work=self.root/'work';(work/'tests').mkdir(parents=True)
        (work/'tests/acceptance_rooms.py').write_text(SOURCE)
        (work/'tests/acceptance.rooms.json').write_text(json.dumps(coverage()))
        self.snapshot=self.store.capture(work)
        self.runner=Runner.__new__(Runner);self.runner.project=self.project;self.runner.store=self.store
        self.run=SimpleNamespace(binding=lambda:dict(task='fixture',number=1))

    def test_fixed_suite_receives_contract_in_all_phases_and_pins_it_in_receipt_identity(self):
        for phase in ('baseline','red','green','control','delivery','integrated','diagnostic'):
            with self.subTest(phase=phase),patch.object(self.runner,'_execute',return_value='job') as execute:
                self.runner.run(self.run,self.snapshot,phase)
            _,identity,command=execute.call_args.args
            self.assertEqual(identity.get('browser_contract'),2)
            self.assertIn('FABRIQUINHA_BROWSER_CONTRACT=2',command)
            self.assertIn('FABRIQUINHA_SOURCE_SHA='+self.snapshot,command)

    def test_old_qa_report_cannot_satisfy_new_acceptance_inventory(self):
        from fabriquinha.executor import preview_drivers
        identity=dict(validation_bundle=self.bundle,qa_preview=preview_drivers(self.project,'green',self.store),browser_contract=2)
        value=dict(identity=identity,report=dict(qa_preview=dict(status='passed',checks=['SHARED'])))
        with self.assertRaisesRegex(ValueError,'inventory'):preview_evidence(self.project,self.store,value,self.snapshot,'green')
        value['report']['qa_preview']['cases']=['acceptance_rooms.Rooms.test_shared']
        value['report']['cases']=['acceptance_rooms.Rooms.test_shared']
        preview_evidence(self.project,self.store,value,self.snapshot,'green')
        del identity['browser_contract']
        with self.assertRaisesRegex(ValueError,'contract'):preview_evidence(self.project,self.store,value,self.snapshot,'green')

    def test_unit_red_cannot_hide_acceptance_startup_failure_or_missing_execution(self):
        value=dict(identity=dict(validation_bundle=self.bundle,browser_contract=2,snapshot=self.snapshot,phase='red'),exit_code=1,
            report=dict(version=1,tests_run=1,cases=['test_unit.Test.test_feature'],
                failures=[dict(case='test_unit.Test.test_feature')],errors=[],skips=[],expected_failures=[],unexpected_successes=[],
                qa_preview=dict(version=1,status='failed',source_sha=self.snapshot,checks=[],cases=['acceptance_rooms.Rooms.test_shared'],
                    errors=['identity mismatch'],phase='health',failure_kind='infrastructure')))
        with self.assertRaisesRegex(ValueError,'acceptance'):suite_report(value)
        with self.assertRaisesRegex(ValueError,'inventory'):preview_evidence(self.project,self.store,value,self.snapshot,'red')
        value['report']['cases'].append('acceptance_rooms.Rooms.test_shared');value['report']['tests_run']=2
        value['report']['qa_preview'].update(failure_kind='behavior',phase='assertion',errors=['expected behavior missing'])
        value['report']['failures']=[dict(case='acceptance_rooms.Rooms.test_shared')]
        preview_evidence(self.project,self.store,value,self.snapshot,'red')
        self.assertEqual(suite_report(value)['tests_run'],2)

    def test_install_upgrade_requires_stopped_preimplementation_board_and_preserves_old_binding(self):
        from unittest.mock import Mock
        path=self.root/'installation.json';old=json.loads(path.read_text());del old['browser_contract'];write_json(path,old)
        runtime=Runtime.__new__(Runtime);runtime.root=self.root;runtime.store=self.store;runtime.project=self.project
        runtime.control=SimpleNamespace(read=lambda:dict(paused=True,error=None,episode='e'*32))
        runtime.pause_status=lambda conn:dict(drained=True)
        connection=Mock();connection.execute.return_value.fetchall.return_value=[dict(body=json.dumps(dict(kind='brief')))]
        api=Mock();api.connect_closing.return_value.__enter__=Mock(return_value=connection)
        api.connect_closing.return_value.__exit__=Mock(return_value=False)
        with patch('fabriquinha.runtime.native',return_value=(None,api,None)):
            with self.assertRaisesRegex(ValueError,'bundle'):runtime.configure_acceptance('f'*64)
            connection.execute.return_value.fetchall.return_value=[dict(body=json.dumps(dict(kind='tests')))]
            with self.assertRaisesRegex(ValueError,'before planning'):runtime.configure_acceptance(self.bundle)
            self.assertEqual(json.loads(path.read_text()),old)
            connection.execute.return_value.fetchall.return_value=[dict(body=json.dumps(dict(kind='brief')))]
            result=runtime.configure_acceptance(self.bundle)
        self.assertEqual(result['browser_contract'],2)
        self.assertFalse(result['dispatch_started'])
        proof=self.store.receipt(result['receipt'],kind='acceptance_upgrade')['payload']
        self.assertEqual(proof['before'],old)
        self.assertEqual(json.loads(path.read_text()),proof['after'])
        with patch('fabriquinha.runtime.native',side_effect=AssertionError('do not repeat migration')):
            self.assertTrue(runtime.configure_acceptance(self.bundle)['already_installed'])


    def test_additive_repair_after_planning_refuses_any_existing_quality_receipt_or_job(self):
        from unittest.mock import Mock
        runtime=Runtime.__new__(Runtime);runtime.root=self.root;runtime.store=self.store;runtime.project=self.project
        runtime.control=SimpleNamespace(read=lambda:dict(paused=True,error=None,episode='e'*32))
        runtime.pause_status=lambda conn:dict(drained=True)
        connection=Mock();connection.execute.return_value.fetchall.return_value=[dict(body=json.dumps(dict(kind='plan'))),dict(body=json.dumps(dict(kind='tests')))]
        api=Mock();api.connect_closing.return_value.__enter__=Mock(return_value=connection)
        api.connect_closing.return_value.__exit__=Mock(return_value=False)
        before=(self.root/'installation.json').read_bytes()
        receipt=self.store.record('test_plan',{'fixture':True},{'frozen':True})
        with patch('fabriquinha.runtime.native',return_value=(None,api,None)):
            with self.assertRaisesRegex(ValueError,'quality'):runtime.configure_acceptance(self.bundle)
            self.assertEqual((self.root/'installation.json').read_bytes(),before)
            # Remove only this disposable test fixture to exercise the separate
            # pending-job boundary; production has no receipt deletion API.
            (self.store.root/'receipts'/(receipt+'.json')).unlink()
            jobs=self.store.root/'jobs';jobs.mkdir(exist_ok=True);(jobs/'pending').write_text('unobserved')
            with self.assertRaisesRegex(ValueError,'job'):runtime.configure_acceptance(self.bundle)
            self.assertEqual((self.root/'installation.json').read_bytes(),before)
            (jobs/'pending').unlink()
            result=runtime.configure_acceptance(self.bundle)
            self.assertFalse(result['dispatch_started'])
            self.assertTrue(runtime.configure_acceptance(self.bundle)['already_installed'])


if __name__=='__main__':unittest.main()
