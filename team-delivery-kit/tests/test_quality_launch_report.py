"""Canary claims need bound frame identities, never a worker-alive assertion."""
import copy
import unittest
import uuid
from qualify_quality_author_launch import validate_report


class ReportTests(unittest.TestCase):
    def report(self):
        ids=[str(uuid.uuid4()) for _ in range(7)]
        frames=[dict(method=m,status='passed',response_sha256='a'*64) for m in ('initialize','session/new')]
        followup=dict(status='passed',source_task=ids[4],task_id=ids[5],request_id=ids[6],frames=frames,
            forced_interleaving=['created','running'],snapshot_mount='readonly',handler_byte_binding=True,
            tests_approved=False,delivery_approval=False)
        return dict(status='passed',docker='real',acp='real',native_api='synthetic_fixture',delivery_approval=False,
            model_calls=0,prompts_sent=0,frames=frames,task_id=ids[0],request_id=ids[1],
            review_launch=dict(status='passed',source_task=ids[0],task_id=ids[2],request_id=ids[3],manifest_sha256='b'*64,
                tests_approved=False,delivery_approval=False,snapshot_mount='readonly',frames=frames,
                test_revision=dict(status='passed',native_authority='synthetic_rejection_fixture',seed_unchanged=True,
                    protected_unchanged=True,frames=frames,tests_approved=False,delivery_approval=False,review_after_correction=followup)))

    def test_followup_remains_a_zero_model_transport_fixture_not_approval(self):validate_report(self.report())

    def test_missing_interleaving_frame_hash_or_readonly_proof_rejects_claim(self):
        for change in ('order','frame','hash','mount','approval','identity'):
            report=self.report();followup=copy.deepcopy(report['review_launch']['test_revision']['review_after_correction'])
            if change=='order':followup['forced_interleaving']=['running','created']
            if change=='frame':followup['frames']=followup['frames'][:1]
            if change=='hash':followup['frames'][0]['response_sha256']='claimed'
            if change=='mount':followup['snapshot_mount']='rw'
            if change=='approval':followup['tests_approved']=True
            if change=='identity':followup['task_id']='unknown'
            report['review_launch']['test_revision']['review_after_correction']=followup
            with self.subTest(change=change),self.assertRaises(ValueError):validate_report(report)
