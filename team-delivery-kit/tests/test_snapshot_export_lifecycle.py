import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock
from snapshot_export_lifecycle import export


class SnapshotExportLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.fx=Mock();self.fx.image.return_value='sha256:'+'a'*64
        self.fx.create.return_value=None;self.info=None
        def create(name,volume,image,labels):
            self.info={'Id':'b'*64,'Image':image,'Config':{'Labels':labels,'User':'10000:10000'},
                'State':{'Running':False,'Status':'created'},'HostConfig':{'NetworkMode':'none','ReadonlyRootfs':True,
                    'Tmpfs':{'/opt/data':'ro,size=1m,mode=0555'}},
                'Mounts':[{'Name':volume,'Destination':'/delivery','RW':False}]}
        self.fx.create.side_effect=create;self.fx.inspect.side_effect=lambda name:self.info
        self.fx.copy.return_value=None
    def invoke(self):return export('delivery-kit-port2-snapshot-source',self.root/'output',self.root,effects=self.fx)
    def test_exact_owned_stopped_id_is_archived_before_removal(self):
        result=self.invoke();self.assertEqual(result['stage'],'exported')
        self.fx.remove.assert_called_once_with('b'*64)
        self.assertEqual(self.fx.create.call_args.args[3]['com.docker.compose.project'],'delivery-kit-port2-tests')
        self.assertTrue(list((self.root/'snapshot-exports').glob('*.json')))
    def test_name_replaced_by_foreign_id_or_running_container_is_preserved(self):
        def copy(*args):self.info={**self.info,'Id':'c'*64}
        self.fx.copy.side_effect=copy
        with self.assertRaises(ValueError):self.invoke()
        self.fx.remove.assert_not_called()
    def test_lost_removal_ack_is_observed_without_second_delete(self):
        def remove(*args):self.info=None;raise TimeoutError()
        self.fx.remove.side_effect=remove
        self.assertEqual(self.invoke()['stage'],'exported');self.fx.remove.assert_called_once()
    def test_failed_copy_preserves_diagnostic_and_retires_exact_helper(self):
        self.fx.copy.side_effect=ValueError('failed copy')
        with self.assertRaises(ValueError):self.invoke()
        self.fx.remove.assert_called_once_with('b'*64)

    def test_implicit_image_volume_is_not_accepted_as_readonly_export(self):
        original=self.fx.create.side_effect
        def create(*args):
            original(*args);self.info['Mounts'].append({'Name':'anonymous','Destination':'/opt/data','RW':True})
        self.fx.create.side_effect=create
        with self.assertRaises(ValueError):self.invoke()
        self.fx.copy.assert_not_called();self.fx.remove.assert_not_called()
