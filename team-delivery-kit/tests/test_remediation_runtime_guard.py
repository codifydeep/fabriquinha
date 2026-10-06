import copy
import json
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from broker import remediation_runtime_guard as guard
from broker.technical_remediation_plan import digest


class RemediationRuntimeGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'db.sqlite'
        self.value = dict(source_task='source',original_depth=2,
            contract_sha256='c'*64,base=dict(base_sha='a'*40,manifest_sha256='b'*64,volume='old'),
            steps=[dict(id='R1',owner='author',edit_scope='new_tests_only',editable_files=['tests/test_new.py'])],
            previous_new_test_delivery=dict(task_id='historic',volume='frozen',manifest_sha256='d'*64,
                                           test_sha256={'tests/test_new.py':'e'*64}),
            baseline_edits_allowed=False,historical_snapshots_editable=False,release_homologated=False)
        proof=dict(operation='remediation_original_base_seed_v1',base_sha='a'*40,manifest_sha256='b'*64,
            contract_sha256='c'*64,previous_manifest_sha256='d'*64,seed_test_sha256={'tests/test_new.py':'e'*64},
            baseline_test_sha256={'tests/test_existing.py':'f'*64},baseline_unchanged=True,
            snapshot_permissions_unchanged=True,product_unchanged=True,red_executed=False,
            execution_authorized=False,release_homologated=False)
        self.state=dict(issue_id='r1',stage='r1_base_qualified',execution_authorized=False,
                        contract_sha256=digest(self.value),preparation=dict(proof=proof))
        self.route=dict(issue_id='r1',author='author',contract_sha256='c'*64,test_first=True,
                        test_first_files=['tests/test_new.py'])
        self.base={**self.value['base'],'issue_id':'r1','volume':'delivery-kit-port2-base-r1'}
        self.b=SimpleNamespace(db=self.db,PREFIX='delivery-kit-port2',OWNER='owner',
            issue_base=lambda issue:self.base,docker=lambda *args:dict(Labels={
                'delivery-kit.owner':'owner','delivery-kit.test-first-task':'historic'}))
        with self.db() as con:
            con.execute('CREATE TABLE remediation_executions(source_task TEXT,contract TEXT,state TEXT)')
            con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
            con.execute('CREATE TABLE test_first_red(issue_id TEXT)')
            con.execute('INSERT INTO remediation_executions VALUES (?,?,?)',('source',json.dumps(self.value),json.dumps(self.state)))
            con.execute('INSERT INTO delivery_routes VALUES (?,?)',('r1',json.dumps(self.route)))

    def db(self):
        return sqlite3.connect(self.path)

    def save(self,value=None,state=None,route=None):
        with self.db() as con:
            if value is not None:con.execute('UPDATE remediation_executions SET contract=?',(json.dumps(value),))
            if state is not None:con.execute('UPDATE remediation_executions SET state=?',(json.dumps(state),))
            if route is not None:con.execute('UPDATE delivery_routes SET config=?',(json.dumps(route),))

    def test_tests_only_cannot_unlock_product_even_with_red(self):
        self.assertEqual(guard.phase(self.b,'r1'),'tests_only')
        with self.db() as con:con.execute('INSERT INTO test_first_red VALUES (?)',('r1',))
        self.assertEqual(guard.phase(self.b,'r1'),'tests_only')

    def test_seed_is_exact_readonly_historical_delivery_not_mounted_in_worker(self):
        selected=guard.seed_source(self.b,'r1')
        self.assertEqual(selected['mount'],dict(Type='volume',Source='frozen',Target='/previous',ReadOnly=True))
        self.assertEqual(selected['selection']['test_sha256'],self.value['previous_new_test_delivery']['test_sha256'])

    def test_unqualified_or_changed_scope_fail_closed_without_legacy_fallback(self):
        for change in (dict(stage='r1_preparation_blocked'),dict(execution_authorized=True),dict(contract_sha256='0'*64)):
            self.save(state={**self.state,**change})
            with self.assertRaises(ValueError):guard.phase(self.b,'r1')
        self.save(state=self.state)
        for change in (dict(author='other'),dict(test_first=False),dict(test_first_files=['app.py'])):
            self.save(route={**self.route,**change})
            with self.assertRaises(ValueError):guard.seed_source(self.b,'r1')

    def test_tampered_proof_baseline_base_or_snapshot_ownership_rejected(self):
        for key in ('baseline_unchanged','snapshot_permissions_unchanged','product_unchanged'):
            state=copy.deepcopy(self.state);state['preparation']['proof'][key]=False
            self.save(state=state)
            with self.assertRaises(ValueError):guard.qualified(self.b,'r1')
        self.save(state=self.state)
        self.base={**self.base,'base_sha':'0'*40}
        with self.assertRaises(ValueError):guard.phase(self.b,'r1')
        self.base={**self.base,'base_sha':'a'*40}
        self.b.docker=lambda *args:dict(Labels={'delivery-kit.owner':'foreign'})
        with self.assertRaises(ValueError):guard.seed_source(self.b,'r1')

    def test_missing_route_or_duplicate_binding_is_not_authority(self):
        with self.db() as con:con.execute('DELETE FROM delivery_routes')
        with self.assertRaises(ValueError):guard.phase(self.b,'r1')
        with self.db() as con:
            con.execute('INSERT INTO remediation_executions VALUES (?,?,?)',('other',json.dumps(self.value),json.dumps(self.state)))
        with self.assertRaises(ValueError):guard.lookup(self.b,'r1')

    def test_historical_review_cannot_be_misclassified_as_first_submission(self):
        with self.assertRaisesRegex(ValueError,'historical independent review adapter'):
            guard.require_historical_review(self.b,'r1')
        self.assertIsNone(guard.require_historical_review(self.b,'unrelated'))
        self.assertIsNone(guard.phase(self.b,'unrelated'))

    def test_legacy_without_registry_is_unchanged(self):
        with self.db() as con:con.execute('DROP TABLE remediation_executions')
        self.assertIsNone(guard.phase(self.b,'unrelated'))


if __name__=='__main__':unittest.main()
