import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import literal_author_feedback as feedback
import test_literal_poll_capture_experiment as capture_tests


class LiteralAuthorFeedbackTests(unittest.TestCase):
    def inputs(self):
        fixture=capture_tests.PollCaptureExperimentTests();self.addCleanup(fixture.doCleanups)
        previous,manifest,raw=fixture.fixture()
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        candidate=Path(temporary.name);(candidate/'tests').mkdir();(candidate/'tests/test.py').write_bytes(raw)
        return previous,candidate,manifest,hashlib.sha256(raw).hexdigest()

    def test_live_feedback_names_exact_failing_capture_and_keeps_all_authority_false(self):
        previous,candidate,manifest,sha=self.inputs()
        value=feedback.run(previous,candidate,manifest,'tests/test.py',sha)
        self.assertFalse(value['checks_passed']);self.assertEqual(value['failed_fields'],['poll_requests'])
        self.assertEqual(value['capture']['assignment'],'snap.poll_requests = latestCount();')
        self.assertGreater(value['capture']['literal_line'],0)
        self.assertEqual(value['expected']['poll_minimum'],3)
        self.assertEqual(value['reports']['guarded']['poll_requests'],2)
        self.assertIn('BEFORE this assignment',value['next_action'])
        self.assertIn('not the later stale-response block',value['next_action'])
        self.assertEqual(value['non_target_verification'],'not_performed_in_feedback')
        for flag in feedback.FALSE_FLAGS:self.assertIs(value[flag],False)

    def test_controller_measurement_observes_real_local_change_but_is_not_delivery_green(self):
        previous,candidate,manifest,_=self.inputs();path=candidate/'tests/test.py'
        raw=path.read_bytes();changed=raw.replace(b'snap.poll_requests = latestCount();',
            b'tick(); await flush(); snap.poll_requests = latestCount();')
        # This intentional same-line variation is outside the supported capture
        # locator. A real tool must fail closed instead of inventing a line.
        path.write_bytes(changed)
        with self.assertRaises(ValueError):feedback.run(previous,candidate,manifest,'tests/test.py',hashlib.sha256(changed).hexdigest())
        changed=raw.replace(b'  snap.poll_requests = latestCount();',
            b'  tick();\\n  await flush();\\n  snap.poll_requests = latestCount();')
        path.write_bytes(changed);sha=hashlib.sha256(changed).hexdigest()
        value=feedback.run(previous,candidate,manifest,'tests/test.py',sha)
        self.assertTrue(value['checks_passed']);self.assertEqual(value['failed_fields'],[])
        self.assertEqual(value['reports']['guarded']['poll_requests'],3)
        self.assertEqual(path.read_bytes(),changed);self.assertFalse(value['product_green'])

    def test_outside_literal_change_stale_hash_or_symlink_never_yields_feedback_success(self):
        previous,candidate,manifest,sha=self.inputs();path=candidate/'tests/test.py'
        with self.assertRaises(ValueError):feedback.run(previous,candidate,manifest,'tests/test.py','f'*64)
        original=path.read_bytes();path.write_bytes(original.replace(b'assertGreaterEqual',b'assertEqual'))
        with self.assertRaises(ValueError):feedback.run(previous,candidate,manifest,'tests/test.py',hashlib.sha256(path.read_bytes()).hexdigest())
        path.unlink();path.symlink_to(previous/'tests/test.py')
        with self.assertRaises(ValueError):feedback.run(previous,candidate,manifest,'tests/test.py',sha)

    def test_concurrent_edit_during_evaluation_discards_observation(self):
        previous,candidate,manifest,sha=self.inputs();path=candidate/'tests/test.py'
        real=feedback.protocol.node
        def race(*args):
            value=real(*args);path.write_bytes(path.read_bytes()+b'\n');return value
        with patch.object(feedback.protocol,'node',side_effect=race):
            with self.assertRaises(ValueError):feedback.run(previous,candidate,manifest,'tests/test.py',sha)
