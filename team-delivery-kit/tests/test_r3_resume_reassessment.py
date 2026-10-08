import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from r3_resume_reassessment import recover
from r3_resume_contract import sha
from portable_remediation_intake import digest


class ResumeReassessmentTests(unittest.TestCase):
    def test_complete_reviewed_hold_preserved_once_and_no_delivery_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'r3-incidents';folder.mkdir()
            evidence=dict(experiment_history=['observe_existing_controller','verify_frozen_delivery','verify_github_ci','verify_local_deployment'],
                facts={f'F{i}':v for i,v in enumerate(['experiment_snapshot_intact','experiment_github_ci_exact_sha',
                    'experiment_local_deployment_exact_sha','experiment_controller_absent'],1)})
            key=digest(evidence);state=dict(stage='retained_hold',post_experiment=True,incident_sha256=key,issue_id='issue',
                proposal={'action':'retain_hold'},review={'decision':'retain_hold'},release_homologated=False)
            path=folder/(key+'.json');path.write_text(json.dumps(dict(config={'evidence':evidence},state=state)))
            proof=dict(incident_sha256=key,issue_id='issue',policy_sha256=sha(),execution_authorized=False,release_homologated=False)
            with patch('r3_verified_resume.verify_lineage') as lineage,patch('r3_incident_runtime.Effects') as fx:
                fx.return_value.request.return_value=dict(proof=proof,reassessment_sha256=digest(proof))
                result=recover(root,state,{'original':'bundle'})
                self.assertEqual(result['stage'],'diagnose_dispatch');self.assertEqual(result['previous_reviewed_hold'],state)
                self.assertFalse(result['release_homologated']);lineage.assert_called_once()
                self.assertIsNone(recover(root,{**result,'stage':'retained_hold'},{}));self.assertEqual(fx.return_value.request.call_count,1)

    def test_partial_or_failed_experiment_hold_does_not_reassess(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'r3-incidents').mkdir()
            s=dict(stage='retained_hold',post_experiment=True,incident_sha256='a'*64,proposal={'action':'retain_hold'},review={'decision':'retain_hold'})
            (root/'r3-incidents'/('a'*64+'.json')).write_text(json.dumps(dict(config={'evidence':{'experiment_history':[],'facts':{}}},state=s)))
            with patch('r3_incident_runtime.Effects') as fx:
                self.assertIsNone(recover(root,s,{}));fx.assert_not_called()
