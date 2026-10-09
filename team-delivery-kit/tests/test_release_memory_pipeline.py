import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from release_memory_pipeline import advance,native_idle


class PostDeliveryMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'flow.json';self.calls=[]
        self.identity={'repository':'https://github.com/acme/demo','namespace':'delivery-kit-one','config':'a'*64}
        self.evidence=['b'*64,'c'*64];self.stage='awaiting_native_review'

    def qualify(self):self.calls.append('qualify');return self.evidence
    def nominate(self):self.calls.append('nominate');return 'd'*64
    def curate(self,key):
        self.calls.append(('curate',key));return {'stage':self.stage,'issue_id':'native-review','delivery_approval':False}
    def run_flow(self):
        return advance(self.path,self.identity,qualify=self.qualify,nominate=self.nominate,curate=self.curate)

    def test_restart_preserves_nomination_and_revalidates_receipts_before_observation(self):
        first=self.run_flow();second=self.run_flow()
        self.assertEqual(first,second);self.assertEqual(self.calls.count('nominate'),1)
        self.assertEqual(self.calls.count('qualify'),2)
        self.assertEqual(self.calls[0],'qualify')
        self.assertFalse(second['delivery_approval']);self.assertEqual(second['owner'],'techlead')

    def test_approval_is_memory_only_and_remains_bound_to_delivery_evidence(self):
        self.stage='approved';result=self.run_flow();self.calls.clear();self.run_flow()
        self.assertEqual(self.calls,['qualify']);self.assertFalse(result['delivery_approval'])
        self.evidence=['different receipt']
        with self.assertRaisesRegex(ValueError,'identity drift'):self.run_flow()

    def test_rejection_and_failure_are_terminal_not_identical_native_retries(self):
        for stage in ('rejected','blocked'):
            self.path.unlink(missing_ok=True);self.calls.clear();self.stage=stage
            result=self.run_flow();self.run_flow()
            self.assertEqual(sum(isinstance(call,tuple) for call in self.calls),1)
            if stage=='blocked':self.assertEqual(result['owner'],'cto')

    def test_no_nomination_or_dispatch_when_delivery_is_not_proven(self):
        def reject():raise ValueError('missing browser QA')
        with self.assertRaises(ValueError):
            advance(self.path,self.identity,qualify=reject,nominate=self.nominate,curate=self.curate)
        self.assertFalse(self.path.exists());self.assertEqual(self.calls,[])

    def test_nomination_intent_precedes_effect_and_unknown_dispatch_errors_block(self):
        def nominate():
            self.assertEqual(json.loads(self.path.read_text())['stage'],'nomination_intent')
            return 'd'*64
        def failed(key):raise subprocess.TimeoutExpired('uncertain dispatch',5)
        result=advance(self.path,self.identity,qualify=self.qualify,nominate=nominate,curate=failed)
        self.assertEqual(result['stage'],'blocked');self.assertEqual(result['owner'],'cto')
        self.assertEqual(result['category'],'TimeoutExpired');self.assertFalse(result['delivery_approval'])
        self.assertEqual(self.run_flow()['stage'],'blocked')

    def test_capacity_observer_is_owned_readonly_and_fails_closed(self):
        outputs=[json.dumps({'com.docker.compose.project':'delivery-kit-one',
                             'com.docker.compose.service':'execution-broker'}),json.dumps({'idle':False})]
        with patch('release_memory_pipeline.subprocess.check_output',side_effect=outputs) as call:
            self.assertFalse(native_idle('delivery-kit-one'))
            self.assertEqual(call.call_args_list[-1].args[0][:4],['docker','exec','-w','/'])
            self.assertIn('m.native_active(b)',call.call_args_list[-1].args[0][-1])
        with self.assertRaises(ValueError):native_idle('unrelated')
        with patch('release_memory_pipeline.subprocess.check_output',return_value='{}'):
            with self.assertRaisesRegex(ValueError,'owned'):native_idle('delivery-kit-one')
