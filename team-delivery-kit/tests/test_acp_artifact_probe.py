import unittest
from probe_acp_artifact import valid_artifact


class AcpArtifactProbeTests(unittest.TestCase):
    def test_actual_artifact_and_preserved_baseline_required(self):
        record = dict(baseline_unchanged=True, credentials_absent=True,
                      bytes=100, test_methods=1, syntax_valid=True)
        self.assertTrue(valid_artifact(record))
        for key, value in [('baseline_unchanged', False), ('credentials_absent', False),
                           ('bytes', 0), ('test_methods', 0), ('syntax_valid', False)]:
            self.assertFalse(valid_artifact(dict(record, **{key: value})))

    def test_prose_or_empty_record_is_not_execution_evidence(self):
        self.assertFalse(valid_artifact({}))
        self.assertFalse(valid_artifact({'status': 'I wrote a test'}))
