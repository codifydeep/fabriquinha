import json
from pathlib import Path
import tempfile
import unittest
from portable_host_service import initial_status,sync_test_blocker
from release_eval import save_receipt


class HostStatusBootstrapTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name).resolve()
        self.config=dict(label='AUTOLOSS-1',issue_id='issue')
        (self.root/'portable-context-AUTOLOSS-1.json').write_text(json.dumps(self.config))

    def test_bootstrap_is_observation_not_approval(self):
        result=initial_status(self.config,self.root,save_receipt)
        self.assertEqual(result['stage'],'waiting_approval')
        self.assertEqual(result['issue_id'],'issue')
        self.assertNotIn('approval',result)

    def test_existing_block_is_never_reset(self):
        path=self.root/'autonomy-status'/'AUTOLOSS-1.json'
        save_receipt(path,dict(self.config,stage='escalation_required'))
        self.assertEqual(initial_status(self.config,self.root,save_receipt)['stage'],'escalation_required')

    def test_wrong_identity_does_not_initialize(self):
        with self.assertRaises(ValueError):initial_status(dict(self.config,issue_id='other'),self.root,save_receipt)
        self.assertFalse((self.root/'autonomy-status').exists())

    def test_new_blocker_updates_projection_without_retry_and_archives_old(self):
        value=dict(self.config,stage='escalation_required',category='test_first_blocked:old')
        managed=dict(route=dict(issue_id='issue'),state=dict(stage='test_first_blocked',source_task='new',
            data=json.dumps(dict(error='test_first_correction_failed_after_cto_diagnosis'))))
        self.assertTrue(sync_test_blocker(value,managed,self.root,save_receipt))
        current=json.loads((self.root/'autonomy-status'/'AUTOLOSS-1.json').read_text())
        self.assertEqual(current['stage'],'escalation_required');self.assertEqual(current['source_task'],'new')
        self.assertEqual(current['owner'],'cto')
        self.assertEqual(len(list((self.root/'autonomy-status'/'history').glob('*.json'))),1)
        self.assertFalse(sync_test_blocker(current,managed,self.root,save_receipt))

    def test_other_issue_or_running_stage_cannot_project_block(self):
        value=dict(self.config,stage='escalation_required',category='old')
        managed=dict(route=dict(issue_id='other'),state=dict(stage='test_first_blocked',data='{}'))
        self.assertFalse(sync_test_blocker(value,managed,self.root,save_receipt))
