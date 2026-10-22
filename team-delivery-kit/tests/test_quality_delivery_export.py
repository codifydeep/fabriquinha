"""Scoped stopped-helper export with synthetic authority, not native delivery."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import quality_delivery_export as export


class Effects:
    def __init__(self,source,descriptor):
        self.source=source;self.descriptor=descriptor;self.info=None;self.creates=0;self.copies=0;self.removes=0
        self.unknown_create=False;self.unknown_copy=False;self.unknown_remove=False
    def image(self,image):
        return dict(Id=image,Config=dict(User='10000:10000',Volumes=None,Env=[],
            Labels={'delivery-kit.component':'quality-green-job'}))
    def volume(self,name):return copy.deepcopy(self.descriptor['volume_identity'])
    def inspect(self,name):return copy.deepcopy(self.info)
    def create(self,name,payload):
        self.creates+=1
        self.info=dict(Id='c'*64,Name='/'+name,Image=payload['Image'],Config=copy.deepcopy(payload),
            HostConfig=copy.deepcopy(payload['HostConfig']),State=dict(Status='created',Running=False),
            Mounts=[dict(Type='volume',Name=payload['HostConfig']['Mounts'][0]['Source'],Destination='/delivery',RW=False)])
        if self.unknown_create:raise TimeoutError('unknown create acknowledgement')
        return self.info['Id']
    def copy(self,identity,target):
        self.copies+=1;shutil.copytree(self.source,target,dirs_exist_ok=True)
        if self.unknown_copy:raise TimeoutError('copy completed but acknowledgement lost')
    def remove(self,identity):
        self.removes+=1;self.info=None
        if self.unknown_remove:raise TimeoutError('unknown retirement acknowledgement')


class DeliveryExportTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name).resolve()
        self.source=self.root/'source';self.source.mkdir(mode=0o700)
        (self.source/'app.py').write_bytes(b'VALUE=1\n')
        facts={'app.py':dict(bytes=8,sha256=hashlib.sha256(b'VALUE=1\n').hexdigest())}
        raw=json.dumps(dict(files=facts),sort_keys=True,separators=(',',':')).encode()
        (self.source/'manifest.json').write_bytes(raw)
        self.private=self.root/'private';self.private.mkdir(mode=0o700)
        self.request='b0000000-0000-4000-8000-000000000001';self.task='b0000000-0000-4000-8000-000000000002'
        namespace='delivery-kit-test';owner=namespace+'-broker-v1';name=namespace+'-quality-delivery-'+self.task
        self.descriptor=dict(operation='quality_delivery_export_authority_v2',namespace=namespace,owner=owner,
            request_id=self.request,task_id=self.task,issue_id='b0000000-0000-4000-8000-000000000003',
            run_id='b0000000-0000-4000-8000-000000000004',manifest_sha256=hashlib.sha256(raw).hexdigest(),
            file_inventory=facts,capture_context_sha256='a'*64,capture_state_sha256='b'*64,
            plan_sha256='d'*64,frozen_sha256='e'*64,image='sha256:'+'f'*64,
            volume_identity=dict(Name=name,Driver='local',Scope='local',CreatedAt='2026-10-22T00:00:00Z',Labels={
                'delivery-kit.owner':owner,'delivery-kit.source-task':self.task,'delivery-kit.quality-run':'b0000000-0000-4000-8000-000000000004',
                'delivery-kit.lifecycle':'snapshot','com.docker.compose.project':namespace+'-tests',
                'com.docker.compose.volume':'quality-delivery-snapshot'}))
        self.fx=Effects(self.source,self.descriptor)

    def call(self):return export.export(self.descriptor,self.private,effects=self.fx)

    def test_export_is_scoped_readonly_stopped_grouped_and_retires_exact_helper(self):
        report=self.call()
        self.assertEqual(report['stage'],'exported');self.assertFalse(report['delivery_approval'])
        self.assertEqual((Path(report['directory'])/'app.py').read_bytes(),b'VALUE=1\n')
        self.assertEqual((self.fx.creates,self.fx.copies,self.fx.removes),(1,1,1))
        self.assertEqual(self.call(),report)
        self.assertEqual((self.fx.creates,self.fx.copies,self.fx.removes),(1,1,1))

    def test_unknown_create_ack_observes_original_helper_without_second_create(self):
        self.fx.unknown_create=True
        with self.assertRaises(export.Pending):self.call()
        self.assertEqual(self.call()['stage'],'exported')
        self.assertEqual(self.fx.creates,1)

    def test_lost_copy_ack_validates_existing_bytes_without_recopy(self):
        self.fx.unknown_copy=True
        with self.assertRaises(export.Pending):self.call()
        self.assertEqual(self.call()['stage'],'exported')
        self.assertEqual(self.fx.copies,1)

    def test_unknown_retirement_ack_observes_absence_without_second_remove(self):
        self.fx.unknown_remove=True
        with self.assertRaises(export.Pending):self.call()
        self.assertEqual(self.call()['stage'],'exported')
        self.assertEqual(self.fx.removes,1)

    def test_other_volume_family_or_recreated_identity_never_gets_a_helper(self):
        self.descriptor['volume_identity']['Name']='delivery-kit-test-snapshot-'+self.task
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.fx.creates,0)

    def test_partial_copy_never_repeats_transfer_or_declares_success(self):
        def incomplete(identity,target):
            self.fx.copies+=1;(target/'app.py').write_bytes(b'partial')
            raise TimeoutError('copy status unknown')
        self.fx.copy=incomplete
        with self.assertRaises(export.Pending):self.call()
        with self.assertRaises(export.Pending):self.call()
        self.assertEqual(self.fx.copies,1);self.assertEqual(self.fx.removes,0)

    def test_recreated_volume_after_unknown_create_blocks_without_copy(self):
        self.fx.unknown_create=True
        with self.assertRaises(export.Pending):self.call()
        changed=copy.deepcopy(self.descriptor['volume_identity']);changed['CreatedAt']='different incarnation'
        self.fx.volume=lambda name:changed
        with self.assertRaises(ValueError):self.call()
        self.assertEqual((self.fx.creates,self.fx.copies,self.fx.removes),(1,0,0))

    def test_running_or_foreign_helper_is_preserved_and_never_copied(self):
        self.fx.unknown_create=True
        with self.assertRaises(export.Pending):self.call()
        self.fx.info['State'].update(Status='running',Running=True)
        with self.assertRaises(ValueError):self.call()
        self.assertEqual((self.fx.copies,self.fx.removes),(0,0))

    def test_unknown_copy_expires_to_visible_block_without_replay(self):
        def incomplete(identity,target):
            self.fx.copies+=1
            raise TimeoutError('unknown transfer')
        self.fx.copy=incomplete
        with patch.object(export.time,'time',return_value=100):
            with self.assertRaises(export.Pending):self.call()
        with patch.object(export.time,'time',return_value=701):
            with self.assertRaises(ValueError):self.call()
        with self.assertRaises(ValueError):self.call()
        self.assertEqual((self.fx.creates,self.fx.copies,self.fx.removes),(1,1,0))
        state=json.loads((self.private/'quality-delivery-exports'/(self.request+'.json')).read_bytes())['state']
        self.assertEqual(state['stage'],'technical_blocked');self.assertFalse(state['automatic_retry'])

    def test_descriptor_tampering_cannot_adopt_existing_operation(self):
        self.fx.unknown_create=True
        with self.assertRaises(export.Pending):self.call()
        self.descriptor['capture_state_sha256']='0'*64
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.fx.creates,1)

    def test_world_readable_journal_cannot_be_resumed(self):
        self.call();path=self.private/'quality-delivery-exports'/(self.request+'.json')
        path.chmod(0o644)
        with self.assertRaises(ValueError):self.call()


if __name__=='__main__':unittest.main()
