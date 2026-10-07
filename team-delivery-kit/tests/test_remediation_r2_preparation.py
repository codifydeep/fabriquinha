import copy
import json
import unittest
from unittest.mock import patch
import test_remediation_r2_issue as fixtures
from broker import remediation_r2_preparation as preparation


class RemediationR2PreparationTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.RemediationR2IssueTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.b=f.b;f.invoke();self.posts=[];self.resources={}
        self.b.IMAGE='sha256:'+'f'*64
        self.b.register_issue_base=lambda value:self.resources.update(registered=value)
        self.b.docker=self.docker
        self.b.docker_stdout=lambda ident:json.dumps(self.resources['proofs'][ident])
        self.resources['proofs']={}
        self.active=False

    def docker(self,method,path,body=None):
        if path.startswith('/images/'):
            return dict(Config=dict(Env=['PATH=/usr/bin']))
        if method=='GET' and path.startswith('/volumes/'):
            name=path.removeprefix('/volumes/')
            return self.resources.get(name) or (dict(Labels={'delivery-kit.owner':self.b.OWNER,
                'delivery-kit.test-first-task':'new-author-task'}) if name in (self.f.value['base']['volume'],'candidate') else None)
        if method=='POST' and path=='/volumes/create':
            self.posts.append(path);self.resources[body['Name']]=body;return body
        if path.startswith('/containers/') and path.endswith('/json'):
            return self.resources.get(path[len('/containers/'):-len('/json')])
        if path.startswith('/containers/create?name='):
            self.posts.append(path)
            name=path.split('=',1)[1];phase=body['Cmd'][-1]
            info=dict(Id=name,Image=body['Image'],Config={k:copy.deepcopy(body[k]) for k in ('User','Env','Labels','Cmd','Entrypoint')},
                HostConfig=body['HostConfig'],State=dict(Running=False,Status='created',ExitCode=0),
                Mounts=[dict(Type='volume',Name=m['Source'],Destination=m['Target'],RW=not m['ReadOnly']) for m in body['HostConfig']['Mounts']])
            info['Config']['Env'].insert(0,'PATH=/usr/bin')
            info['Config']['Labels']['com.docker.compose.project']=self.b.PREFIX+'-tests'
            self.resources[name]=info
            v=self.f.value;red=self.f.f.state['r1_gate']['red']['red']
            self.resources['proofs'][name]=dict(operation='remediation_original_base_copy_v2' if phase=='copy' else 'remediation_original_base_seed_v1',
                base_sha=v['base']['base_sha'],manifest_sha256=v['base']['manifest_sha256'],contract_sha256=v['contract_sha256'],
                baseline_test_sha256={'tests/test_old.py':'a'*64},baseline_unchanged=True,product_unchanged=True,
                red_executed=False,execution_authorized=False,release_homologated=False,
                previous_manifest_sha256=red['manifest_sha256'],seed_test_sha256=red['test_sha256'],snapshot_permissions_unchanged=True)
            return dict(Id=name)
        if method=='POST' and path.endswith('/start'):
            self.posts.append(path);self.resources[path[len('/containers/'):-len('/start')]]['State']['Status']='exited'
            return None
        raise AssertionError((method,path))

    def invoke(self):
        with patch.object(preparation.planning,'Effects',return_value=self.f.fx),patch.object(preparation.review,'verify'):
            return preparation.prepare(self.b,'source')

    def test_uses_original_base_and_approved_r1_not_old_failed_tests(self):
        with patch.object(preparation.review,'verify'):
            value,state,projection=preparation.inputs(self.b,'source',self.f.fx)
        self.assertEqual(projection['base'],value['base'])
        self.assertEqual(projection['previous_new_test_delivery']['volume'],'candidate')
        self.assertNotEqual(projection['previous_new_test_delivery']['volume'],value['previous_new_test_delivery']['volume'])
        self.assertEqual(state['steps']['R2']['issue_id'],self.f.ITEM_ID)

    def test_two_fixed_jobs_no_worker_grant_and_idempotent_qualification(self):
        self.assertEqual(self.invoke()['stage'],'seed_pending')
        receipt=self.invoke();self.assertEqual(receipt['stage'],'base_qualified')
        self.assertFalse(receipt['execution_authorized']);self.assertFalse(receipt['release_homologated'])
        self.assertEqual(self.invoke(),receipt)
        self.assertEqual(len([p for p in self.posts if '/create?name=' in p]),2)
        self.assertEqual(self.resources['registered']['manifest_sha256'],self.f.value['base']['manifest_sha256'])
        self.assertNotEqual(self.resources['registered']['manifest_sha256'],receipt['seed_proof']['previous_manifest_sha256'])

    def test_missing_r1_approval_does_not_touch_docker(self):
        bad=copy.deepcopy(self.f.f.state);bad.pop('r1_gate');self.f.f.f.f.save(state=bad)
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.posts,[])

    def test_cancelled_root_cannot_prepare_or_dispatch(self):
        self.f.parent['status']='cancelled'
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.posts,[])

    def test_active_r2_lease_prevents_any_base_write(self):
        with self.b.db() as con:
            con.execute('INSERT INTO leases VALUES (?,?)',('busy','running'))
            con.execute('INSERT INTO native_bindings VALUES (?,?,?,?,?)',('live',self.f.ITEM_ID,'scope','author','busy'))
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.posts,[])

    def test_lost_create_ack_observes_exact_job_and_never_reposts(self):
        original=self.b.docker
        def fail(method,path,body=None):
            if '/containers/create?' in path:
                original(method,path,body);raise TimeoutError()
            return original(method,path,body)
        self.b.docker=fail
        with self.assertRaises(TimeoutError):self.invoke()
        self.b.docker=original
        self.assertEqual(self.invoke()['stage'],'seed_pending')
        self.assertEqual(len([p for p in self.posts if '/create?name=' in p]),1)

    def test_absent_uncertain_handle_never_recreates(self):
        original=self.b.docker
        def fail(method,path,body=None):
            if '/containers/create?' in path:self.posts.append(path);raise TimeoutError()
            return original(method,path,body)
        self.b.docker=fail
        with self.assertRaises(TimeoutError):self.invoke()
        self.b.docker=original
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(len([p for p in self.posts if '/create?name=' in p]),1)

    def test_changed_seed_proof_cannot_qualify(self):
        self.invoke()
        original=self.b.docker_stdout
        self.b.docker_stdout=lambda ident:json.dumps({**json.loads(original(ident)),'snapshot_permissions_unchanged':False})
        with self.assertRaises(ValueError):self.invoke()
        self.assertNotIn('registered',self.resources)

    def test_revocation_after_first_job_stops_second_job(self):
        self.invoke()
        bad=copy.deepcopy(self.f.f.state);bad.pop('r1_gate');self.f.f.f.f.save(state=bad)
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(len([p for p in self.posts if '/create?name=' in p]),1)

    def test_watchdog_qualifies_base_without_execution_authority(self):
        with patch.object(preparation.planning,'Effects',return_value=self.f.fx),patch.object(preparation.review,'verify'):
            preparation.tick(self.b);preparation.tick(self.b);preparation.tick(self.b)
        with self.b.db() as con:
            state=json.loads(con.execute('SELECT state FROM remediation_r2_preparations').fetchone()[0])
        self.assertEqual(state['stage'],'base_qualified');self.assertFalse(state['execution_authorized'])
        self.assertEqual(len([p for p in self.posts if '/create?name=' in p]),2)

    def test_watchdog_blocks_semantic_failure_once_with_owner(self):
        self.f.parent['status']='cancelled'
        with patch.object(preparation.planning,'Effects',return_value=self.f.fx),patch.object(preparation.review,'verify'):
            preparation.tick(self.b);preparation.tick(self.b)
        with self.b.db() as con:
            state=json.loads(con.execute('SELECT state FROM remediation_executions').fetchone()[0])
        self.assertEqual(state['r2_issue_hold']['owner'],'lead');self.assertFalse(state['r2_issue_hold']['execution_authorized'])
        self.assertEqual(self.posts,[])

    def test_uncertain_job_deadline_is_visible_and_does_not_retry(self):
        self.invoke()
        with self.b.db() as con:
            row=json.loads(con.execute('SELECT state FROM remediation_r2_preparations').fetchone()[0])
            row['started_at']=0
            con.execute('UPDATE remediation_r2_preparations SET state=?',(json.dumps(row),))
        with patch.object(preparation.planning,'Effects',return_value=self.f.fx),patch.object(preparation.review,'verify'):
            preparation.tick(self.b);preparation.tick(self.b)
        with self.b.db() as con:
            row=json.loads(con.execute('SELECT state FROM remediation_r2_preparations').fetchone()[0])
        self.assertEqual(row['stage'],'blocked');self.assertEqual(row['category'],'r2_preparation_observation_deadline')
        self.assertEqual(len([p for p in self.posts if '/create?name=' in p]),1)
