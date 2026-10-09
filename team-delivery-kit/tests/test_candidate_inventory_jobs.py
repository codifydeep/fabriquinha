from types import SimpleNamespace
import unittest
from unittest.mock import patch
from broker import candidate_inventory_jobs as jobs
from broker.validation_job import Pending


class CandidateInventoryJobTests(unittest.TestCase):
    def setUp(self):
        self.b=SimpleNamespace(CANDIDATE_INVENTORY_IMAGE='sha256:'+'a'*64,OWNER='owner',
            docker=lambda *_:{'Labels':{'delivery-kit.owner':'owner','delivery-kit.source-task':'source'}},
            handoff_runtime=SimpleNamespace(task_base=lambda *args:{'volume':'base'}))

    def test_fixed_job_has_no_commands_credentials_network_or_writable_mounts(self):
        with patch.object(jobs.validation_job,'run',return_value={'exit_code':0}) as run:
            self.assertEqual(jobs.ensure(self.b,'issue','source','candidate'),self.b.CANDIDATE_INVENTORY_IMAGE)
        b,source,kind,payload=run.call_args.args
        self.assertEqual(kind,'candidate_inventory');self.assertEqual(source,'source')
        self.assertEqual(payload['Cmd'],['/candidate_inventory.py'])
        self.assertEqual(payload['Env'],[]);self.assertTrue(payload['NetworkDisabled'])
        self.assertEqual(payload['HostConfig']['NetworkMode'],'none')
        self.assertTrue(payload['HostConfig']['ReadonlyRootfs'])
        self.assertEqual(payload['HostConfig']['CapDrop'],['ALL'])
        self.assertEqual([m['Source'] for m in payload['HostConfig']['Mounts']],['candidate','base'])
        self.assertTrue(all(m['ReadOnly'] for m in payload['HostConfig']['Mounts']))

    def test_pending_same_job_is_not_failure_or_success_and_bad_ownership_rejected(self):
        with patch.object(jobs.validation_job,'run',side_effect=Pending('same fixed handle')):
            with self.assertRaises(Pending):jobs.ensure(self.b,'issue','source','candidate')
        self.b.docker=lambda *_:{'Labels':{'delivery-kit.owner':'other'}}
        with patch.object(jobs.validation_job,'run') as run:
            with self.assertRaises(ValueError):jobs.ensure(self.b,'issue','source','candidate')
            run.assert_not_called()

    def test_unpinned_image_and_nonzero_inventory_never_authorize_execution(self):
        self.b.CANDIDATE_INVENTORY_IMAGE='mutable:latest'
        with self.assertRaises(ValueError):jobs.ensure(self.b,'issue','source','candidate')
        self.b.CANDIDATE_INVENTORY_IMAGE='sha256:'+'a'*64
        with patch.object(jobs.validation_job,'run',return_value={'exit_code':1}):
            with self.assertRaises(ValueError):jobs.ensure(self.b,'issue','source','candidate')
