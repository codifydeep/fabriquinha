import copy
import unittest
from calibration_json_transport_probe import run,source_hashes
from broker import calibration_incident_job as jobs


class JsonTransportProbeTests(unittest.TestCase):
    def test_fixed_experiment_proves_current_transport_not_historical_cause_or_delivery(self):
        proof=run();jobs.validate(proof,source_hashes(),'json')
        self.assertEqual(proof['model_calls'],0);self.assertFalse(proof['product_tests_executed'])
        self.assertFalse(proof['historical_cause_proven']);self.assertFalse(proof['delivery_approval'])
        for key in proof['checks']:
            bad=copy.deepcopy(proof);bad['checks'][key]=False
            with self.assertRaises(ValueError):jobs.validate(bad,source_hashes(),'json')
        with self.assertRaises(ValueError):jobs.validate(proof,source_hashes())
