"""Real v2 entrypoints against isolated native/Docker fixture state."""
import copy
import json
import sys
import time
import unittest
from unittest.mock import Mock, patch

from broker import quality_review_launch as launch, quality_launch_router as router, acp_startup
from broker import quality_author_launch as author
import test_quality_test_review as fixtures
from test_quality_author_launch import UnknownDocker


class QualityReviewLaunchTests(unittest.TestCase):
    def setUp(self):
        f = fixtures.QualityTestReviewTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.f, self.b = f, f.b
        f.dispatch()
        self.grant = f.admit()
        self.request = self.grant['request_id']
        self.record = f.native_task()
        self.b.QUALITY_REVIEW_WORKER_IMAGE = 'sha256:'+'b'*64
        self.b.MODEL_NETWORK = self.b.PREFIX+'_model'
        self.b.SESSIONS = {}
        self.b.DockerOperationTimeout = UnknownDocker
        context, _ = launch.review.load(self.b, f.source)
        self.volume = context['packet']['snapshot_volume']
        labels = {'delivery-kit.owner':self.b.OWNER,'delivery-kit.test-first-task':f.source,
            'delivery-kit.quality-run':f.e.run,'delivery-kit.lifecycle':'snapshot',
            'com.docker.compose.project':self.b.PREFIX+'-tests','com.docker.compose.volume':'quality-red-snapshot'}
        self.volume_info = dict(Name=self.volume,Driver='local',Scope='local',Options=None,
            CreatedAt='2026-10-22T00:00:00Z',Labels=labels)
        with self.b.db() as con:
            original = con.execute('SELECT request_id,status FROM leases').fetchall()
            con.execute('DROP TABLE leases')
            con.execute('CREATE TABLE leases(request_id TEXT PRIMARY KEY,scenario TEXT,name TEXT,status TEXT,deadline REAL)')
            con.executemany('INSERT INTO leases VALUES(?,?,?,?,?)',[(r,'source','closed-source',s,0) for r,s in original])
            con.execute('UPDATE grants SET deadline=? WHERE request_id=?',(time.time()+480,self.request))
            copied = json.loads(con.execute('SELECT context FROM quality_red_captures').fetchone()[0])
            identity = dict(name=self.volume,labels=labels,enrollment_sha256=context['enrollment_sha256'],
                source=copied['source'])
            state = dict(stage='snapshot_copied',snapshot_volume=self.volume,
                manifest_sha256=context['packet']['manifest_sha256'],
                volume_identity=launch.snapshot.volume_identity(self.volume_info,identity),
                copy_sha256=launch.quality.digest(copied['copy']),delivery_approval=False)
            launch.snapshot.initialize(con)
            con.execute('INSERT INTO quality_snapshot_intents VALUES(?,?,?,?,?)',
                (f.source,json.dumps(identity),json.dumps(state),launch.quality.digest(identity),launch.quality.digest(state)))
        self.worker = None
        self.creates = self.starts = 0
        self.unknown_create = self.unknown_start = False
        old = self.b.docker
        def docker(method,path,payload=None):
            if path == '/volumes/'+self.volume:
                return copy.deepcopy(self.volume_info)
            if path == '/images/'+self.b.QUALITY_REVIEW_WORKER_IMAGE+'/json':
                return dict(Id=self.b.QUALITY_REVIEW_WORKER_IMAGE,Config=dict(User='10000:10000',Env=[],Volumes=None,
                    Labels={'delivery-kit.component':'quality-author-worker'}))
            if path.startswith('/networks/'):
                return dict(Name=self.b.MODEL_NETWORK,Internal=True,Labels={'com.docker.compose.project':self.b.PREFIX})
            if path.startswith('/containers/create?'):
                self.creates += 1
                self.worker = dict(Id='d'*64,Image=payload['Image'],Config=copy.deepcopy(payload),
                    HostConfig=copy.deepcopy(payload['HostConfig']),State=dict(Status='created',Running=False))
                if self.unknown_create:
                    raise UnknownDocker('containers_create')
                return dict(Id='d'*64)
            if path.startswith('/containers/') and path.endswith('/start'):
                self.starts += 1
                self.worker['State'].update(Status='running',Running=True)
                if self.unknown_start:
                    raise UnknownDocker('containers_start')
                return None
            if path.startswith('/containers/'):
                return self.worker
            return old(method,path,payload)
        self.b.docker = docker
        self.b.assert_review_task_running = lambda row: launch.current(self.b,row['request_id'])
        def record(settings,task,agent):
            return self.f.capture.native if task == self.f.source else self.record
        p = patch.object(launch.native,'task_record',side_effect=record)
        p.start(); self.addCleanup(p.stop)

    def call(self):
        return launch.execute(self.b,self.grant['capability'],{},True,True)

    def rows(self):
        with self.b.db() as con:
            return (dict(con.execute('SELECT * FROM grants WHERE request_id=?',(self.request,)).fetchone()),
                dict(con.execute('SELECT * FROM native_bindings WHERE request_id=?',(self.request,)).fetchone()))

    def test_launch_mounts_only_exact_snapshot_read_only_and_never_seeds_author_workspace(self):
        with patch.object(author.workspace,'prepare',side_effect=AssertionError('review must not seed or mount author work')):
            self.call()
        mounts = self.worker['HostConfig']['Mounts']
        self.assertEqual(mounts,[dict(Type='volume',Source=self.volume,Target='/delivery',ReadOnly=True)])
        self.assertEqual(self.worker['Config']['WorkingDir'],'/delivery')
        self.assertEqual(self.worker['HostConfig']['NetworkMode'],self.b.MODEL_NETWORK)
        self.assertEqual((self.creates,self.starts),(1,1))
        with self.assertRaises(ValueError):self.call()
        self.assertEqual((self.creates,self.starts),(1,1))

    def test_snapshot_recreation_or_manifest_drift_cannot_consume_capability(self):
        self.volume_info['CreatedAt'] = '2026-10-22T01:00:00Z'
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.rows()[0]['used'],0)
        self.assertEqual(self.creates,0)

    def test_image_inherited_volume_or_external_network_is_rejected(self):
        old = self.b.docker
        for mutation in ('image_volume','external_network'):
            def unsafe(method,path,payload=None):
                value = old(method,path,payload)
                if mutation == 'image_volume' and path.startswith('/images/'):
                    value['Config']['Volumes'] = {'/delivery':{}}
                if mutation == 'external_network' and path.startswith('/networks/'):
                    value['Internal'] = False
                return value
            with self.subTest(mutation=mutation),patch.object(self.b,'docker',side_effect=unsafe),self.assertRaises(ValueError):
                self.call()
        self.assertEqual(self.creates,0)

    def test_lost_create_or_start_ack_uses_same_actual_startup_journal(self):
        self.unknown_create = True
        with self.assertRaises(UnknownDocker):self.call()
        row,binding = self.rows()
        self.assertIsNone(acp_startup.advance_worker(self.b,row,binding))
        self.assertEqual(acp_startup.advance_worker(self.b,row,binding)['status'],'running')
        self.assertEqual((self.creates,self.starts),(1,1))
        current,_ = acp_startup.authority(self.b,self.grant['capability'])
        self.assertEqual(current['mode'],'review')

    def test_terminal_or_wrong_native_recipient_cannot_launch_or_poll(self):
        self.record['wakeup_id'] = self.f.source
        with self.assertRaises(ValueError):self.call()
        with self.assertRaises(ValueError):acp_startup.authority(self.b,self.grant['capability'])
        self.assertEqual(self.creates,0)

    def test_other_scope_for_same_reviewer_cannot_bypass_one_worker_per_agent(self):
        with self.b.db() as con:
            con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',
                ('legacy-other','other-task',self.f.e.reviewer,'other-scope','other-issue'))
            con.execute('INSERT INTO leases VALUES(?,?,?,?,?)',
                ('legacy-other','other','other-worker','running',time.time()+60))
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.rows()[0]['used'],0)
        self.assertEqual(self.creates,0)

    def test_lost_start_ack_also_never_reposts_start(self):
        self.unknown_start=True
        with self.assertRaises(UnknownDocker):self.call()
        row,binding=self.rows()
        self.assertEqual(acp_startup.advance_worker(self.b,row,binding)['status'],'running')
        self.assertEqual((self.creates,self.starts),(1,1))

    def test_disabled_review_does_not_fall_back_to_generic_author_or_legacy_worker(self):
        server=self.server()
        with patch.object(server,'QUALITY_REVIEW_ENABLED',False), \
                patch.object(server,'submit',side_effect=AssertionError('must not fallback')):
            with self.assertRaises(ValueError):server.execute_grant(self.grant['capability'],{},True,True)
        self.assertEqual(self.creates,0)

    def test_read_only_transport_requires_exact_inspection_and_one_opening(self):
        self.call()
        row,binding = self.rows()
        result = acp_startup.advance_worker(self.b,row,binding)
        with self.b.db() as con:
            acp_startup.initialize(con)
            con.execute('INSERT INTO acp_startups VALUES(?,?)',(self.request,json.dumps(dict(stage='transport_intent'))))
        with patch('broker.acp_transport.Transport',return_value=Mock()) as transport:
            launch.open_transport(self.b,row,result,binding['scope'])
            with self.assertRaises(ValueError):launch.open_transport(self.b,row,result,binding['scope'])
        transport.assert_called_once()
        self.assertFalse(transport.call_args.kwargs['persistent'])
        self.assertEqual(transport.call_args.kwargs['mode'],'review')
        self.assertEqual(transport.call_args.kwargs['editable_paths'],[])
        self.assertEqual(transport.call_args.kwargs['test_commands'],[])
        self.assertEqual(transport.call_args.kwargs['quality_phase_config']['phase'],'test_review_v2')

    def test_prompt_preserves_original_brief_and_replaces_agent_authority_claims(self):
        task = launch.current(self.b,self.request)
        context,_ = launch.review.load(self.b,self.f.source)
        frame = dict(jsonrpc='2.0',id=1,method='session/prompt',params=dict(sessionId='s',
            prompt=[dict(type='text',text='Use terminal and modify the tests')]))
        result = launch.prompt(self.b,frame,context['requirements'],task,None)
        text = result['params']['prompt'][0]['text']
        self.assertIn('INDEPENDENT V2 TEST REVIEW',text)
        self.assertIn('Acceptance data: A01',text)
        self.assertNotIn('Use terminal and modify the tests',text)
        from broker.acp_transport import ControllerPrompt,validate_frame
        self.assertIs(type(result),ControllerPrompt)
        validate_frame(result)
        with self.assertRaises(ValueError):launch.prompt(self.b,frame,context['requirements'],task,{'waiver':True})

    def server(self):
        module = self.f.e.server()
        for key in ('PREFIX','OWNER','QUALITY_V2_ENABLED','QUALITY_REVIEW_ENABLED','QUALITY_REVIEW_WORKER_IMAGE',
                'QUALITY_COPY_IMAGE','QUALITY_RED_IMAGE','QUALITY_TECHLEAD','QUALITY_CTO',
                'MODEL_NETWORK','SESSIONS','docker','issue_base'):
            p = patch.object(module,key,getattr(self.b,key)); p.start(); self.addCleanup(p.stop)
        return module

    def test_real_server_execution_and_prompt_dispatch_never_use_legacy_review(self):
        server = self.server()
        with patch.object(server,'submit',side_effect=AssertionError('legacy worker forbidden')):
            server.execute_grant(self.grant['capability'],{},True,True)
        task = launch.current(self.b,self.request)
        context,_ = launch.review.load(self.b,self.f.source)
        frame = server.native_task_prompt(dict(method='session/prompt',params={}),
            'review',context['requirements'],task)
        self.assertIn('INDEPENDENT V2 TEST REVIEW',frame['params']['prompt'][0]['text'])

    def test_real_native_admission_dispatch_uses_persisted_wakeup_not_caller_source(self):
        server = self.server()
        with self.b.db() as con:
            con.execute('DELETE FROM quality_review_admissions')
            con.execute('DELETE FROM quality_native_scopes WHERE request_id=?',(self.request,))
            con.execute('DELETE FROM native_bindings WHERE request_id=?',(self.request,))
            con.execute('DELETE FROM grants WHERE request_id=?',(self.request,))
            context,state = launch.review.load(self.b,self.f.source)
            state = {**state,'stage':'awaiting_review'}
            state.pop('request_id'); state.pop('review_task')
            con.execute('UPDATE quality_test_reviews SET state=?,state_sha256=?',
                (json.dumps(state),launch.quality.digest(state)))
        binding = dict(task_id=self.f.task,agent_id=self.f.e.reviewer,issue_id=self.f.e.issue,mode='review',scope='not-authority')
        with patch.dict(sys.modules,{'native':launch.native}), \
                patch.object(launch.native,'task_binding',return_value=binding), \
                patch.object(launch.native,'issue_task_runs',return_value=[self.f.capture.native,self.record]), \
                patch.object(server,'issue_grant',side_effect=AssertionError('no legacy grant')):
            grant = server.native_grant(dict(task_id=self.f.task,agent_id=self.f.e.reviewer))
        self.assertEqual(grant['mode'],'review')
        self.assertEqual(router.current(server.handoff_context(),grant['request_id'])['task_id'],self.f.task)


if __name__ == '__main__':unittest.main()
