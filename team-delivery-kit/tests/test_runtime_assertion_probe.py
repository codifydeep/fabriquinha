import importlib.util
import hashlib
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from broker import assertion_witness


class RuntimeProbeTests(unittest.TestCase):
    def setUp(self):
        path=pathlib.Path(__file__).parents[1]/'broker/runtime_assertion_probe.py'
        with patch.dict('sys.modules',{'assertion_witness':assertion_witness}):
            spec=importlib.util.spec_from_file_location('runtime_probe',path);self.probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.probe)

    def test_reports_never_publish_nonfixture_strings_or_large_data(self):
        value=dict(ok=False,title='fixture',private='secret',items=['fixture','secret'],count=2)
        result=self.probe.safe_value(value,{'fixture'})
        self.assertEqual(result['ok'],False);self.assertEqual(result['title'],'fixture')
        self.assertEqual(result['private'],{'redacted_type':'str'});self.assertEqual(result['count'],2)
        self.assertEqual(self.probe.safe_value(['x']*17,{'x'}),{'redacted_type':'list'})

    def test_event_order_is_bounded_and_untrusted_values_redacted(self):
        raw=dict(events=[dict(sequence=1,context=1,kind='fetch_started',query='secret',method='GET')],total_events=1,truncated=False)
        clean=self.probe.clean_event_report(raw,set());self.assertEqual(clean['events'][0]['query'],{'redacted_type':'str'})
        raw['events'].append(raw['events'][0])
        with self.assertRaises(ValueError):self.probe.clean_event_report(raw,set())

    def test_fixed_probe_does_not_suppress_original_assertions(self):
        source=pathlib.Path(self.probe.__file__).read_text()
        self.assertIn('return original(test,*args,**kwargs)',source)
        self.assertIn("unittest.defaultTestLoader.discover(str(root/'tests')",source)
        self.assertIn("status='experiment_only_not_green_or_approval',approval=False",source)

    def test_observation_preserves_actual_failure_and_restores_assertion(self):
        class Fixture(unittest.TestCase):
            def id(self):return 'tests.new.Case.test_x'
            def runTest(self):
                report={'stale':False,'title':'fixture','private':'secret'}
                self.report=report
                self.assertTrue(report['stale'])
        original=unittest.TestCase.assertTrue
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);(root/'tests').mkdir();raw=b'TITLE="fixture"\n';(root/'tests/new.py').write_bytes(raw)
            digest=hashlib.sha256(raw).hexdigest();(root/'manifest.json').write_text(json.dumps(dict(files={'tests/new.py':{'sha256':digest}})))
            proof=dict(manifest_sha256='a'*64,output_sha256='b'*64,anchors=[dict(qualified_name='tests.new.Case.test_x',assertion='assertTrue',line=Fixture.runTest.__code__.co_firstlineno+3,fields=['stale'])])
            with patch.object(self.probe,'extract_trace',return_value=proof),patch.object(unittest.defaultTestLoader,'discover',return_value=unittest.TestSuite([Fixture()])):
                result=self.probe.run(root,{'tests/new.py':digest},'')
        self.assertEqual(result['suite']['failures'],1);self.assertEqual(result['suite']['errors'],0)
        self.assertFalse(result['approval']);self.assertEqual(result['runtime_observations'][0]['operands'],[False])
        self.assertEqual(result['runtime_observations'][0]['reports']['report']['private'],{'redacted_type':'str'})
        self.assertEqual(result['runtime_observations'][0]['reports']['self_report'],{'stale':False})
        self.assertIs(unittest.TestCase.assertTrue,original)

    def test_numeric_failure_observation_does_not_weaken_threshold_or_suppress_failure(self):
        class Fixture(unittest.TestCase):
            def id(self):return 'tests.new.Case.test_x'
            def runTest(self):
                self.report={'poll_requests':2}
                self.assertGreaterEqual(self.report['poll_requests'],3)
        original=unittest.TestCase.assertGreaterEqual
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);(root/'tests').mkdir();raw=b'VALUE=3\n';(root/'tests/new.py').write_bytes(raw)
            digest=hashlib.sha256(raw).hexdigest();(root/'manifest.json').write_text(json.dumps(dict(files={'tests/new.py':{'sha256':digest}})))
            proof=dict(manifest_sha256='a'*64,output_sha256='b'*64,anchors=[dict(qualified_name='tests.new.Case.test_x',
                assertion='assertGreaterEqual',line=Fixture.runTest.__code__.co_firstlineno+2,fields=['poll_requests'])])
            with patch.object(self.probe,'extract_trace',return_value=proof),patch.object(unittest.defaultTestLoader,'discover',return_value=unittest.TestSuite([Fixture()])):
                result=self.probe.run(root,{'tests/new.py':digest},'')
        self.assertEqual(result['suite']['failures'],1);self.assertEqual(result['suite']['errors'],0)
        self.assertEqual(result['runtime_observations'][0]['operands'],[2,3])
        self.assertEqual(result['runtime_observations'][0]['reports']['self_report'],{'poll_requests':2})
        self.assertFalse(result['approval']);self.assertIs(unittest.TestCase.assertGreaterEqual,original)
