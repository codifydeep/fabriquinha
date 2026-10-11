import copy
import hashlib
import json
import sqlite3
import unittest
from types import SimpleNamespace

import test_generic_calibration_proposal as samples
from broker import generic_calibration_proposal as producer
from broker import generic_calibration_materialization as jobs
from generic_calibration_bundle_writer import expected_files
from generic_harness_calibration import digest


class MaterializationJobTests(unittest.TestCase):
    def job(self,uncertain=None):
        fixture=samples.ProposalTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        record=producer.bundle(fixture.body,fixture.value,fixture.route,fixture.prepared)
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        producer.store(con,'issue','author-task',record);con.commit()
        b=SimpleNamespace(PREFIX='delivery-kit-port2',OWNER='owned',
            GENERIC_CALIBRATION_WRITER_IMAGE='sha256:'+'d'*64)
        volumes={};container={};effects=[]
        def docker(method,path,body=None):
            if path.startswith('/images/'):
                return dict(Id=b.GENERIC_CALIBRATION_WRITER_IMAGE,Config=dict(Env=['PATH=/usr/bin']))
            if path.startswith('/volumes/') and method=='GET':return copy.deepcopy(volumes.get(path.split('/')[-1]))
            if path=='/volumes/create':
                effects.append((method,path));volumes[body['Name']]=copy.deepcopy(body)
                if uncertain=='volume':raise TimeoutError('lost volume create acknowledgment')
                return body
            if method=='GET':return copy.deepcopy(container) if container else None
            effects.append((method,path))
            if '/create?' in path:
                container.update(Id='container',Image=b.GENERIC_CALIBRATION_WRITER_IMAGE,
                    Config={k:copy.deepcopy(v) for k,v in body.items() if k!='HostConfig'},
                    Mounts=[dict(Type='volume',Name=m['Source'],Destination=m['Target'],RW=not m['ReadOnly'])
                        for m in body['HostConfig']['Mounts']],
                    HostConfig=copy.deepcopy(body['HostConfig']),State=dict(Status='created',Running=False,ExitCode=0))
                if uncertain=='create':raise TimeoutError('lost container create acknowledgment')
                return dict(Id='container')
            container['State']=dict(Status='exited',Running=False,ExitCode=0)
            if uncertain=='start':raise TimeoutError('lost start acknowledgment')
        files=expected_files(record,digest(record))
        receipt=dict(operation='generic_calibration_bundle_materialized_v1',bundle_sha256=digest(record),
            policy_sha256=record['policy_sha256'],controls_manifest_sha256=record['policy']['controls_manifest_sha256'],
            policy_manifest_sha256=hashlib.sha256(files['policy']['manifest.json'].encode()).hexdigest(),
            tests_executed=False,execution_authorized=False,delivery_approval=False)
        b.docker=docker;b.docker_stdout=lambda *a,**k:json.dumps(receipt)
        return b,con,record,effects,volumes,container

    def test_volume_create_lost_ack_is_observed_not_repeated(self):
        b,con,record,effects,volumes,container=self.job('volume')
        # Both volume creations can lose acknowledgment, each exactly once.
        for now in (1,2):
            with self.assertRaises(TimeoutError):jobs.run(b,con,'issue','author-task',now=now)
        result=jobs.run(b,con,'issue','author-task',now=3)
        self.assertFalse(result['receipt']['tests_executed'])
        self.assertEqual(sum(path=='/volumes/create' for method,path in effects),2)

    def test_container_create_and_start_uncertainty_never_duplicate_execution(self):
        for phase in ('create','start'):
            with self.subTest(phase=phase):
                b,con,record,effects,volumes,container=self.job(phase)
                with self.assertRaises(TimeoutError):jobs.run(b,con,'issue','author-task',now=1)
                result=jobs.run(b,con,'issue','author-task',now=2)
                self.assertFalse(result['receipt']['delivery_approval'])
                self.assertEqual(sum('/create?' in p for m,p in effects),1)
                self.assertEqual(sum(p.endswith('/start') for m,p in effects),1)
                before=len(effects);self.assertEqual(jobs.run(b,con,'issue','author-task',now=3),result)
                self.assertEqual(len(effects),before)

    def test_missing_handle_and_bad_receipt_are_not_repaired_by_reexecution(self):
        b,con,record,effects,volumes,container=self.job('create')
        with self.assertRaises(TimeoutError):jobs.run(b,con,'issue','author-task',now=1)
        container.clear()
        with self.assertRaises(TimeoutError):jobs.run(b,con,'issue','author-task',now=2)
        self.assertEqual(sum('/create?' in p for m,p in effects),1)
        b,con,record,effects,volumes,container=self.job()
        b.docker_stdout=lambda *a,**k:'{"delivery_approval":true}'
        with self.assertRaises(ValueError):jobs.run(b,con,'issue','author-task',now=1)
        before=len(effects)
        with self.assertRaises(ValueError):jobs.run(b,con,'issue','author-task',now=2)
        self.assertEqual(len(effects),before)

    def test_only_new_controller_targets_are_writable_and_payload_is_fixed(self):
        b,con,record,effects,volumes,container=self.job()
        jobs.run(b,con,'issue','author-task',now=1)
        mounts=container['HostConfig']['Mounts']
        self.assertEqual({m['Target'] for m in mounts},{'/controls','/policy'})
        self.assertTrue(all(m['ReadOnly'] is False for m in mounts))
        self.assertEqual(container['HostConfig']['NetworkMode'],'none')
        self.assertTrue(container['HostConfig']['ReadonlyRootfs'])
        self.assertEqual(container['Config']['Cmd'][0],'/generic_calibration_bundle_writer.py')
        self.assertEqual(container['Config']['Labels']['com.docker.compose.project'],'delivery-kit-port2-tests')

    def test_proposal_must_be_persisted_before_any_effect(self):
        b,con,record,effects,volumes,container=self.job()
        con.execute('DELETE FROM generic_calibration_proposals')
        with self.assertRaises(ValueError):jobs.run(b,con,'issue','author-task',now=1)
        self.assertFalse(effects)

    def test_foreign_volume_ownership_is_rejected_without_overwrite(self):
        b,con,record,effects,volumes,container=self.job('volume')
        with self.assertRaises(TimeoutError):jobs.run(b,con,'issue','author-task',now=1)
        next(iter(volumes.values()))['Labels']['delivery-kit.owner']='foreign'
        before=len(effects)
        with self.assertRaises(ValueError):jobs.run(b,con,'issue','author-task',now=2)
        self.assertEqual(len(effects),before)

    def test_omitted_legacy_flag_does_not_allow_bridge_network_or_extra_mounts(self):
        for mutate in (lambda c:c['HostConfig'].update(NetworkMode='bridge'),
                       lambda c:c['HostConfig'].update(Privileged=True),
                       lambda c:c['Mounts'].append(dict(Type='bind',Destination='/socket',RW=True))):
            b,con,record,effects,volumes,container=self.job('create')
            with self.assertRaises(TimeoutError):jobs.run(b,con,'issue','author-task',now=1)
            self.assertNotIn('NetworkDisabled',container['Config'])
            mutate(container)
            with self.assertRaises(ValueError):jobs.run(b,con,'issue','author-task',now=2)
            self.assertFalse(any(path.endswith('/start') for method,path in effects))

    def test_inherited_image_volumes_or_credentials_are_rejected_before_creation(self):
        for config in (dict(Env=['PATH=/usr/bin'],Volumes={'/opt/data':{}}),
                       dict(Env=['PATH=/usr/bin','OPENROUTER_API_KEY=not-a-real-key'])):
            b,con,record,effects,volumes,container=self.job()
            original=b.docker
            def docker(method,path,body=None):
                if path.startswith('/images/'):return dict(Id=b.GENERIC_CALIBRATION_WRITER_IMAGE,Config=config)
                return original(method,path,body)
            b.docker=docker
            with self.assertRaises(ValueError):jobs.run(b,con,'issue','author-task',now=1)
            self.assertFalse(effects)
