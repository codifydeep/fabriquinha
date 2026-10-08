import hashlib
import json
import unittest
from unittest.mock import Mock,patch
import test_product_scope_execution as fixtures
from broker import product_scope_bootstrap as bootstrap


class ProductScopeBootstrapTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.ProductScopeExecutionTests();f.setUp();self.addCleanup(f.doCleanups)
        self.b,self.fx,self.context,self.original=f.b,f.fx,f.context,f.original
        self.b.PREFIX='delivery-kit-test';self.b.OWNER='owner';self.b.OFFLINE_IMAGE='validator'
        self.base=dict(volume='base-volume',base_sha='a'*40,manifest_sha256='b'*64)
        self.b.issue_base=Mock(return_value=self.base)
        failure=dict(category='executed_test_failure',source_task='source',volume='snapshot',
                     output_sha256=self.context['failure_output_sha256'],diagnostic_source_hashes=self.context['eligible_code_sha256'])
        route=dict(enabled=True,test_first=True,author='backend',cto='cto',techlead='lead',
                   contract_sha256=self.context['contract_sha256'])
        facts=dict(manifest_sha256=self.context['snapshot_sha256'],baseline_tests_intact=True,
                   new_test_sha256=self.context['frozen_test_sha256'],diagnostic_file_sha256=self.context['eligible_code_sha256'])
        output=json.dumps(facts)
        identity=dict(task='source',kind='structure',payload=dict(Image='validator',HostConfig=dict(
            Mounts=[dict(Source='snapshot',ReadOnly=True)])))
        job=dict(stage='complete',result=dict(exit_code=0,output=output,output_sha256=hashlib.sha256(output.encode()).hexdigest()))
        red=dict(task_id='original-red',red=dict(test_sha256=self.context['frozen_test_sha256'],
                    manifest_sha256='1'*64,base_manifest_sha256=self.base['manifest_sha256']))
        review=dict(status='approved',source_task='original-red',review_task='independent',read_contract='complete-lines-v2',
                    manifest_sha256='1'*64,decision=dict(action='approve_test_revision',optional_files=[],manifest_sha256='1'*64))
        with self.b.db() as con:
            con.executescript('CREATE TABLE delivery_handoffs(source_task TEXT,stage TEXT,data TEXT,issue_id TEXT,updated REAL);'
                'CREATE TABLE delivery_routes(issue_id TEXT,config TEXT);CREATE TABLE snapshots(task_id TEXT,volume TEXT,status TEXT);'
                'CREATE TABLE validation_jobs(identity TEXT,state TEXT);CREATE TABLE test_first_red(issue_id TEXT,receipt TEXT);'
                'CREATE TABLE test_revision_trials(issue_id TEXT,state TEXT);')
            con.execute('INSERT INTO delivery_handoffs VALUES (?,?,?,?,?)',('source','technical_decision_required',json.dumps(dict(validation_failure=failure)),'issue',1))
            con.execute('INSERT INTO delivery_routes VALUES (?,?)',('issue',json.dumps(route)))
            con.execute('INSERT INTO snapshots VALUES (?,?,?)',('source','snapshot','complete'))
            con.execute('INSERT INTO validation_jobs VALUES (?,?)',(json.dumps(identity),json.dumps(job)))
            con.execute('INSERT INTO test_first_red VALUES (?,?)',('issue',json.dumps(red)))
            con.execute('INSERT INTO test_revision_trials VALUES (?,?)',('issue',json.dumps(review)))
        proof=dict(operation='inspected_product_scope_base_v1',base_sha=self.base['base_sha'],
                   manifest_sha256=self.base['manifest_sha256'],contract_sha256=self.context['contract_sha256'],
                   contract=self.original,delivery_approval=False,write_grant_issued=False)
        output=json.dumps(proof)
        self.result=dict(exit_code=0,output=output,output_sha256=hashlib.sha256(output.encode()).hexdigest(),approval=False)

    def test_existing_failure_opens_exact_persistent_plan_without_agent_calls_or_grants(self):
        with patch.object(bootstrap.validation_job,'run',return_value=self.result) as run:
            state=bootstrap.prepare(self.b,'issue',self.fx)
            self.assertEqual(state['context'],self.context)
            self.assertEqual(state['stage'],'awaiting_proposal');self.assertTrue(state['author_blocked'])
            payload=run.call_args.args[3]
            self.assertEqual(payload['Image'],bootstrap.IMAGE);self.assertTrue(payload['NetworkDisabled'])
            self.assertTrue(all(m['ReadOnly'] for m in payload['HostConfig']['Mounts']))
            self.assertEqual(bootstrap.prepare(self.b,'issue',self.fx),state)
            self.fx.wake.assert_not_called()

    def test_pending_read_reobserves_same_fixed_job(self):
        with patch.object(bootstrap.validation_job,'run',side_effect=[bootstrap.validation_job.Pending('live'),self.result]) as run:
            with self.assertRaises(bootstrap.validation_job.Pending):bootstrap.prepare(self.b,'issue',self.fx)
            bootstrap.prepare(self.b,'issue',self.fx)
            self.assertEqual(run.call_args_list[0],run.call_args_list[1])

    def test_changed_base_invalid_read_or_stale_sponsor_never_open_new_plan(self):
        for mutation in ({'approval':True},{'exit_code':1},{'output_sha256':'0'*64}):
            with self.subTest(mutation=mutation),patch.object(bootstrap.validation_job,'run',return_value=dict(self.result,**mutation)),self.assertRaises(ValueError):
                bootstrap.prepare(self.b,'issue',self.fx)
        self.fx.verify_binding.side_effect=ValueError('stale')
        with patch.object(bootstrap.validation_job,'run',return_value=self.result),self.assertRaises(ValueError):
            bootstrap.prepare(self.b,'issue',self.fx)

    def test_changed_frozen_tests_require_test_review_not_code_scope_replanning(self):
        with self.b.db() as con:con.execute('UPDATE test_first_red SET receipt=?',(json.dumps(dict(task_id='old',red=dict(test_sha256={}))),))
        with patch.object(bootstrap.validation_job,'run',return_value=self.result),self.assertRaises(ValueError):
            bootstrap.prepare(self.b,'issue',self.fx)

    def test_unrelated_observer_note_does_not_starve_valid_scope_bootstrap(self):
        def note_only(state):
            with self.b.db() as con:
                data=json.loads(con.execute('SELECT data FROM delivery_handoffs').fetchone()[0])
                data['observation_note']='still waiting for a technical decision'
                con.execute('UPDATE delivery_handoffs SET data=?',(json.dumps(data),))
        self.fx.verify_binding.side_effect=note_only
        with patch.object(bootstrap.validation_job,'run',return_value=self.result):
            self.assertEqual(bootstrap.prepare(self.b,'issue',self.fx)['stage'],'awaiting_proposal')

    def test_base_change_or_disabled_route_during_read_is_rejected(self):
        self.b.issue_base.side_effect=[self.base,dict(self.base,manifest_sha256='0'*64)]
        with patch.object(bootstrap.validation_job,'run',return_value=self.result),self.assertRaises(ValueError):
            bootstrap.prepare(self.b,'issue',self.fx)
