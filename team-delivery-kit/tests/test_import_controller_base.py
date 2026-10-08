import json
import unittest
from unittest.mock import patch
from import_controller_base import main


class ControllerBaseImportTests(unittest.TestCase):
    def setUp(self):
        self.config=dict(Env=['PATH=/usr/bin'],User='root',WorkingDir='/eval-state',Entrypoint=['python','/broker.py'],Cmd=None)
        self.source=dict(Id='sha256:source',Config=self.config)
        self.container=dict(Image='sha256:source',State=dict(Status='created',StartedAt='0001-01-01T00:00:00Z'),
            Config=dict(Labels={'com.docker.compose.project':'delivery-kit-test-tests',
                                'delivery-kit.owner':'delivery-kit-test-broker-v1'}))
        self.argv=['import_controller_base','--source-image','source','--container','owned','--archive','/private/tmp/export',
                   '--tag','delivery-kit-execution-broker:flat','--namespace','delivery-kit-test']
    def call(self,imported=None):
        with (patch('sys.argv',self.argv),patch('import_controller_base.inspect',side_effect=[self.source,self.container,
                imported or dict(Id='sha256:flat',Config=self.config)]),
              patch('import_controller_base.os.path.islink',return_value=False),
              patch('import_controller_base.os.path.isfile',return_value=True),
              patch('import_controller_base.os.chmod'),patch('import_controller_base.subprocess.run') as run):
            main()
            return run
    def test_import_preserves_metadata_and_never_removes_source(self):
        run=self.call();command=run.call_args.args[0]
        self.assertEqual(command[:2],['docker','import'])
        self.assertNotIn('rm',command)
    def test_started_foreign_or_credential_bearing_source_is_rejected(self):
        self.container['State']['Status']='running'
        with self.assertRaises(ValueError):self.call()
        self.container['State']['Status']='created';self.config['Env']=['API_KEY=private']
        with self.assertRaises(ValueError):self.call()
    def test_metadata_drift_blocks_qualification(self):
        with self.assertRaises(ValueError):self.call(dict(Id='flat',Config={**self.config,'User':'different'}))
