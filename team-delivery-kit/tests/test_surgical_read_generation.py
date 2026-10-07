import copy
import json
import unittest

from artifact_read_evidence import observations
from test_artifact_schema import apply
import test_surgical_typed_tool as fixtures


class SurgicalReadGenerationTests(unittest.TestCase):
    def saved(self):
        fixture = fixtures.TypedSurgicalTests()
        body = fixture.body()
        body['messages'] += [
            dict(role='assistant', tool_calls=[dict(id='saved-edit', function=dict(
                name='surgical_test_edit', arguments=json.dumps(fixture.args())))]),
            dict(role='tool', tool_call_id='saved-edit', content=json.dumps(dict(
                operation='surgical_test_edit_v1', verified=True, path=fixture.config()['path'],
                before_sha256='a'*64, sha256='b'*64, bytes_written=10,
                test_bodies_preserved=True, delivery_approval=False))),
            dict(role='assistant', tool_calls=[dict(id='post-read', function=dict(
                name='read_file', arguments=json.dumps(dict(
                    path=fixture.config()['path'], offset=1, limit=50))))]),
            dict(role='tool', tool_call_id='post-read', content=json.dumps(dict(
                content='1|changed', total_lines=1)))]
        return body

    def test_saved_edit_keeps_pre_edit_inspection_after_changed_read(self):
        body = self.saved()
        original = copy.deepcopy(body)
        self.assertIs(apply(body), body)
        self.assertEqual(body, original)
        # Immutable review coverage must still reject mixed generations.
        self.assertNotIn('/workspace/tests/test_new.py', observations(body['messages'], wire=True))

    def test_unpaired_or_wrong_receipt_cannot_end_inspection(self):
        for field, value in [('tool_call_id', 'unpaired'), ('sha256', 'a'*64),
                             ('delivery_approval', True), ('verified', False),
                             ('bytes_written', True), ('before_sha256', 'c'*64)]:
            with self.subTest(field=field):
                body = self.saved()
                message = body['messages'][-3]
                if field == 'tool_call_id':
                    message[field] = value
                else:
                    receipt = json.loads(message['content']); receipt[field] = value
                    message['content'] = json.dumps(receipt)
                self.assert_blocked(body)

    def assert_blocked(self, body):
        try:
            result = apply(body)
        except ValueError:
            return  # Fail-closed stalled inspection is acceptable for invalid receipts.
        self.assertIsNot(result, body)

    def test_missing_pre_edit_reads_cannot_be_replaced_by_post_edit_reads(self):
        body = self.saved()
        del body['messages'][3:5]  # Remove the complete target read before editing.
        self.assert_blocked(body)

    def test_wrong_call_hash_or_tool_cannot_authorize_receipt(self):
        for name, args in [('write_file', {}), ('surgical_test_edit', dict(
                path='/workspace/tests/test_new.py', expected_sha256='c'*64, edits=[]))]:
            body = self.saved()
            body['messages'][-4]['tool_calls'][0]['function'] = dict(
                name=name, arguments=json.dumps(args))
            self.assert_blocked(body)

    def test_actual_v6_line_edit_uses_same_generation_boundary(self):
        body = self.saved()
        body['messages'][0]['content'] = body['messages'][0]['content'].replace(
            'SURGICAL_TEST_V2', 'SURGICAL_TEST_V6')
        body['messages'][-4]['tool_calls'][0]['function']['arguments'] = json.dumps(dict(
            path='/workspace/tests/test_new.py', expected_sha256='a'*64,
            edits=[dict(start_line=1, end_line=1, new='changed\n')]))
        self.assertIs(apply(body), body)

    def test_failed_result_cannot_be_replayed_as_success(self):
        body = self.saved()
        failed = copy.deepcopy(body['messages'][-3])
        failed['content'] = json.dumps(dict(error='denied', verified=False))
        body['messages'].insert(len(body['messages'])-3, failed)
        self.assert_blocked(body)

    def test_duplicate_call_id_is_not_authoritative(self):
        body = self.saved()
        body['messages'].insert(len(body['messages'])-3, copy.deepcopy(body['messages'][-4]))
        self.assert_blocked(body)

    def test_incomplete_other_source_read_is_not_authorized(self):
        body = self.saved()
        del body['messages'][1:3]
        self.assert_blocked(body)
