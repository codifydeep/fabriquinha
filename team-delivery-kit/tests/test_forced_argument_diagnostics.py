"""Rejected patch diagnostics distinguish constraints without retaining proposals."""
import json
from pathlib import Path
import tempfile
import unittest
from artifact_response_contract import validate, ArtifactResponseRejected
from artifact_rejection_receipts import from_event, record, read


class ForcedArgumentDiagnosticsTests(unittest.TestCase):
    def body(self):
        return dict(messages=[dict(role='user', content='DELIVERY_TEST_ARTIFACT_V1:/workspace/tests/test_new.py')],
            tool_choice=dict(function=dict(name='patch')),
            tools=[dict(function=dict(name='patch', parameters=dict(
                required=['path', 'old_string', 'new_string'], properties=dict(
                    path=dict(type='string', enum=['/workspace/tests/test_new.py']),
                    old_string=dict(type='string', minLength=1, maxLength=4096),
                    new_string=dict(type='string', minLength=1, maxLength=4096)))))])

    def rejection(self, **changes):
        args=dict(path='/workspace/tests/test_new.py', old_string='PRIVATE old', new_string='PRIVATE new')
        args.update(changes)
        raw=json.dumps(dict(choices=[dict(finish_reason='tool_calls', message=dict(tool_calls=[
            dict(function=dict(name='patch', arguments=json.dumps(args)))]))])).encode()
        with self.assertRaises(ArtifactResponseRejected) as caught:
            validate(self.body(), raw, 'application/json')
        return caught.exception.diagnostic

    def test_path_type_length_noop_and_utf8_are_distinct(self):
        for args, field, constraint in [
            (dict(path='/PRIVATE'), 'path', 'enum'),
            (dict(old_string=12), 'old_string', 'type'),
            (dict(new_string=''), 'new_string', 'length'),
            (dict(new_string='PRIVATE old'), 'new_string', 'no_change'),
            (dict(new_string='é'*3000), 'new_string', 'utf8_length')]:
            with self.subTest(constraint=constraint):
                info=self.rejection(**args)
                self.assertEqual(info['field'], field)
                self.assertEqual(info['constraint'], constraint)
                self.assertEqual(info['schema'], 'forced-argument-constraint-v1')
                self.assertNotIn('PRIVATE', json.dumps(info))

    def test_argument_receipt_no_authority_and_no_legacy_invention(self):
        event=dict(event='model_proxy_request', status=502,
            execution_id='eb720780-398c-4809-aa34-8c4848b279bf', call_number=5208,
            artifact_selected_tool='patch', artifact_contract_present=True,
            artifact_rejection_category='invalid_forced_argument')
        receipt=from_event(event)
        self.assertIsNotNone(receipt)
        self.assertNotIn('structure', receipt)
        receipt=from_event(dict(event, artifact_rejection_diagnostic=self.rejection(path='/PRIVATE')))
        self.assertEqual(receipt['structure']['constraint'], 'enum')
        self.assertFalse(receipt['write_executed'])
        self.assertFalse(receipt['delivery_approval'])
        for change in (dict(source='PRIVATE'), dict(field='PRIVATE'), dict(characters=True)):
            info=dict(receipt['structure'], **change)
            with self.assertRaises(ValueError):
                from_event(dict(event, artifact_rejection_diagnostic=info))
        with tempfile.TemporaryDirectory() as folder:
            counter=Path(folder)/'calls.json'
            counter.write_text('{"calls":0}')
            enriched=dict(event, artifact_rejection_diagnostic=receipt['structure'])
            record(counter, enriched);record(counter, enriched)
            self.assertEqual(read(counter, event['execution_id']), [receipt])
            with self.assertRaisesRegex(ValueError, 'drift'):
                record(counter, event)

    def test_valid_patch_is_unchanged_and_missing_keys_remain_rejected(self):
        for args, valid in [(dict(path='/workspace/tests/test_new.py', old_string='a', new_string='b'), True),
                            (dict(path='/workspace/tests/test_new.py', new_string='b'), False)]:
            raw=json.dumps(dict(choices=[dict(finish_reason='tool_calls', message=dict(tool_calls=[
                dict(function=dict(name='patch', arguments=json.dumps(args)))]))])).encode()
            if valid:validate(self.body(), raw, 'application/json')
            else:
                with self.assertRaises(ArtifactResponseRejected) as caught:
                    validate(self.body(), raw, 'application/json')
                self.assertEqual(caught.exception.category, 'wrong_forced_arguments')
