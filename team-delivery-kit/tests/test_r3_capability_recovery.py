import unittest
import json
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch
from r3_capability_recovery import recover


class CapabilityRecoveryTests(unittest.TestCase):
    def test_exact_independent_hold_is_preserved_and_new_evidence_is_idempotent(self):
        from portable_remediation_intake import digest
        from r3_incident_capabilities import OPERATIONS,sha
        import r3_incident_capabilities
        evidence={'facts':{'F01':'controller_handle_missing'}}
        proposal={'action':'retain_hold','experiment':'none'}
        review={'decision':'retain_hold','proposal_sha256':digest(proposal)}
        state=dict(stage='retained_hold',diagnosis_task='tl-task',diagnosis_wakeup='tl-wake',
                   review_task='cto-task',wakeup_id='cto-wake',proposal=proposal,review=review)
        saved={'state':state,'config':{'evidence':evidence}}
        proof=dict(catalogue_sha256=sha(),operations=OPERATIONS,
                   module_sha256=hashlib.sha256(Path(r3_incident_capabilities.__file__).read_bytes()).hexdigest(),
                   execution_authorized=False)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'r3-incidents').mkdir()
            path=root/'r3-incidents'/(digest(evidence)+'.json')
            path.write_text(json.dumps(saved));original=path.read_bytes()
            with patch('r3_incident_runtime.Effects') as effects,\
                 patch('r3_incident_runtime.validate_decision',side_effect=[proposal,review,proposal,review]),\
                 patch('r3_capability_recovery.command',return_value=json.dumps(proof)):
                first=recover(root,evidence,state);again=recover(root,evidence,state)
            self.assertEqual(first,again);self.assertEqual(path.read_bytes(),original)
            self.assertEqual(first['facts']['F02'],'fixed_incident_capability_catalogue_qualified')
            receipts=list((root/'r3-capability-reassessments').glob('*.json'))
            self.assertEqual(len(receipts),1)
            self.assertFalse(json.loads(receipts[0].read_text())['execution_authorized'])
            with patch('r3_incident_runtime.Effects'),\
                 patch('r3_incident_runtime.validate_decision',side_effect=[proposal,review]),\
                 patch('r3_capability_recovery.command',return_value=json.dumps({**proof,'catalogue_sha256':'b'*64})):
                with self.assertRaises(ValueError):recover(root,evidence,state)

    def test_unreviewed_work_and_already_clarified_holds_are_never_repeated(self):
        for stage,evidence in [('awaiting_review',{'facts':{}}),
                ('blocked',{'facts':{}}),
                ('retained_hold',{'facts':{'F01':'fixed_incident_capability_catalogue_qualified'}}),
                ('retained_hold',{'facts':{},'experiment_history':['verify_frozen_delivery']})]:
            with patch('r3_capability_recovery.read') as read,patch('r3_capability_recovery.command') as command:
                self.assertIsNone(recover('/unused',evidence,{'stage':stage}))
                read.assert_not_called();command.assert_not_called()
