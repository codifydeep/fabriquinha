import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import archive_capacity_probe as a


class ArchiveCapacityProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.folder=self.root/'provider-probes';self.folder.mkdir(mode=0o700)
        self.identifier='11111111-1111-4111-8111-111111111111'
        self.inputs=dict(issue_id='issue',source_task='source',manifest_sha256='a'*64,
            target='/workspace/tests/test_new.py',files={'/workspace/tests/test_new.py':'#'+'x'*32670})
        self.probe=dict(issue_id='issue',source_task='source',execution_id=self.identifier,
            diagnostic_parent='22222222-2222-4222-8222-222222222222',status='failed',
            failure_category='fixture_protocol_rejected',fixture_kind='frozen_context_prospective_v1',
            input_sha256=a.capacity.digest(self.inputs),manifest_sha256='a'*64,
            tools_executed=False,candidate_files_written=False,native_read_evidence=False,
            historical_failure_cause_proven=False,product_retry=False,delivery_approval=False,
            proxy_image='sha256:'+'c'*64,local_rejection=dict(schema='local-proposal-rejection-v1',
                constraint='artifact_size',response_sha256='b'*64,
                tools_executed=False,candidate_files_written=False))
        for suffix,value in (('.json',self.probe),('.input.json',self.inputs)):
            path=self.folder/('frozen-patch-'+self.identifier+suffix)
            path.write_text(json.dumps(value));path.chmod(0o600)
        self.commands=[];self.stored=dict(self.probe);self.image=self.probe['proxy_image']

    def command(self,cmd,**kwargs):
        self.commands.append(cmd)
        if cmd[:2]==['docker','inspect']:
            if cmd[-1]=='{{.Image}}':return self.image
            service='model-proxy' if 'model-proxy' in cmd[2] else 'execution-broker'
            return json.dumps({'com.docker.compose.project':'delivery-kit-port2','com.docker.compose.service':service})
        if 'model-proxy-1' in ' '.join(cmd):return json.dumps(self.stored)
        self.assertEqual(json.loads(kwargs['input']),dict(probe=self.probe,inputs=self.inputs))
        return json.dumps(dict(archived=True,execution_id=self.identifier,delivery_approval=False))

    def run_main(self):
        with patch.object(a,'PRIVATE',self.root),patch.object(a,'PROJECT','delivery-kit-port2'),\
                patch('sys.argv',['archive','--execution',self.identifier]),\
                patch.object(a.subprocess,'check_output',side_effect=self.command):
            a.main()

    def test_archive_requires_terminal_proxy_match_and_prints_no_inputs(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):self.run_main()
        self.assertTrue(json.loads(out.getvalue())['archived'])
        self.assertNotIn('files',out.getvalue())
        self.assertNotIn('/workspace',out.getvalue())
        self.assertTrue(any('mode=ro' in ' '.join(cmd) for cmd in self.commands))
        self.assertFalse(any('chat/completions' in ' '.join(cmd) for cmd in self.commands))

    def test_ledger_drift_is_rejected_before_publication(self):
        self.stored['status']='passed'
        with self.assertRaises(ValueError):self.run_main()
        self.assertFalse(any('execution-broker-1' in ' '.join(cmd) and cmd[1]=='exec' for cmd in self.commands))

    def test_changed_proxy_is_rejected(self):
        self.image='sha256:'+'d'*64
        with self.assertRaises(ValueError):self.run_main()

    def test_publicly_readable_archive_is_rejected_before_docker(self):
        (self.folder/('frozen-patch-'+self.identifier+'.json')).chmod(0o644)
        with self.assertRaises(ValueError):self.run_main()
        self.assertEqual(self.commands,[])
