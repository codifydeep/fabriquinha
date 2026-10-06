import copy
import hashlib
import json
import shutil
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import test_incremental_checkpoints as fixtures
from test_initial_base_validation import InitialInspectionTests
from broker import incremental_read_recovery as recovery
from broker.unwritten_unit_inspect import inspect_unwritten


class UnwrittenInspectionTests(unittest.TestCase):
    def setUp(self):
        f=InitialInspectionTests();f.setUp();self.addCleanup(f.doCleanups)
        self.base=f.root;self.sha=f.sha;self.work=Path(f.tmp.name+'-work')
        self.work.mkdir();self.addCleanup(shutil.rmtree,self.work)
        for name in ('AGENTS.md','app.py','tests/test_old.py'):
            p=self.work/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(self.base/name,p)
        (self.work/'tests/test_new.py').write_bytes(b'')
        (self.work/'.delivery-kit-base.json').write_text(json.dumps(dict(base_sha='a'*40,manifest_sha256=self.sha)))

    def test_full_old_base_and_empty_new_test_are_qualified_without_tdd_approval(self):
        proof=inspect_unwritten(self.base,self.work,self.sha,['tests/test_new.py'])
        self.assertEqual(proof['base_files_verified'],3);self.assertFalse(proof['delivery_approval'])

    def test_changed_existing_file_after_empty_new_test_is_not_skipped(self):
        (self.work/'tests/test_old.py').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'base changed'):inspect_unwritten(self.base,self.work,self.sha,['tests/test_new.py'])

    def test_new_artifact_symlink_or_foreign_entry_never_qualifies(self):
        (self.work/'tests/test_new.py').write_bytes(b'not empty')
        with self.assertRaises(ValueError):inspect_unwritten(self.base,self.work,self.sha,['tests/test_new.py'])
        (self.work/'tests/test_new.py').unlink();(self.work/'tests/test_new.py').symlink_to(self.work/'app.py')
        with self.assertRaises(ValueError):inspect_unwritten(self.base,self.work,self.sha,['tests/test_new.py'])

    def test_seeded_revision_requires_exact_historic_bytes_and_all_base_bytes(self):
        seed=self.work.parent/(self.work.name+'-seed')
        seed.mkdir();self.addCleanup(shutil.rmtree,seed)
        (seed/'tests').mkdir();data=b'original new assertion'
        (seed/'tests/test_new.py').write_bytes(data)
        (self.work/'tests/test_new.py').write_bytes(data)
        hashes={'tests/test_new.py':hashlib.sha256(data).hexdigest()}
        proof=inspect_unwritten(self.base,self.work,self.sha,list(hashes),seed,hashes)
        self.assertEqual(proof['provenance'],'controller_offline_unchanged_seeded_workspace_v1')
        self.assertEqual(proof['new_test_sha256'],hashes)
        self.assertFalse(proof['delivery_approval'])
        with self.assertRaises(ValueError):inspect_unwritten(self.base,self.work,self.sha,list(hashes),seed,{})
        (self.work/'tests/test_new.py').write_bytes(b'changed')
        with self.assertRaises(ValueError):inspect_unwritten(self.base,self.work,self.sha,list(hashes),seed,hashes)
        (self.work/'tests/test_new.py').write_bytes(data)
        (self.work/'app.py').write_bytes(b'changed baseline')
        with self.assertRaises(ValueError):inspect_unwritten(self.base,self.work,self.sha,list(hashes),seed,hashes)

    def test_seed_snapshot_hash_mismatch_is_not_accepted(self):
        hashes={'tests/test_new.py':'0'*64}
        with self.assertRaises(ValueError):inspect_unwritten(self.base,self.work,self.sha,list(hashes),self.work,hashes)


class ReadRecoveryTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.IncrementalCheckpointTests();f.setUp();self.addCleanup(f.doCleanups)
        self.con=f.con;self.state=f.state();self.state['execution_authorized']=True
        self.state['units']['U1']['binding']=dict(materialization=dict(base_manifest_sha256='b'*64,
            baseline_test_sha256={'tests/old.py':'c'*64},new_test='tests/new.py'))
        self.config={'source_task':'source'};self.route=dict(issue_id='child',enabled=True,author='author',cto='cto')
        self.task=dict(id='failed',issue_id='child',agent_id='author',status='failed',error='hermes provider error: API call failed after 1 retries')
        self.proof=dict(provenance='controller_offline_unwritten_workspace_v1',delivery_approval=False,
            base_manifest_sha256='b'*64,baseline_test_sha256={'tests/old.py':'c'*64},
            new_test_sha256={'tests/new.py':hashlib.sha256(b'').hexdigest()},base_files_verified=3)
        self.con.execute('CREATE TABLE incremental_runtime_incidents(source_task TEXT PRIMARY KEY,receipt TEXT)')
        self.incident=dict(category='forced_read_argument_rejected',task_id='failed',selected_tool='read_file',
            proxy_category='invalid_forced_argument',proxy_status=502,proxy_call=1)
        self.con.execute('INSERT INTO incremental_runtime_incidents VALUES(?,?)',('source',json.dumps(self.incident)))
        self.con.execute('CREATE TABLE test_first_red(issue_id TEXT)')

    def authorize(self,**kw):
        return recovery.authorize(self.con,self.config,self.state,self.route,self.task,kw.get('proof',self.proof),kw.get('tool_count',0))

    def test_single_authorization_preserves_incident_and_never_approves_delivery(self):
        receipt=self.authorize();self.assertEqual(self.authorize(),receipt)
        self.assertEqual(receipt['previous_incident'],self.incident);self.assertEqual(receipt['attempt_limit'],1)
        self.assertFalse(receipt['delivery_approval']);self.assertTrue(recovery.authorized(self.con,'child'))
        self.assertFalse(recovery.authorized(self.con,'other'))
        self.assertEqual(self.con.execute('SELECT count(*) FROM incremental_runtime_incidents').fetchone()[0],0)

    def test_tool_execution_wrong_failure_changed_base_or_red_prevent_recovery(self):
        with self.assertRaises(ValueError):self.authorize(tool_count=1)
        changed={**self.proof,'base_manifest_sha256':'0'*64}
        with self.assertRaises(ValueError):self.authorize(proof=changed)
        self.task['error']='different failure'
        with self.assertRaises(ValueError):self.authorize()
        self.task['error']='hermes provider error: API call failed after 1 retries'
        self.con.execute('INSERT INTO test_first_red VALUES(?)',('child',))
        with self.assertRaises(ValueError):self.authorize()
        self.assertEqual(self.con.execute('SELECT count(*) FROM incremental_runtime_incidents').fetchone()[0],1)

    def test_dispatch_reuses_exact_marker_after_ambiguous_exception_and_restart(self):
        self.authorize();effects=SimpleNamespace(remaining_calls=Mock(return_value=70),implementation_available=Mock(return_value=True),
            ensure_wakeup=Mock(side_effect=[TimeoutError(),{'id':'wake'}]))
        with self.assertRaises(TimeoutError):recovery.reconcile(self.con,'source',self.state['units']['U1'],effects)
        result=recovery.reconcile(self.con,'source',self.state['units']['U1'],effects)
        self.assertEqual(result['wakeup_id'],'wake')
        self.assertEqual(effects.ensure_wakeup.call_args_list[0].args[3],effects.ensure_wakeup.call_args_list[1].args[3])
        recovery.reconcile(self.con,'source',self.state['units']['U1'],effects)
        self.assertEqual(effects.ensure_wakeup.call_count,2)

    def test_budget_wait_never_dispatches_or_approves(self):
        self.authorize();effects=SimpleNamespace(remaining_calls=Mock(return_value=0),implementation_available=Mock(return_value=True),ensure_wakeup=Mock())
        self.assertEqual(recovery.reconcile(self.con,'source',self.state['units']['U1'],effects)['stage'],'pending')
        effects.ensure_wakeup.assert_not_called()

    def seeded_fixture(self):
        unit=self.state['units']['U1'];unit['revision']=2
        unit['test_repair']=dict(parent_issue='old-child',decision_task='cto-task',reason='Repair harness')
        self.route['enabled']=False
        self.con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
        self.con.execute('INSERT INTO delivery_routes VALUES(?,?)',('child',json.dumps(self.route)))
        self.con.execute('CREATE TABLE test_revision_trials(issue_id TEXT,config TEXT)')
        trial=dict(parent_issue='old-child',cto_decision='cto-task',seed_previous_tests=True,
            old_red={'red':{'test_sha256':{'tests/new.py':'f'*64}}})
        self.con.execute('INSERT INTO test_revision_trials VALUES(?,?)',('child',json.dumps(trial)))
        self.incident['proxy_category']='incomplete_forced_tool_response'
        self.con.execute('UPDATE incremental_runtime_incidents SET receipt=?',(json.dumps(self.incident),))
        self.proof.update(provenance='controller_offline_unchanged_seeded_workspace_v1',new_test_sha256={'tests/new.py':'f'*64})

    def test_seeded_revision_recovery_is_single_attempt_and_reenables_exact_route(self):
        self.seeded_fixture()
        result=self.authorize()
        self.assertEqual(result['attempt_limit'],1)
        self.assertEqual(result['inspection']['new_test_sha256'],{'tests/new.py':'f'*64})
        self.assertTrue(json.loads(self.con.execute('SELECT config FROM delivery_routes').fetchone()[0])['enabled'])
        self.assertEqual(result,self.authorize())

    def test_empty_or_modified_seed_does_not_qualify_revision_recovery(self):
        self.seeded_fixture()
        for sha in (hashlib.sha256(b'').hexdigest(),'0'*64):
            with self.assertRaises(ValueError):self.authorize(proof={**self.proof,'new_test_sha256':{'tests/new.py':sha}})
        self.assertFalse(json.loads(self.con.execute('SELECT config FROM delivery_routes').fetchone()[0])['enabled'])
        self.assertEqual(self.con.execute('SELECT count(*) FROM incremental_runtime_incidents').fetchone()[0],1)

    def write_failure_fixture(self):
        self.seeded_fixture();old=self.authorize()
        old.update(stage='blocked',wakeup_id='read-wake',failed_recovery_task='failed-write',
            recovery_failure=dict(selected_tool='write_file',proxy_status=502,proxy_category='invalid_forced_argument',proxy_call=2))
        self.con.execute('UPDATE incremental_read_recoveries SET receipt=?',(json.dumps(old),))
        self.route['enabled']=False
        self.task.update(id='failed-write',wakeup_id='read-wake')
        incident=dict(category='artifact_write_argument_rejected',task_id='failed-write',proxy_call=2)
        self.con.execute('INSERT INTO incremental_runtime_incidents VALUES(?,?)',('source',json.dumps(incident)))
        return old

    def test_distinct_write_protocol_recovery_preserves_failed_read_attempt_and_is_bounded(self):
        old=self.write_failure_fixture()
        r=recovery.authorize_write_phase(self.con,self.config,self.state,self.route,self.task,self.proof)
        self.assertEqual(r['write_phase_recovery']['previous_read_recovery'],old)
        self.assertEqual(r['write_phase_recovery']['attempt_limit'],1)
        self.assertEqual(r['prior_failed_tasks'],['failed'])
        self.assertEqual(r['failed_task'],'failed-write')
        self.assertNotIn('wakeup_id',r)
        self.assertEqual(r,recovery.authorize_write_phase(self.con,self.config,self.state,self.route,self.task,self.proof))
        self.assertFalse(r['delivery_approval'])

    def test_write_protocol_recovery_rejects_changed_workspace_or_wrong_execution(self):
        self.write_failure_fixture()
        with self.assertRaises(ValueError):
            recovery.authorize_write_phase(self.con,self.config,self.state,self.route,self.task,{**self.proof,'base_files_verified':0})
        self.task['wakeup_id']='wrong'
        with self.assertRaises(ValueError):
            recovery.authorize_write_phase(self.con,self.config,self.state,self.route,self.task,self.proof)
