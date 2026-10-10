import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import test_generic_calibration_registration as samples
from generic_harness_calibration import digest
from broker import generic_calibration_proposal as proposal


class ProposalTests(unittest.TestCase):
    def setUp(self):
        fixture=samples.RegistrationInputTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.value=fixture.value;self.route=fixture.route
        self.prepared=dict(manifest_sha256=fixture.policy['candidate_manifest_sha256'],
            test_sha256=fixture.policy['test_sha256'])
        self.body=dict(action='propose_calibration_bundle',engine='unittest_path_fixture_v1',
            modules=fixture.policy['modules'],negatives=fixture.policy['negatives'],
            previous_methods=fixture.policy['previous_methods'],
            controls={'positive.txt':'correct','negative.txt':'broken'},
            execution_authorized=False,delivery_approval=False)

    def test_controller_binds_hashes_instead_of_accepting_model_authorship_claims(self):
        result=proposal.bundle(self.body,self.value,self.route,self.prepared)
        self.assertEqual(result['policy']['execution_sha256'],digest(self.value))
        self.assertEqual(result['policy']['test_sha256'],self.prepared['test_sha256'])
        self.assertEqual(result['policy']['criteria'],['A01'])
        self.assertFalse(result['execution_authorized'])
        self.assertFalse(result['delivery_approval'])
        self.assertEqual(hashlib.sha256(result['controls_manifest'].encode()).hexdigest(),
            result['policy']['controls_manifest_sha256'])

    def test_extra_paths_commands_authority_and_unbounded_controls_are_rejected(self):
        for mutate in (lambda b:b.update(command=['sh','-c','true']),
                       lambda b:b.update(delivery_approval=True),
                       lambda b:b.update(execution_authorized=0),
                       lambda b:b['controls'].update({'../escape':'x'}),
                       lambda b:b['controls'].update({'extra.txt':'x'}),
                       lambda b:b['controls'].update({'positive.txt':'x'*65537}),
                       lambda b:b['controls'].update({'positive.txt':True})):
            body=copy.deepcopy(self.body);mutate(body)
            with self.assertRaises(ValueError):proposal.bundle(body,self.value,self.route,self.prepared)

    def test_scope_and_criteria_cannot_be_replaced_by_proposal(self):
        body=copy.deepcopy(self.body);body['negatives'][0]['criteria']=['A02']
        with self.assertRaises(ValueError):proposal.bundle(body,self.value,self.route,self.prepared)
        body=copy.deepcopy(self.body);body['modules'][0]['path']='tests/replacement.py'
        with self.assertRaises(ValueError):proposal.bundle(body,self.value,self.route,self.prepared)

    def test_proposal_requires_exact_completed_cto_wakeup_and_full_source_reads(self):
        task=dict(id='cto-task',agent_id='cto',issue_id='issue',wakeup_id='wake',status='completed',
            result=dict(output=json.dumps(self.body)))
        paths=proposal.source_paths(self.body)
        reads={p:dict(lines=3,total_lines=3) for p in paths}
        result=proposal.from_task(task,'wake',self.value,self.route,self.prepared,reads)
        self.assertEqual(result['producer']['task_id'],'cto-task')
        for key,val in (('agent_id','author'),('wakeup_id','other'),('status','running'),('issue_id','other')):
            bad=copy.deepcopy(task);bad[key]=val
            with self.assertRaises(ValueError):proposal.from_task(bad,'wake',self.value,self.route,self.prepared,reads)
        partial=copy.deepcopy(reads);partial[paths[0]]['lines']=1
        with self.assertRaises(ValueError):proposal.from_task(task,'wake',self.value,self.route,self.prepared,partial)

    def test_proposal_storage_is_immutable_and_has_no_approval_or_docker_effect(self):
        import sqlite3
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        record=proposal.bundle(self.body,self.value,self.route,self.prepared)
        record['producer']={'task_id':'cto-task'}
        proposal.store(con,'issue','author-task',record)
        proposal.store(con,'issue','author-task',record)
        changed=copy.deepcopy(record);changed['producer']['task_id']='other'
        with self.assertRaises(ValueError):proposal.store(con,'issue','author-task',changed)
        self.assertEqual(con.execute('SELECT count(*) FROM generic_calibration_proposals').fetchone()[0],1)


class MaterializationTests(unittest.TestCase):
    setUp=ProposalTests.setUp
    def test_materializer_does_not_accept_extra_operations(self):
        from generic_calibration_bundle_writer import expected_files
        record=proposal.bundle(self.body,self.value,self.route,self.prepared)
        record['command']=['sh','-c','true']
        with self.assertRaises(ValueError):expected_files(record,digest(record))

    def test_fixed_materializer_preserves_content_and_never_overwrites_existing_target(self):
        from generic_calibration_bundle_writer import write
        with tempfile.TemporaryDirectory() as directory:
            record=proposal.bundle(self.body,self.value,self.route,self.prepared)
            root=Path(directory);controls=root/'controls';policy=root/'policy'
            controls.mkdir();policy.mkdir()
            receipt=write(controls,policy,record,digest(record))
            self.assertFalse(receipt['delivery_approval'])
            self.assertFalse(receipt['tests_executed'])
            self.assertEqual((controls/'positive.txt').read_text(),'correct')
            before=(controls/'manifest.json').read_bytes()
            self.assertEqual(write(controls,policy,record,digest(record)),receipt)
            self.assertEqual((controls/'manifest.json').read_bytes(),before)
            (controls/'positive.txt').chmod(0o600)
            (controls/'positive.txt').write_text('altered')
            with self.assertRaises(ValueError):write(controls,policy,record,digest(record))
            self.assertEqual((controls/'positive.txt').read_text(),'altered')

    def test_foreign_files_symlinks_and_changed_bundle_digest_are_not_repaired(self):
        from generic_calibration_bundle_writer import write
        for kind in ('foreign','symlink','digest'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as directory:
                record=proposal.bundle(self.body,self.value,self.route,self.prepared)
                controls=Path(directory)/'controls';policy=Path(directory)/'policy'
                controls.mkdir();policy.mkdir()
                if kind=='foreign':(controls/'foreign').write_text('preserve')
                if kind=='symlink':(controls/'positive.txt').symlink_to('/tmp/never-follow')
                with self.assertRaises(ValueError):write(controls,policy,record,
                    '0'*64 if kind=='digest' else digest(record))
