import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import qualify_frozen_harness as runner
from generic_harness_calibration import digest


class FrozenHarnessQualificationTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name)
        (self.root/'calibration_frozen_harness_probe.py').write_text('fixed qualified source')
        self.source=dict(issue_id='11111111-1111-4111-8111-111111111111',author_task='author',candidate_volume='volume',
            test_files=['test.py'],prepared=dict(manifest_sha256='a'*64,test_sha256={'test.py':'b'*64},test_methods={'test.py':['test_a']}))
        self.context=dict(source=self.source,hold={'review':'hold'},owner='owner',prefix='delivery-kit-port2',image='sha256:'+'c'*64)
        self.identity=dict(source_sha256=digest(self.source),hold_sha256=digest(self.context['hold']),
            script_sha256=hashlib.sha256(b'fixed qualified source').hexdigest(),image=self.context['image'])
        self.folder=self.root/'.local-port2/probes'/('frozen-harness-'+digest(self.identity));self.folder.mkdir(parents=True)

    def command(self):
        labels=dict(**{'com.docker.compose.project':'delivery-kit-port2','com.docker.compose.service':'execution-broker'})
        volume=[dict(Labels={'delivery-kit.owner':'owner','delivery-kit.test-first-task':'author'})]
        with patch.object(runner,'ROOT',self.root),patch.object(runner,'docker',side_effect=[json.dumps(labels),json.dumps(self.context),json.dumps(volume)]),\
                patch('sys.argv',['qualification','--issue',self.source['issue_id']]),patch.object(runner.subprocess,'run') as launch,\
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):runner.main()
            launch.assert_not_called()

    def test_uncertain_existing_intent_is_observed_not_restarted(self):
        (self.folder/'intent.json').write_text('{}');self.command()

    def test_corrupt_cached_receipt_cannot_be_reported_as_a_qualified_result(self):
        (self.folder/'receipt.json').write_text(json.dumps(dict(identity={**self.identity,'image':'sha256:'+'d'*64})))
        self.command()
