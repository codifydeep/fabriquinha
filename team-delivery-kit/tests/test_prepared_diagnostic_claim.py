import json
from pathlib import Path
import tempfile
import unittest
from calibration_diagnostic_probe import claim_prepared_submission


class PreparedDiagnosticClaimTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.prep='11111111-1111-4111-8111-111111111111'
        self.run='22222222-2222-4222-8222-222222222222'
        (self.base/self.prep).mkdir()

    def test_unknown_acknowledgment_does_not_allow_replay(self):
        claim=claim_prepared_submission(self.base,self.prep,self.run,'a'*64)
        self.assertEqual(claim['max_model_calls'],1)
        self.assertIs(claim['automatic_replay'],False)
        with self.assertRaises(FileExistsError):
            claim_prepared_submission(self.base,self.prep,self.run,'a'*64)

    def test_historical_submission_without_claim_also_blocks_replay(self):
        folder=self.base/self.run;folder.mkdir()
        (folder/'identity.json').write_text(json.dumps({'prepared_from':self.prep}))
        with self.assertRaises(ValueError):
            claim_prepared_submission(self.base,self.prep,self.run,'a'*64)

    def test_invalid_identity_or_hash_cannot_claim_submission(self):
        for prep,sha in (('../other','a'*64),(self.prep,'bad')):
            with self.assertRaises(ValueError):claim_prepared_submission(self.base,prep,self.run,sha)
        self.assertFalse((self.base/self.prep/'single-call-claim.json').exists())
