"""Failure observation must prove terminal process and retirement, not timeout."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import qualify_quality_author_workspace as qualifier


class QualificationFailureTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.namespace='delivery-kit-test'
        self.operation='70000000-0000-4000-8000-000000000001'
        self.archive=self.root/'.local-test/backups'/('quality-author-docker-'+self.operation)
        self.archive.mkdir(parents=True)
        (self.archive/'operation.json').write_text(json.dumps(dict(operation=self.operation,worker_image=None,volumes={})))
        self.p=patch.object(qualifier,'ROOT',self.root);self.p.start();self.addCleanup(self.p.stop)

    def record(self,phase,code):
        name=self.namespace+'-author-probe-'+self.operation[:8]+'-'+phase
        (self.archive/(phase+'-intent.json')).write_text(json.dumps(dict(argv=['docker','run','--name',name])))
        (self.archive/(phase+'-result.json')).write_text(json.dumps(dict(exit_code=code)))
        return name

    def test_nonzero_result_and_exact_retired_helper_records_failure_not_success(self):
        name=self.record('seed',1)
        with patch.object(qualifier,'await_retirement') as observe:
            result=qualifier.observe_failure(self.namespace,self.operation)
        observe.assert_called_once_with(name)
        self.assertEqual(result['status'],'failed');self.assertFalse(result['delivery_approval'])
        self.assertEqual(json.loads((self.archive/'result.json').read_text()),result)

    def test_missing_or_still_live_helper_result_never_closes_unknown_outcome(self):
        with patch.object(qualifier,'await_retirement'):
            with self.assertRaises(FileNotFoundError):qualifier.observe_failure(self.namespace,self.operation)
        self.record('seed',1)
        with patch.object(qualifier,'await_retirement',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):qualifier.observe_failure(self.namespace,self.operation)
        self.assertFalse((self.archive/'result.json').exists())


if __name__=='__main__':unittest.main()
