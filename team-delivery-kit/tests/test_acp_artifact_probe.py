import unittest
from probe_acp_artifact import valid_artifact, seeded_tool_receipts


class AcpArtifactProbeTests(unittest.TestCase):
    def frames(self):
        frames=[]
        for identifier,kind,title in [('a','read','read: /workspace/app.py'),
                ('b','read','read: /workspace/tests/test_new.py'),
                ('c','edit','patch (replace): /workspace/tests/test_new.py')]:
            for update in [dict(sessionUpdate='tool_call',toolCallId=identifier,kind=kind,title=title),
                           dict(sessionUpdate='tool_call_update',toolCallId=identifier,status='completed')]:
                frames.append(dict(method='session/update',params=dict(update=update)))
        return frames

    def test_actual_workspace_reads_and_patch_are_paired(self):
        self.assertEqual(seeded_tool_receipts(self.frames()),dict(actual_patch_calls=1,
            actual_read_calls=2,paired_patch_results=1,tool_protocol_valid=True))

    def test_missing_failed_duplicate_or_unknown_result_is_not_completion(self):
        frames=self.frames()
        for altered in (frames[:-1],frames+[frames[-1]],frames+[frames[0]],
                frames+[dict(method='session/update',params=dict(update=dict(
                    sessionUpdate='tool_call_update',toolCallId='unknown',status='completed')))]):
            self.assertFalse(seeded_tool_receipts(altered)['tool_protocol_valid'])

    def test_write_and_other_paths_are_not_patch_evidence(self):
        for title in ('write: /workspace/tests/test_new.py','patch (replace): /workspace/app.py'):
            frames=self.frames()
            frames[-2]['params']['update']['title']=title
            receipt=seeded_tool_receipts(frames)
            self.assertFalse(receipt['tool_protocol_valid'])
            self.assertEqual(receipt['actual_patch_calls'],0)

    def test_seeded_probe_uses_real_transport_and_only_narrow_fixture_patch(self):
        import inspect
        import ast
        from probe_acp_artifact import remote_probe
        source=inspect.getsource(remote_probe)
        compile(source,'real-acp-probe','exec');ast.parse(source)
        for term in ('acp-seeded-patch-probe-v1','expected_patch_applied','paired_patch_results',
                     'DELIVERY_SEEDED_EDIT_REQUIRED_V1','synthetic-probe-evidence'):
            self.assertIn(term,source)
        self.assertIn("if seeded_patch:",source)
        self.assertNotIn('force=true',source)
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
