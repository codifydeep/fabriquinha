import copy
import hashlib
import json
import unittest
from unittest.mock import patch
from broker import handoffs, native, service_mode_schema_evidence as evidence
from tests import test_failed_execution_evidence as fixtures


class ServiceModeSchemaEvidenceTests(unittest.TestCase):
    db = fixtures.FailedExecutionEvidenceTests.db
    run_register = fixtures.FailedExecutionEvidenceTests.run_register

    def setUp(self):
        fixtures.FailedExecutionEvidenceTests.setUp(self)
        self.runs[0]['issue_id'] = 'issue'
        self.runs[-1].update(issue_id='issue', wakeup_id='wake')
        self.image = 'sha256:' + 'c' * 64
        self.broker.docker = lambda method, path: (
            dict(Image=self.image) if '/containers/' in path else
            {'Labels': {'delivery-kit.owner': 'owner', 'delivery-kit.source-task': self.source,
                        'delivery-kit.diagnostic-only': 'true'}})
        with self.db() as con:
            route = dict(enabled=False, author='author', cto='cto', reviewer='reviewer',
                         test_first_files=[evidence.probe.TEST])
            con.execute('UPDATE delivery_routes SET config=?', (json.dumps(route),))
            row = handoffs.load(con, self.source)
            d = json.loads(row['data'])
            d['validation_failure']['diagnostic_read_files'] = list(evidence.probe.READ_FILES)
            d['failed_execution_diagnostic']['failure'] = copy.deepcopy(d['validation_failure'])
            d.update(source_task=self.source, wakeup_id='wake', test_revision_proposal={'old': True},
                     technical_replan_certificate={'old': True})
            con.execute('UPDATE failed_execution_diagnoses SET receipt=?',
                        (json.dumps(d['failed_execution_diagnostic']),))
            handoffs.save(con, self.source, 'issue', 'test_revision_required', 'reviewer', d, 300)
            con.execute('UPDATE test_first_red SET receipt=?', (json.dumps({'red': {
                'manifest_sha256': 'f' * 64, 'test_sha256': {evidence.probe.TEST: 'b' * 64}}}),))
        fact = dict(value_type='dict', has_calls=True, has_issued=False,
                    text_type='str', is_checking=True, is_demo=False, calls=4)
        self.proof = dict(operation='service_mode_harness_schema_v1',
            input_sha256={p: 'b' * 64 for p in evidence.probe.READ_FILES}, report_sha256='d' * 64,
            snapshot_manifest_sha256='e' * 64, inputs_unchanged=True, delivery_approval=False,
            valid_red_green_receipt=False, facts={'after_ok': dict(fact),
                'pending_observed': dict(fact), 'after_deferred': dict(value_type='str',
                    has_calls=False, has_issued=False, text_type=None, is_checking=False, is_demo=True)})

    def enrich(self):
        with patch.dict('os.environ', {'HOSTNAME': 'controller'}), \
             patch.object(native, 'issue_task_runs', return_value=self.runs), \
             patch.object(evidence, 'capture', return_value=self.proof) as capture:
            return evidence.register(self.broker, self.evidence_payload), capture

    def test_durable_experiment_preserves_history_not_approval_or_new_depth(self):
        receipt, capture = self.enrich()
        capture.assert_called_once()
        self.assertEqual(receipt['prior_decision_task'], self.decision)
        self.assertEqual(receipt['status'], 'evidence_only_not_approved')
        self.assertFalse(receipt['proof']['delivery_approval'])
        second, capture = self.enrich()
        self.assertEqual(receipt, second)
        capture.assert_not_called()
        with self.db() as con:
            row = handoffs.load(con, self.source)
            self.assertEqual(row['stage'], 'diagnose_cto')
            data = json.loads(row['data'])
            self.assertNotIn('test_revision_proposal', data)
            self.assertNotIn('technical_replan_certificate', data)
            self.assertIn('failed_execution_diagnostic', data)
            self.assertNotIn('green_validation', data)
            route = json.loads(con.execute('SELECT config FROM delivery_routes').fetchone()[0])
            note = handoffs.harness_diagnosis_instruction(data, route)
            self.assertLessEqual(len(note) + 82, 4000)
            self.assertIn('REVISION DEPTH EXHAUSTED', note)
            self.assertFalse(route['enabled'])

    def test_running_or_closing_worker_rejected(self):
        with self.db() as con:
            con.execute("INSERT INTO leases VALUES ('closing')")
        with self.assertRaisesRegex(ValueError, 'paused idle'):
            self.enrich()

    def test_enabled_route_rejected(self):
        with self.db() as con:
            route = json.loads(con.execute('SELECT config FROM delivery_routes').fetchone()[0])
            route['enabled'] = True
            con.execute('UPDATE delivery_routes SET config=?', (json.dumps(route),))
        with self.assertRaisesRegex(ValueError, 'paused idle'):
            self.enrich()

    def test_stale_cto_wakeup_rejected(self):
        self.runs[-1]['wakeup_id'] = 'other'
        with self.assertRaisesRegex(ValueError, 'authentic'):
            self.enrich()

    def test_saved_output_tampering_rejected(self):
        with self.db() as con:
            con.execute("UPDATE frozen_suite_failures SET output='changed'")
        with self.assertRaisesRegex(ValueError, 'paused idle'):
            self.enrich()

    def test_changed_test_hash_cannot_dispatch(self):
        self.proof['input_sha256'][evidence.probe.TEST] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'nonapproving'):
            self.enrich()
        with self.db() as con:
            self.assertEqual(handoffs.load(con, self.source)['stage'], 'test_revision_required')

    def test_arbitrary_command_not_accepted(self):
        with self.assertRaises(ValueError):
            evidence.register(self.broker, {**self.evidence_payload, 'command': 'write'})

    def test_interrupted_missing_probe_not_recreated(self):
        self.broker.docker = lambda *args: None
        with self.assertRaisesRegex(ValueError, 'handle missing'):
            evidence.capture(self.broker, self.source, 'diagnostic', 'b' * 64,
                             self.image, resume=True)

    def stopped_probe(self):
        import docker_grouping
        return dict(Image=self.image, Config=dict(Cmd=['/service_mode_harness_spike.py', 'b' * 64],
            Entrypoint=['python'], User='10000:10000', Labels={
                **docker_grouping.labels(namespace=self.broker.PREFIX),
                'delivery-kit.owner': self.broker.OWNER, 'delivery-kit.source-task': self.source}),
            HostConfig=dict(NetworkMode='none', ReadonlyRootfs=True, CapDrop=['ALL']),
            Mounts=[dict(Type='volume', Name='diagnostic', Destination='/delivery', RW=False)],
            State=dict(StartedAt='2026-10-06T01:00:00Z', Running=False, ExitCode=0))

    def test_completed_exact_probe_is_observed_without_restart_or_deletion(self):
        info = self.stopped_probe()
        calls = []
        def docker(method, path):
            calls.append((method, path))
            return info
        self.broker.docker = docker
        self.broker.docker_stdout = lambda *args, **kwargs: json.dumps(self.proof)
        result = evidence.capture(self.broker, self.source, 'diagnostic', 'b' * 64, self.image, resume=True)
        self.assertEqual(result, self.proof)
        self.assertTrue(all(method == 'GET' for method, _ in calls))

    def test_writable_or_extra_mounts_rejected_on_observation(self):
        for mutation in (lambda info: info['Mounts'][0].update(RW=True),
                         lambda info: info['Mounts'].append(dict(Type='bind', Destination='/var/run/docker.sock'))):
            info = self.stopped_probe()
            mutation(info)
            self.broker.docker = lambda *args: info
            with self.assertRaisesRegex(ValueError, 'exact interrupted'):
                evidence.capture(self.broker, self.source, 'diagnostic', 'b' * 64, self.image, resume=True)

    def test_unsafe_proof_cannot_be_used_as_decision(self):
        for mutate in (lambda p: p.update(delivery_approval=True),
                       lambda p: p['facts']['after_ok'].update(calls=100000),
                       lambda p: p['facts']['after_ok'].update(raw_output='private'),
                       lambda p: p.update(valid_red_green_receipt=True)):
            proof = copy.deepcopy(self.proof)
            mutate(proof)
            with self.assertRaises(ValueError):
                evidence.validate_proof(proof, 'b' * 64)
