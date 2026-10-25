"""One-shot safety with a local mocked transport; never call a provider."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('canary',ROOT/'scripts/canary_provider.py')
canary=importlib.util.module_from_spec(spec);spec.loader.exec_module(canary)


class CanarySafety(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.meter=self.root/'meter';self.meter.mkdir()
        canary.write_json(self.meter/'calls.json',dict(calls=7))
        self.pause=dict(category='upstream_payment_required',upstream_status=402,call_number=7)
        canary.write_json(self.meter/'provider-pause.json',self.pause)
        self.key=self.root/'fixture.key';self.key.write_text('fixture-only-not-a-real-credential');self.key.chmod(0o600)
        self.authorization='a'*32

    def invoke(self,expected=7):
        with redirect_stdout(io.StringIO()):
            return canary.one(self.meter,self.key,self.authorization,'example/model',expected,10)

    def test_success_archives_pause_and_makes_only_one_bounded_request(self):
        response=json.dumps(dict(choices=[dict(message=dict(content='OK'))])).encode()
        with patch.object(canary.Relay,'forward',return_value=(200,response)) as forward:
            result=self.invoke();self.assertTrue(result['valid_reply']);self.assertEqual(result['calls_after'],8)
            self.assertEqual(forward.call_count,1)
            body=forward.call_args.args[0];self.assertEqual(body['max_tokens'],128);self.assertNotIn('tools',body)
            with self.assertRaises(ValueError):self.invoke()
            self.assertEqual(forward.call_count,1)
        archive=self.meter/'canaries'/self.authorization/'pause-before.json'
        self.assertEqual(json.loads(archive.read_bytes()),self.pause)

    def test_payment_error_reinstates_pause_with_new_counter_without_retry(self):
        with patch.object(canary.Relay,'forward',return_value=(402,b'not published')) as forward:
            result=self.invoke();self.assertEqual(result['status'],402);self.assertEqual(forward.call_count,1)
        self.assertEqual(json.loads((self.meter/'provider-pause.json').read_bytes()),{**self.pause,'call_number':8})

    def test_changed_counter_or_missing_credential_preserves_original_pause(self):
        with patch.object(canary.Relay,'forward') as forward:
            with self.assertRaises(ValueError):self.invoke(6)
            self.key.unlink()
            with self.assertRaises(ValueError):self.invoke()
            forward.assert_not_called()
        self.assertEqual(json.loads((self.meter/'provider-pause.json').read_bytes()),self.pause)
        self.assertFalse((self.meter/'canaries').exists())


if __name__=='__main__':unittest.main()
