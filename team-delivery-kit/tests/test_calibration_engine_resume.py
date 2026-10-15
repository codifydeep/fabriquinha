from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from broker import generic_calibration_workflow as workflow
from broker import remediation_runtime_guard as guard,remediation_admission as admission
import test_generic_calibration_proposal_collector as samples


class EngineResumeTests(unittest.TestCase):
    def setUp(self):
        f=samples.ProposalCollectorTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f

    def request(self,**kwargs):
        f=self.f
        with ExitStack() as stack:
            stack.enter_context(patch.object(guard,'qualified',return_value=f.value))
            stack.enter_context(patch.object(admission,'Effects',return_value=SimpleNamespace(plan=lambda source:(
                dict(cto='cto',reviewer='lead',original_author='author'),dict(plan_sha256=f.value['plan_sha256'])))))
            stack.enter_context(patch.object(workflow,'Effects',return_value=SimpleNamespace(verify=lambda c:None,plans=f.fx)))
            return workflow.request(f.b,'issue','author-task',**kwargs)

    def test_default_resume_uses_persisted_v2_without_downgrade_or_reconfiguration(self):
        first=self.request(engine='unittest_path_fixtures_v2')
        self.assertEqual(self.request(),first)
        with self.assertRaises(ValueError):self.request(engine='unittest_path_fixture_v1')

    def test_legacy_default_remains_v1_and_explicit_upgrade_cannot_change_existing_config(self):
        first=self.request();self.assertEqual(self.request(),first)
        with self.assertRaises(ValueError):self.request(engine='unittest_path_fixtures_v2')

    def test_resuming_persisted_engine_still_revalidates_original_author(self):
        self.request(engine='unittest_path_fixtures_v2')
        self.f.con.execute("UPDATE leases SET status='running' WHERE request_id='author'")
        with self.assertRaises(ValueError):self.request()
