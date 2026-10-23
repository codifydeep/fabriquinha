"""Fixed transport fixtures plus real Git/SQLite, not native qualification."""
import copy
import json
import unittest
import uuid
from unittest.mock import patch
import quality_candidate_authority as authority
import quality_delivery_candidate as bridge
import quality_candidate_dispatch as dispatch
from broker import quality_candidate_rpc as rpc
import test_quality_delivery_candidate as fixtures


class Effects:
    def __init__(self,b):
        self.b=b;self.calls=[];self.lost_record=False
        self.info=dict(Id='a'*64,Name='/'+b.PREFIX+'-execution-broker-1',Image='sha256:'+'b'*64,
            State=dict(Running=True),Config=dict(Labels={'com.docker.compose.project':b.PREFIX,
                'com.docker.compose.service':'execution-broker'}))
    def inspect(self,name):return copy.deepcopy(self.info)
    def execute(self,identity,value):
        self.calls.append(copy.deepcopy(value));result=rpc.invoke_json(self.b,json.dumps(value))
        if self.lost_record and value['operation']=='record':raise TimeoutError('record succeeded; reply lost')
        return result


class CandidateAuthorityTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.DeliveryCandidateTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.b=f.b;self.b.OWNER=self.b.PREFIX+'-broker-v1'
        self.fx=Effects(self.b);self.a=authority.Authority(self.b.PREFIX,self.fx.info['Image'],effects=self.fx)

    def call(self):return bridge.advance_remote(self.a,self.f.f.request,self.f.f.f.repo,
        self.f.f.private,effects=self.f.fx)

    def test_fixed_local_rpc_binds_real_git_without_model_or_public_endpoint(self):
        self.assertEqual(self.a.about()['stage'],'available')
        result=self.call();self.assertEqual(result['stage'],'awaiting_green');self.assertFalse(result['delivery_approval'])
        self.assertEqual([v['operation'] for v in self.fx.calls],['about','inspect','record'])
        self.assertEqual(self.call(),result)
        self.assertEqual((self.f.fx.creates,self.f.fx.copies,self.f.fx.removes),(1,1,1))

    def test_lost_record_reply_reads_durable_binding_before_repeating_any_local_effect(self):
        self.fx.lost_record=True
        with self.assertRaises(authority.Pending):self.call()
        with patch.object(bridge.exporter,'export',side_effect=AssertionError('no replay export')),\
                patch.object(bridge.candidate,'materialize',side_effect=AssertionError('no replay Git')):
            self.assertEqual(self.call()['stage'],'awaiting_green')
        self.assertEqual(sum(v['operation']=='record' for v in self.fx.calls),1)

    def test_wrong_image_service_or_project_blocks_before_exec_or_local_effects(self):
        original=copy.deepcopy(self.fx.info)
        for field in ('image','project','service'):
            self.fx.info=copy.deepcopy(original)
            if field=='image':self.fx.info['Image']='sha256:'+'c'*64
            else:self.fx.info['Config']['Labels']['com.docker.compose.'+field]='other'
            with self.subTest(field=field),self.assertRaises(ValueError):self.call()
        self.assertEqual(self.fx.calls,[]);self.assertEqual(self.f.fx.creates,0)

    def test_controller_replacement_mid_reply_cannot_be_accepted(self):
        original=self.fx.execute
        def replace(*args):
            result=original(*args);self.fx.info['Id']='d'*64;return result
        self.fx.execute=replace
        with self.assertRaises(ValueError):self.a.about()

    def test_maintenance_never_exports_or_creates_git_objects(self):
        with self.b.db() as con:
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',('pause','sealed',json.dumps(dict(stage='sealed'))))
        with self.assertRaises(authority.Pending):self.call()
        self.assertEqual(self.f.fx.creates,0)

    def test_unknown_commands_extra_fields_duplicate_keys_and_nonfinite_values_fail_closed(self):
        for value in (dict(operation='shell',namespace=self.b.PREFIX),
                dict(operation='about',namespace=self.b.PREFIX,command='terminal'),
                dict(operation='about',namespace='delivery-kit-other')):
            with self.subTest(value=value),self.assertRaises(ValueError):rpc.invoke(self.b,value)
        for raw in ('{"operation":"about","operation":"record"}',
                '{"operation":"about","namespace":NaN}',' '*262145):
            with self.assertRaises(ValueError):rpc.invoke_json(self.b,raw)
        with self.assertRaises(ValueError):self.a.call('terminal')

    def test_disabled_v2_allows_only_about_not_candidate_registration(self):
        self.b.QUALITY_V2_ENABLED=False
        self.assertFalse(self.a.about()['v2_enabled'])
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.f.fx.creates,0)

    def test_pending_queue_pages_validate_capture_hashes_and_isolate_corruption(self):
        requests=[str(uuid.uuid4()) for _ in range(130)]
        with self.b.db() as con:
            con.execute('DELETE FROM quality_delivery_captures')
            for request in requests:
                context=copy.deepcopy(self.f.context);context['admission']['request_id']=request
                state=copy.deepcopy(self.f.state)
                con.execute('INSERT INTO quality_delivery_captures VALUES(?,?,?,?,?)',(request,
                    json.dumps(context),json.dumps(state),rpc.binding.quality.digest(context),rpc.binding.quality.digest(state)))
            con.execute('UPDATE quality_delivery_captures SET state=? WHERE request_id=?',('{',requests[0]))
        first=self.a.pending()
        self.assertEqual(first['requests'],requests[1:128]);self.assertEqual(len(first['rejected_rowids']),1)
        self.assertGreater(first['next_after'],0)
        second=self.a.pending(first['next_after'])
        self.assertEqual(second['requests'],requests[128:]);self.assertEqual(second['next_after'],0)
        self.assertEqual(self.f.fx.creates,0)

    def test_pending_queue_excludes_already_bound_deliveries_and_rejects_bad_cursor(self):
        self.assertEqual(self.a.pending()['requests'],[self.f.f.request])
        self.call()
        self.assertEqual(self.a.pending()['requests'],[])
        for cursor in (-1,True,'0',2**63):
            with self.subTest(cursor=cursor),self.assertRaises(ValueError):self.a.pending(cursor)

    def test_dispatcher_resumes_real_git_after_lost_record_ack_without_new_effects(self):
        self.fx.lost_record=True
        repositories={'codifydeep/descartavel2':str(self.f.f.f.repo)}
        before=self.f.f.f.git('rev-parse','HEAD')
        first=dispatch.tick(self.a,repositories,self.f.f.private,effects=self.f.fx)
        self.assertEqual(first['observed'][0]['stage'],'pending')
        with patch.object(bridge.exporter,'export',side_effect=AssertionError('no replay export')),\
                patch.object(bridge.candidate,'materialize',side_effect=AssertionError('no replay Git')):
            last=dispatch.tick(self.a,repositories,self.f.f.private,effects=self.f.fx)
        self.assertEqual(last['observed'][0]['stage'],'bound')
        self.assertEqual((self.f.fx.creates,self.f.fx.copies,self.f.fx.removes),(1,1,1))
        self.assertEqual(self.f.f.f.git('rev-parse','HEAD'),before)
        self.assertEqual(sum(v['operation']=='record' for v in self.fx.calls),1)


if __name__=='__main__':unittest.main()
