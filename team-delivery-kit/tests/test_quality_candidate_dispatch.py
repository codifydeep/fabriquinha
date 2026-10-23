"""Durable scheduling fixtures; not a native autonomous-delivery qualification."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch
import quality_candidate_dispatch as dispatch


class Authority:
    namespace='delivery-kit-test'
    image='sha256:'+'a'*64
    def __init__(self):
        self.requests=[str(uuid.uuid4()) for _ in range(3)]
        self.paused=False
    def about(self):
        return dict(maintenance=self.paused,v2_enabled=True,implementation_enabled=True,queue_supported=True)
    def pending(self,after):
        return dict(stage='queued',requests=self.requests,next_after=0,rejected_rowids=[])
    def inspect(self,request):
        return dict(stage='pending',packet=dict(repository='owner/repository'))


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.root.chmod(0o700)
        self.authority=Authority();self.repositories={'owner/repository':str(self.root)}
        self.calls=[]
    def tick(self,advance=None):
        def pending(*args,**kwargs):
            self.calls.append(args[1]);raise dispatch.Pending('original operation remains unresolved')
        with patch.object(dispatch,'advance_remote',side_effect=advance or pending):
            return dispatch.tick(self.authority,self.repositories,str(self.root))
    def database(self):return next((self.root/'quality-candidate-dispatch').glob('*.sqlite'))

    def test_pending_card_cannot_monopolize_capacity_across_restart(self):
        first=self.tick();second=self.tick()
        a,b,c=self.authority.requests
        self.assertEqual(self.calls,[a,b,c,a])
        self.assertEqual([v['request_id'] for v in second['observed']],[c,a])
        self.assertEqual(first['model_calls'],0)
        self.assertFalse(second['delivery_approval'])

    def test_bound_card_is_not_replayed_and_context_cannot_silently_change(self):
        self.tick(lambda *args,**kwargs:dict(stage='awaiting_green',delivery_approval=False))
        self.calls=[];self.tick()
        self.assertEqual(self.calls,[self.authority.requests[2]])
        self.authority.image='sha256:'+'b'*64
        with self.assertRaises(ValueError):self.tick()

    def test_maintenance_records_health_without_listing_or_effects(self):
        self.authority.paused=True
        with patch.object(self.authority,'pending',side_effect=AssertionError('no queue probe')):
            result=self.tick()
        self.assertEqual(result['stage'],'maintenance');self.assertEqual(self.calls,[])
        with sqlite3.connect(self.database()) as con:
            self.assertEqual(json.loads(con.execute('SELECT health FROM meta').fetchone()[0]),result)

    def test_queue_outage_has_durable_deadline_and_no_effect_retry(self):
        with patch.object(self.authority,'pending',side_effect=dispatch.Pending('unavailable')):
            with patch.object(dispatch.time,'time',return_value=100):first=self.tick()
            with patch.object(dispatch.time,'time',return_value=1901):last=self.tick()
        self.assertEqual(first['stage'],'control_plane_pending')
        self.assertEqual(last['stage'],'technical_blocked')
        self.assertEqual(last['unavailable_since'],100)
        self.assertTrue(last['alert_due']);self.assertFalse(last['automatic_retry'])
        self.assertEqual(self.calls,[])

    def test_rejected_identity_is_visible_and_never_runs_effects(self):
        with patch.object(self.authority,'about',side_effect=ValueError('wrong image')):
            result=self.tick()
        self.assertEqual(result['owner'],'cto');self.assertEqual(result['stage'],'technical_blocked')
        self.assertEqual(self.calls,[])

    def test_expired_task_is_not_reexecuted(self):
        with patch.object(dispatch.time,'time',return_value=100):self.tick()
        before=len(self.calls)
        with patch.object(dispatch.time,'time',return_value=1901):self.tick();self.tick();self.tick()
        self.assertEqual(len(self.calls),before)

    def test_expired_card_can_observe_binding_after_lost_reply_without_new_effects(self):
        with patch.object(dispatch.time,'time',return_value=100):self.tick()
        def bound(request):
            return dict(stage='bound',identity=dict(packet=dict(repository='owner/repository')))
        with patch.object(self.authority,'inspect',side_effect=bound),patch.object(dispatch.time,'time',return_value=1901):
            result=self.tick(lambda *args,**kwargs:dict(stage='awaiting_green',delivery_approval=False))
        self.assertTrue(all(v['stage']=='bound' for v in result['observed']))

    def test_corrupt_local_card_does_not_starve_other_cards_on_rediscovery(self):
        self.tick();request=self.authority.requests[0]
        with sqlite3.connect(self.database()) as con:
            con.execute('UPDATE tasks SET state=? WHERE request_id=?',('{',request))
        result=self.tick()
        self.assertIn(request,result['local_integrity_rejections'])
        self.assertIn(self.authority.requests[2],[v['request_id'] for v in result['observed']])

    def test_malformed_queue_does_not_partially_enroll_tasks(self):
        self.authority.requests.append('invalid')
        result=self.tick()
        self.assertEqual(result['category'],'controller_queue_rejected')
        with sqlite3.connect(self.database()) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM tasks').fetchone()[0],0)

    def test_kernel_lock_prevents_concurrent_dispatch_not_a_pid_file(self):
        token=str(uuid.uuid5(uuid.NAMESPACE_URL,'quality-candidate-dispatch:'+self.authority.namespace))
        with dispatch.journal(str(self.root),token,family='quality-candidate-dispatch'):
            with self.assertRaises(dispatch.Pending):self.tick()
        self.tick()
        self.assertEqual(len(self.calls),2)

    def test_missing_installed_queue_adapter_is_not_an_empty_successful_queue(self):
        with patch.object(self.authority,'about',return_value=dict(maintenance=False,v2_enabled=True,implementation_enabled=True)):
            result=self.tick()
        self.assertEqual(result['stage'],'configuration_blocked')
        self.assertEqual(result['owner'],'cto');self.assertEqual(self.calls,[])

    def test_private_config_rejects_permissions_duplicates_nonfinite_and_hardlinks(self):
        path=self.root/'config.json'
        value=dict(namespace=self.authority.namespace,image=self.authority.image,private=str(self.root),repositories=self.repositories)
        path.write_text(json.dumps(value));path.chmod(0o600)
        self.assertEqual(dispatch.configuration(path),value)
        path.chmod(0o644)
        with self.assertRaises(ValueError):dispatch.configuration(path)
        path.chmod(0o600)
        for text in ('{"namespace":"one","namespace":"two"}','{"namespace":NaN}'):
            path.write_text(text)
            with self.assertRaises(ValueError):dispatch.configuration(path)
        path.write_text(json.dumps(value))
        (self.root/'alias.json').hardlink_to(path)
        with self.assertRaises(ValueError):dispatch.configuration(path)


if __name__=='__main__':unittest.main()
