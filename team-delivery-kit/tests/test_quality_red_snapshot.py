"""Snapshot intent recovery with synthetic authority; not native qualification."""
import copy
import json
import unittest
from unittest.mock import patch

from broker import quality_red_snapshot as producer,validation_job
import test_quality_red_capture as fixtures


class QualitySnapshotTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.QualityRedCaptureTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.b=f.b;self.task=f.task;self.volume=None;self.creates=0;self.unknown=False
        self.old_docker=self.b.docker
        def docker(method,path,payload=None):
            if path=='/volumes/'+self.f.vol:return copy.deepcopy(self.volume)
            if method=='POST' and path=='/volumes/create':
                self.creates+=1
                self.volume=dict(Name=payload['Name'],Driver='local',Scope='local',Options=None,
                    CreatedAt='2026-10-22T00:00:00Z',Labels=payload['Labels'])
                if self.unknown:raise TimeoutError('create acknowledgement unknown')
                return self.volume
            return self.old_docker(method,path)
        self.b.docker=docker
        with self.b.db() as con:
            self.copy_identity,self.copy_state=con.execute('SELECT identity,state FROM test_first_jobs').fetchone()
            con.execute('DELETE FROM test_first_jobs')
        p=patch.object(producer.maintenance,'current',return_value=None);self.addCleanup(p.stop);p.start()

    def copied(self,b,con,task,phase,payload):
        con.execute('INSERT INTO test_first_jobs VALUES(?,?,?)',(task+':copy',self.copy_identity,self.copy_state))
        con.commit();return json.loads(self.copy_state)['result']

    def call(self):return producer.prepare(self.b,self.task)

    def test_fixed_producer_records_intent_then_complete_snapshot_without_red_approval(self):
        with patch.object(producer.test_first_job,'run',side_effect=self.copied) as run:
            receipt=self.call()
        self.assertEqual(self.creates,1);self.assertEqual(receipt['stage'],'snapshot_copied')
        self.assertEqual(receipt['manifest_sha256'],'e'*64)
        self.assertFalse(receipt['delivery_approval']);self.assertFalse(receipt['execution_authorized'])
        self.assertEqual(run.call_args.args[3],'copy')
        with patch.object(producer.test_first_job,'run',side_effect=AssertionError('no replay')):
            self.assertEqual(self.call(),receipt)

    def test_unknown_volume_create_ack_is_observed_without_a_second_post(self):
        self.unknown=True
        with self.assertRaises(validation_job.Pending):self.call()
        with patch.object(producer.test_first_job,'run',side_effect=self.copied):self.call()
        self.assertEqual(self.creates,1)

    def test_existing_unregistered_volume_is_not_adopted_or_removed(self):
        self.volume=dict(Name=self.f.vol,Labels={'delivery-kit.owner':self.b.OWNER})
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.creates,0);self.assertIsNotNone(self.volume)

    def test_pause_prevents_volume_or_container_creation(self):
        with patch.object(producer.maintenance,'current',return_value={'stage':'sealed'}),\
                patch.object(producer.test_first_job,'run') as run:
            with self.assertRaises(validation_job.Pending):self.call()
            run.assert_not_called()
        self.assertEqual(self.creates,0)

    def test_pending_copy_uses_same_job_and_volume_after_restart(self):
        with patch.object(producer.test_first_job,'run',side_effect=TimeoutError('observe same job')) as run:
            for _ in range(2):
                with self.assertRaises(validation_job.Pending):self.call()
            self.assertEqual(run.call_args_list[0].args[2:],run.call_args_list[1].args[2:])
        self.assertEqual(self.creates,1)
        with patch.object(producer.test_first_job,'run',side_effect=self.copied):self.call()

    def test_recreated_volume_identity_cannot_replace_recorded_snapshot(self):
        with patch.object(producer.test_first_job,'run',side_effect=TimeoutError('observe same job')):
            with self.assertRaises(validation_job.Pending):self.call()
        self.volume['CreatedAt']='2026-10-22T01:00:00Z'
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.creates,1)

    def test_advance_connects_copy_to_red_capture_and_does_not_repeat_copy(self):
        with patch.object(producer.test_first_job,'run',side_effect=self.copied) as copy_job,\
                patch.object(producer.capture.validation_job,'run',side_effect=self.f.job):
            first=producer.advance(self.b,self.task)
            self.assertEqual(first['stage'],'awaiting_independent_test_review')
            self.assertEqual(producer.advance(self.b,self.task),first)
            copy_job.assert_called_once()


if __name__=='__main__':unittest.main()
