import unittest
from migrate_agent_models import targets, owned_runtimes
from model_policy import MODEL, PREVIOUS_MODEL


class ModelMigrationScopeTests(unittest.TestCase):
    def test_only_exact_installation_devices_are_selected(self):
        runtimes=[{'id':'primary','provider':'hermes','device_info':'delivery-kit-port2 · isolated'},
                  {'id':'legacy','provider':'hermes','device_info':'delivery-kit-port2 · Hermes'},
                  {'id':'host','provider':'hermes','device_info':'other-host'},
                  {'id':'suffix','provider':'hermes','device_info':'delivery-kit-port2-other · Hermes'}]
        self.assertEqual(owned_runtimes(runtimes,'delivery-kit-port2','primary'),{'primary','legacy'})
        with self.assertRaises(ValueError):owned_runtimes(runtimes,'delivery-kit-port2','host')

    def test_scope_ignores_other_runtimes_and_nonmodel_boundary(self):
        old={'runtime_id':'owned','model':PREVIOUS_MODEL}
        new={'runtime_id':'owned','model':MODEL}
        agents=[old,new,{'runtime_id':'other','model':'other/model'},
                {'runtime_id':'owned','model':''}]
        self.assertEqual(targets(agents,'owned'),[old,new])

    def test_unknown_model_and_empty_scope_are_blocked(self):
        for agents in ([],[{'runtime_id':'owned','model':'other/model'}]):
            with self.assertRaises(ValueError):targets(agents,'owned')
