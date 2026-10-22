"""Fixed green-job input contract, not controller/native authorization."""
import json
import unittest
from unittest.mock import patch
import quality_green_job as job


class GreenJobTests(unittest.TestCase):
    def snapshot(self):
        return dict(operation='snapshot_after_implementation_v2',plan={},base_manifest_sha256='a'*64,
            reviewed_manifest_sha256='b'*64,frozen_tests={})

    def test_snapshot_uses_fixed_paths_without_command_or_resume_authority(self):
        request=self.snapshot()
        with patch.object(job.snapshot,'copy',return_value={'kind':'fixture'}) as copy:
            self.assertEqual(job.run(request),{'kind':'fixture'})
        self.assertEqual(copy.call_args.args[:4],('/base','/reviewed','/workspace','/snapshot'))
        self.assertEqual(copy.call_args.kwargs,{})

    def test_unknown_fields_operations_commands_and_oversized_input_fail_closed(self):
        for request in ({**self.snapshot(),'command':'sh'},{**self.snapshot(),'resume':True},
                {**self.snapshot(),'operation':'arbitrary'},[],{}):
            with self.subTest(request=request),self.assertRaises(ValueError):job.request(json.dumps(request))
        with self.assertRaises(ValueError):job.request(' '*65537)
        for operation in ([],None,True):
            with self.assertRaises(ValueError):job.request(json.dumps({**self.snapshot(),'operation':operation}))

    def test_observation_receives_only_fixed_snapshot_paths_and_bound_metadata(self):
        request=dict(operation='observe_green_v2',plan={},task_id='task',base_manifest_sha256='a'*64,
            snapshot_manifest_sha256='b'*64,green_context={})
        with patch.object(job.observer,'run',return_value={'kind':'fixture'}) as observe:
            self.assertEqual(job.run(request),{'kind':'fixture'})
        self.assertEqual(observe.call_args.args[:2],('/base','/snapshot'))
        self.assertEqual(observe.call_args.kwargs,dict(green_context={}))

    def test_missing_green_context_cannot_fall_back_to_red_observation(self):
        value=dict(operation='observe_green_v2',plan={},task_id='task',base_manifest_sha256='a'*64,
            snapshot_manifest_sha256='b'*64,green_context=None)
        with patch.object(job.observer,'run') as observe,self.assertRaises(ValueError):job.run(value)
        observe.assert_not_called()


if __name__=='__main__':unittest.main()
