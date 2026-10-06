import json
import os
import sqlite3
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import test_incremental_checkpoints as fixtures
from broker import incremental_supervisor as supervisor
from broker import incremental_dispatch as dispatch


class SupervisorTests(unittest.TestCase):
    def test_pre_red_failure_routes_to_bounded_handoff_not_generic_incident(self):
        import sqlite3
        self.con.row_factory=sqlite3.Row;supervisor.handoffs.initialize(self.con)
        self.con.execute('CREATE TABLE test_first_red(issue_id TEXT,task_id TEXT)')
        route=dict(issue_id='issue',author='author')
        old=dict(id='old',agent_id='author',issue_id='issue',status='completed')
        new=dict(id='new',agent_id='author',issue_id='issue',status='completed')
        with patch.object(supervisor.test_first_handoffs,'reconcile') as recover:
            self.assertIsNone(supervisor.reconcile_red_author(self.b,route,[old],Mock()));recover.assert_called_once()
        self.con.execute('INSERT INTO test_first_red VALUES(?,?)',('issue','new'))
        with patch.object(supervisor.test_first_handoffs,'reconcile') as recover:
            self.assertEqual(supervisor.reconcile_red_author(self.b,route,[old,new],Mock()),new);recover.assert_not_called()
        with self.assertRaises(ValueError):supervisor.reconcile_red_author(self.b,route,[old],Mock())

    def test_checkpoint_task_recovery_uses_exact_durable_receipts(self):
        from broker import incremental_checkpoints as ledger
        unit=dict(id='U1',stage='checkpointed',green_manifest_sha256='a'*64)
        green=dict(operation='green',source_task='root',unit='U1',manifest_sha256='a'*64,task_id='author-task')
        unit['green']=ledger.digest(green)
        review=dict(operation='delivery_review',source_task='root',unit='U1',manifest_sha256='a'*64,task_id='review-task',decision='approve',green_receipt_sha256=unit['green'])
        unit['delivery_review']=ledger.digest(review)
        for key,proof in (('green',green),('delivery_review',review)):
            self.con.execute('INSERT INTO incremental_checkpoint_events VALUES(?,?,?)',('root',unit[key],json.dumps(proof)))
        self.assertEqual(supervisor.checkpoint_tasks(self.con,'root',unit),('author-task','review-task'))
        with self.assertRaises(ValueError):supervisor.checkpoint_tasks(self.con,'other',unit)
        with self.assertRaises(ValueError):supervisor.checkpoint_tasks(self.con,'root',{**unit,'delivery_source_task':'wrong'})
        self.con.execute("UPDATE incremental_checkpoint_events SET receipt=? WHERE receipt_sha256=?",(json.dumps({**review,'decision':'request_changes'}),unit['delivery_review']))
        with self.assertRaises(ValueError):supervisor.checkpoint_tasks(self.con,'root',unit)

    def test_checkpoint_publication_binds_exact_independent_approval_and_is_idempotent(self):
        import sqlite3
        self.con.row_factory=sqlite3.Row;supervisor.handoffs.initialize(self.con)
        self.con.execute('CREATE TABLE reviews(review_task_id TEXT,source_task_id TEXT,reviewer_agent_id TEXT,manifest_sha256 TEXT,status TEXT)')
        route=dict(issue_id='issue',author='author',reviewer='reviewer')
        self.con.execute('INSERT INTO delivery_routes VALUES(?,?)',('issue',json.dumps(route)))
        supervisor.handoffs.save(self.con,'source','issue','ready_review','reviewer',dict(green_validation=dict(manifest_sha256='a'*64)),1)
        self.con.execute('INSERT INTO reviews VALUES(?,?,?,?,?)',('review','source','reviewer','b'*64,'approved'))
        self.con.commit()
        state=dict(units=dict(U1=dict(stage='checkpointed',delivery_source_task='source',delivery_review_task='review',green_manifest_sha256='a'*64)))
        with patch.object(supervisor.handoff_runtime,'safe_publish') as publish:
            with self.assertRaises(ValueError):supervisor.publish_checkpoints(self.b,state)
            publish.assert_not_called()
            self.con.execute("UPDATE reviews SET manifest_sha256=?",('a'*64,))
            supervisor.publish_checkpoints(self.b,state);supervisor.publish_checkpoints(self.b,state)
            publish.assert_called_once()
        row=supervisor.handoffs.load(self.con,'source');self.assertEqual(row['stage'],'approved')
        self.assertFalse(json.loads(row['data'])['checkpoint_sync']['release_homologated'])

    def test_proxy_budget_unavailability_excludes_auth_and_invalid_payload(self):
        import urllib.error,io
        effects=supervisor.handoff_runtime.Effects(self.b,{})
        for error in (urllib.error.URLError('connection failed'),TimeoutError(),
                      urllib.error.HTTPError('http://model-proxy:8080/status',503,'unavailable',{},None)):
            with patch.object(supervisor.handoff_runtime.urllib.request,'urlopen',side_effect=error):
                with self.assertRaises(supervisor.handoff_runtime.BudgetStatusUnavailable):effects.remaining_calls()
        error=urllib.error.HTTPError('http://model-proxy:8080/status',401,'unauthorized',{},None)
        with patch.object(supervisor.handoff_runtime.urllib.request,'urlopen',side_effect=error):
            with self.assertRaises(urllib.error.HTTPError):effects.remaining_calls()
        with patch.object(supervisor.handoff_runtime.urllib.request,'urlopen',return_value=io.BytesIO(b'{"calls":1}')):
            with self.assertRaises(ValueError):effects.remaining_calls()

    def test_proxy_health_recovery_is_attributed_backed_off_and_read_only(self):
        import sqlite3
        self.con.row_factory=sqlite3.Row
        self.con.execute('CREATE TABLE incremental_runtime_incidents(source_task TEXT PRIMARY KEY,receipt TEXT)')
        incident=supervisor.handoff_runtime.BudgetStatusUnavailable().incident
        incident['next_check_at']=10
        self.con.execute('INSERT INTO incremental_runtime_incidents VALUES(?,?)',('source',json.dumps(incident)))
        effects=Mock();effects.remaining_calls.side_effect=supervisor.handoff_runtime.BudgetStatusUnavailable()
        self.assertFalse(supervisor.recover_proxy_health(self.b,'source',effects,now=9));effects.remaining_calls.assert_not_called()
        self.assertFalse(supervisor.recover_proxy_health(self.b,'source',effects,now=10));effects.remaining_calls.assert_called_once()
        updated=json.loads(self.con.execute('SELECT receipt FROM incremental_runtime_incidents').fetchone()[0])
        self.assertEqual(updated['health_checks'],1);self.assertEqual(updated['next_check_at'],30)
        self.assertFalse(supervisor.recover_proxy_health(self.b,'source',effects,now=29));effects.remaining_calls.assert_called_once()
        effects.remaining_calls.side_effect=ValueError('invalid budget status')
        self.assertFalse(supervisor.recover_proxy_health(self.b,'source',effects,now=30))
        effects.remaining_calls.side_effect=None;effects.remaining_calls.return_value=0
        self.assertTrue(supervisor.recover_proxy_health(self.b,'source',effects,now=31))
        self.assertFalse(self.con.execute('SELECT 1 FROM incremental_runtime_incidents').fetchone())
        receipt=json.loads(self.con.execute('SELECT receipt FROM incremental_recovery_evidence').fetchone()[0])
        self.assertFalse(receipt['execution_retried']);self.assertFalse(receipt['delivery_approval'])
        effects.ensure_wakeup.assert_not_called()
        self.con.execute('INSERT INTO incremental_runtime_incidents VALUES(?,?)',('source',json.dumps({'category':'URLError'})))
        self.assertFalse(supervisor.recover_proxy_health(self.b,'source',effects,now=100))

    def test_running_author_acceptance_is_exact_observation_not_approval(self):
        import sqlite3
        self.con.row_factory=sqlite3.Row;supervisor.handoffs.initialize(self.con)
        route=dict(issue_id='issue',author='author',contract_sha256='a'*64)
        data=dict(dispatch_stage='correct_author',target='author',wakeup_id='wake',contract_sha256='a'*64)
        supervisor.handoffs.save(self.con,'source','issue','awaiting_acceptance','author',data,1)
        run=dict(id='new-author',issue_id='issue',agent_id='author',status='running',wakeup_id='wake')
        for changes in (dict(wakeup_id='other'),dict(agent_id='other'),dict(issue_id='other'),dict(status='queued')):
            supervisor.observe_author_acceptance(self.b,route,[{**run,**changes}])
            self.assertEqual(supervisor.handoffs.load(self.con,'source')['stage'],'awaiting_acceptance')
        with self.assertRaises(ValueError):
            supervisor.observe_author_acceptance(self.b,route,[run,{**run,'id':'duplicate'}])
        supervisor.observe_author_acceptance(self.b,route,[run])
        row=supervisor.handoffs.load(self.con,'source');observed=json.loads(row['data'])
        self.assertEqual(row['stage'],'accepted');self.assertEqual(observed['recipient_task'],run['id'])
        self.assertNotIn('green_validation',observed);self.assertNotIn('delivery_approval',observed)
        count=self.con.execute('SELECT count(*) FROM delivery_handoff_events').fetchone()[0]
        supervisor.observe_author_acceptance(self.b,route,[run])
        self.assertEqual(self.con.execute('SELECT count(*) FROM delivery_handoff_events').fetchone()[0],count)

    def setUp(self):
        fixture=fixtures.IncrementalCheckpointTests();fixture.setUp()
        self.con=fixture.con;self.addCleanup(self.con.close)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        (Path(self.tmp.name)/'native.json').write_text('{}')
        class Context:
            def __enter__(_):return self.con
            def __exit__(_,kind,value,tb):self.con.commit() if kind is None else self.con.rollback()
        self.b=SimpleNamespace(LOCK=threading.RLock(),db=lambda:Context(),STATE=Path(self.tmp.name))
        self.state=fixture.state()

    def test_missing_product_delta_is_durable_diagnosis_not_runtime_limbo(self):
        self.con.row_factory=sqlite3.Row
        supervisor.handoffs.initialize(self.con)
        self.con.execute('CREATE TABLE incremental_runtime_incidents(source_task TEXT PRIMARY KEY,receipt TEXT)')
        incident=dict(category='ValueError',owner='cto',required_action='diagnose_incremental_runtime_binding_or_execution')
        self.con.execute('INSERT INTO incremental_runtime_incidents VALUES(?,?)',('root',json.dumps(incident)))
        route=dict(issue_id='issue',author='author',reviewer='reviewer',cto='cto',contract_sha256='a'*64)
        author=dict(id='author-task',status='completed')
        snapshot=dict(volume='snapshot',task_id='author-task',status='complete')
        error=ValueError('artifact_validation: new product code required; new test files present=1')
        phase=dict(phase='implementation',independent_test_review='approved')
        supervisor._artifact_handoff(self.b,'root',route,author,snapshot,error,phase=phase)
        row=supervisor.handoffs.load(self.con,'author-task');data=json.loads(row['data'])
        self.assertEqual(row['stage'],'diagnose_cto')
        self.assertEqual(data['failure_category'],'missing_delivery_artifacts')
        self.assertEqual(data['snapshot'],snapshot)
        self.assertEqual(data['previous_runtime_incident'],incident)
        self.assertFalse(self.con.execute('SELECT 1 FROM incremental_runtime_incidents').fetchone())
        self.assertNotIn('green_validation',data)
        self.assertNotIn('validation_failure',data)
        count=self.con.execute('SELECT count(*) FROM delivery_handoff_events').fetchone()[0]
        supervisor._artifact_handoff(self.b,'root',route,author,snapshot,error,phase=phase)
        self.assertEqual(count,self.con.execute('SELECT count(*) FROM delivery_handoff_events').fetchone()[0])
        with self.assertRaises(ValueError):
            supervisor._artifact_handoff(self.b,'root',route,author,snapshot,ValueError('other'),phase=phase)

    def enable(self):
        self.state['execution_authorized']=True
        self.con.execute('UPDATE incremental_checkpoints SET state=?',(json.dumps(self.state),))

    def test_default_disabled_and_unauthorized_contract_never_run_effects(self):
        with patch.dict(os.environ,{'BROKER_INCREMENTAL_ENABLED':'0'}),patch.object(supervisor,'_step') as step:
            supervisor.tick(self.b);step.assert_not_called()
        with patch.dict(os.environ,{'BROKER_INCREMENTAL_ENABLED':'1'}),patch.object(supervisor,'_step') as step:
            supervisor.tick(self.b);step.assert_not_called()

    def test_runtime_failure_is_persistent_and_not_retried_indefinitely(self):
        self.enable()
        with patch.dict(os.environ,{'BROKER_INCREMENTAL_ENABLED':'1'}),patch.object(supervisor,'_step',side_effect=ValueError()) as step:
            supervisor.tick(self.b);supervisor.tick(self.b)
            step.assert_called_once()
        incident=json.loads(self.con.execute('SELECT receipt FROM incremental_runtime_incidents').fetchone()[0])
        self.assertIn('required_action',incident)
        self.assertEqual(incident['owner'],'cto')

    def test_owned_unit_excluded_from_legacy_coordinator_even_when_paused(self):
        dispatch.initialize(self.con)
        self.con.execute('INSERT INTO incremental_unit_owners VALUES(?,?,?,?)',('child','source','U1',1))
        self.assertTrue(dispatch.owns(self.con,'child'))
        self.assertFalse(dispatch.owns(self.con,'unrelated'))

    def test_checkpointed_units_do_not_trigger_more_work(self):
        for unit in self.state['units'].values():unit['stage']='checkpointed'
        supervisor._step(self.b,{'source_task':'source'},self.state,Mock(),{})

    def test_delivery_review_intent_committed_before_dispatch_and_idempotent(self):
        import sqlite3
        self.con.row_factory=sqlite3.Row;supervisor.handoffs.initialize(self.con)
        route=dict(issue_id='issue',author='author',reviewer='reviewer')
        author=dict(id='completed-author',issue_id='issue',agent_id='author',status='completed')
        snapshot=dict(task_id='completed-author',status='complete',volume='immutable')
        proof=dict(manifest_sha256='a'*64,tests=249)
        first=supervisor.register_review_intent(self.b,route,author,snapshot,proof,'marker')
        row=supervisor.handoffs.load(self.con,author['id']);self.assertEqual(row['stage'],'ready_review')
        self.assertEqual(json.loads(row['data'])['target'],'reviewer')
        self.assertFalse(first['delivery_approval']);self.assertFalse(self.con.in_transaction)
        self.assertEqual(first,supervisor.register_review_intent(self.b,route,author,snapshot,proof,'marker'))
        with self.assertRaises(ValueError):supervisor.register_review_intent(self.b,route,author,snapshot,proof,'other')
        with self.assertRaises(ValueError):supervisor.register_review_intent(self.b,route,{**author,'status':'running'},snapshot,proof,'marker')

    def test_functional_failure_creates_cto_handoff_once_without_model_effects(self):
        import sqlite3
        self.con.row_factory=sqlite3.Row
        route=dict(issue_id='child',author='author',reviewer='reviewer',cto='cto',contract_sha256='a'*64)
        failure=dict(category='executed_test_failure',source_task='task',volume='frozen',output_sha256='b'*64)
        supervisor._functional_handoff(self.b,route,dict(id='task'),failure,dict(volume='frozen'))
        supervisor._functional_handoff(self.b,route,dict(id='task'),failure,dict(volume='frozen'))
        row=supervisor.handoffs.load(self.con,'task');data=json.loads(row['data'])
        self.assertEqual(row['stage'],'diagnose_cto');self.assertEqual(row['owner'],'cto')
        self.assertEqual(data['validation_failure'],failure)
        self.assertTrue(data['artifact_diagnosis'])
        self.assertEqual(self.con.execute('SELECT count(*) FROM delivery_handoff_events').fetchone()[0],1)

    def review_fixture(self):
        import sqlite3
        self.con.row_factory=sqlite3.Row;supervisor.handoffs.initialize(self.con)
        route=dict(issue_id='issue',author='author',reviewer='reviewer',contract_sha256='c'*64)
        author=dict(id='author-task',issue_id='issue',agent_id='author',status='completed')
        snapshot=dict(task_id=author['id'],status='complete',volume='immutable')
        proof=dict(manifest_sha256='a'*64,tests=249)
        supervisor.register_review_intent(self.b,route,author,snapshot,proof,'marker')
        row=supervisor.handoffs.load(self.con,author['id']);data=json.loads(row['data']);data['wakeup_id']='wake'
        supervisor.handoffs.save(self.con,author['id'],'issue','ready_review','reviewer',data,1)
        return route,author,snapshot,proof

    def test_registered_green_reuses_exact_snapshot_and_rejects_drift(self):
        route,author,snapshot,proof=self.review_fixture()
        row=supervisor.handoffs.load(self.con,author['id'])
        self.assertEqual(supervisor.registered_green(row,snapshot),proof)
        with self.assertRaisesRegex(ValueError,'snapshot drift'):
            supervisor.registered_green(row,{**snapshot,'volume':'other'})
        data=json.loads(row['data']);data['green_validation']['manifest_sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'manifest drift'):
            supervisor.registered_green({**row,'data':json.dumps(data)},snapshot)

    def test_legacy_intent_migrates_green_without_duplicate_wakeup(self):
        route,author,snapshot,proof=self.review_fixture()
        row=supervisor.handoffs.load(self.con,author['id']);data=json.loads(row['data']);del data['green_validation']
        supervisor.handoffs.save(self.con,author['id'],'issue','ready_review','reviewer',data,2)
        migrated=supervisor.register_review_intent(self.b,route,author,snapshot,proof,'marker')
        self.assertEqual(migrated['wakeup_id'],'wake');self.assertEqual(migrated['green_validation'],proof)
        self.assertFalse(self.con.in_transaction)

    def test_review_changes_return_to_original_author_without_approval(self):
        route,author,snapshot,proof=self.review_fixture()
        review=dict(id='review-task',agent_id='reviewer',status='completed',wakeup_id='wake')
        result=dict(review_task_id=review['id'],source_task_id=author['id'],reviewer_agent_id='reviewer',
                    status='changes_requested',finding='Correct the implementation, preserve tests')
        with self.assertRaisesRegex(ValueError,'identity drift'):
            supervisor.register_review_changes(self.b,route,author,{**review,'wakeup_id':'old'},result,proof)
        supervisor.register_review_changes(self.b,route,author,review,result,proof)
        row=supervisor.handoffs.load(self.con,author['id']);data=json.loads(row['data'])
        self.assertEqual(row['stage'],'correct_author');self.assertEqual(row['owner'],'author')
        self.assertFalse(data['delivery_approval']);self.assertEqual(data['evidence'],proof)
        self.assertEqual(data['contract_sha256'],route['contract_sha256'])
        self.assertEqual(data['author'],'author');self.assertEqual(data['attempts'],1)
        self.assertFalse(self.con.in_transaction)

    def test_tick_waiting_for_registered_review_does_not_repeat_green(self):
        route,author,snapshot,proof=self.review_fixture()
        route.update(enabled=True,minimum_calls=8,review_instruction='Review')
        self.state['units']['U1'].update(stage='awaiting_green',binding=dict(issue_id='issue'))
        self.con.execute('INSERT INTO delivery_routes VALUES(?,?)',('issue',json.dumps(route)))
        unit=self.state['units']['U1']
        marker=supervisor.ledger.digest(dict(source_task='source',unit='U1',revision=unit['revision'],
            operation='incremental-delivery-review-v2',author_task=author['id']))
        row=supervisor.handoffs.load(self.con,author['id']);data=json.loads(row['data']);data['dispatch_marker']=marker
        supervisor.handoffs.save(self.con,author['id'],'issue','ready_review','reviewer',data,1)
        review=dict(id='review-task',status='running',agent_id='reviewer',wakeup_id='wake')
        effects=Mock();effects.freeze.return_value=snapshot;effects.assign.return_value=True
        effects.ensure_wakeup.return_value=dict(id='wake');effects.remaining_calls.return_value=20
        with patch.object(supervisor.native,'issue_task_runs',return_value=[author,review]),\
                patch.object(supervisor.test_first_handoffs,'reconcile',return_value=[author,review]):
            supervisor._step(self.b,dict(source_task='source'),self.state,effects,{})
        effects.validate.assert_not_called();effects.review_result.assert_not_called()

    def test_unchanged_rejected_correction_requires_cto_not_another_review(self):
        route,author,snapshot,proof=self.review_fixture();route['cto']='cto'
        row=supervisor.handoffs.load(self.con,author['id']);data=json.loads(row['data'])
        data.update(dispatch_stage='correct_author',wakeup_id='correction',finding='Check disputed behavior',
                    review=dict(review_task_id='review',status='changes_requested'))
        supervisor.handoffs.save(self.con,author['id'],'issue','awaiting_acceptance','author',data,1)
        corrected={**author,'id':'corrected','wakeup_id':'unrelated'}
        snapshot={**snapshot,'task_id':'corrected'}
        self.assertFalse(supervisor.unchanged_review_correction(self.b,route,corrected,snapshot,proof))
        corrected['wakeup_id']='correction'
        self.assertFalse(supervisor.unchanged_review_correction(self.b,route,corrected,snapshot,{**proof,'manifest_sha256':'b'*64}))
        self.assertTrue(supervisor.unchanged_review_correction(self.b,route,corrected,snapshot,proof))
        row=supervisor.handoffs.load(self.con,'corrected');data=json.loads(row['data'])
        self.assertEqual(row['stage'],'diagnose_cto');self.assertEqual(row['owner'],'cto')
        self.assertFalse(data['delivery_approval'])
        self.assertEqual(supervisor.handoffs.load(self.con,author['id'])['stage'],'superseded')
        self.assertFalse(self.con.in_transaction)

    def test_functional_failure_rejects_wrong_snapshot_or_source(self):
        failure=dict(source_task='wrong',volume='frozen')
        with self.assertRaisesRegex(ValueError,'identity'):
            supervisor._functional_handoff(self.b,{},dict(id='task'),failure,dict(volume='frozen'))
        failure['source_task']='task'
        with self.assertRaisesRegex(ValueError,'identity'):
            supervisor._functional_handoff(self.b,{},dict(id='task'),failure,dict(volume='other'))

    def test_running_native_author_with_expired_lease_is_visible_not_waiting_forever(self):
        import sqlite3
        self.con.row_factory=sqlite3.Row
        self.con.execute('CREATE TABLE native_bindings(task_id TEXT,request_id TEXT)')
        self.con.execute('CREATE TABLE leases(request_id TEXT,status TEXT,deadline REAL)')
        self.con.execute('INSERT INTO native_bindings VALUES(?,?)',('task','request'))
        self.con.execute('INSERT INTO leases VALUES(?,?,?)',('request','expired',1))
        self.con.commit()
        with self.assertRaises(supervisor.ExpiredAuthorLease) as error:
            supervisor._check_author_leases(self.b,dict(cto='actual-cto'),[dict(id='task',status='running')])
        self.assertEqual(error.exception.incident['owner'],'actual-cto')
        self.assertEqual(error.exception.incident['request_id'],'request')
        self.assertFalse(error.exception.incident['automatic_retry'])
        self.con.execute("UPDATE leases SET status='running'")
        supervisor._check_author_leases(self.b,dict(cto='actual-cto'),[dict(id='task',status='running')])
        self.con.execute("UPDATE leases SET status='expired'")
        supervisor._check_author_leases(self.b,dict(cto='actual-cto'),[dict(id='task',status='completed')])

    def test_green_failure_is_routed_not_approved_and_persistent_recovery_is_reconciled(self):
        import sqlite3
        self.con.row_factory=sqlite3.Row
        from broker.suite_failure import FrozenSuiteFailure
        route=dict(issue_id='child',enabled=True,author='author',reviewer='reviewer',cto='cto',contract_sha256='a'*64)
        self.state['units']['U1'].update(stage='awaiting_green',binding=dict(issue_id='child'))
        self.con.execute('CREATE TABLE delivery_routes(issue_id TEXT PRIMARY KEY,config TEXT)')
        self.con.execute('INSERT INTO delivery_routes VALUES(?,?)',('child',json.dumps(route)))
        supervisor.handoffs.initialize(self.con)
        run=dict(id='task',agent_id='author',status='completed',created_at='1',issue_id='child')
        effects=Mock();effects.freeze.return_value=dict(volume='frozen')
        effects.phase_evidence.return_value=dict(phase='implementation',independent_test_review='approved')
        failure=dict(category='executed_test_failure',source_task='task',volume='frozen',output_sha256='b'*64)
        effects.validate.side_effect=FrozenSuiteFailure(failure)
        cto=dict(id='diagnosis',agent_id='cto',status='completed',created_at='2',issue_id='child')
        with patch.object(supervisor.native,'issue_task_runs',return_value=[run,cto]),\
                patch.object(supervisor.test_first_handoffs,'reconcile',return_value=[run]),\
                patch.object(supervisor,'_record') as record:
            supervisor._step(self.b,dict(source_task='source'),self.state,effects,{})
            effects.assign.assert_not_called();record.assert_not_called()
            with patch.object(supervisor.handoffs,'reconcile') as reconcile:
                supervisor._step(self.b,dict(source_task='source'),self.state,effects,{})
                reconcile.assert_called_once_with(self.con,route,[run,cto],effects)
            self.assertEqual(effects.validate.call_count,1)

    def test_missing_provisioning_is_not_simulated_as_author_dispatch(self):
        with self.assertRaisesRegex(ValueError,'provisioning'):
            supervisor._step(self.b,{'source_task':'source'},self.state,Mock(),{})

    def test_only_exact_recovery_run_can_advance_red(self):
        self.state['units']['U1']['binding']=dict(issue_id='child',prior_suite='proof')
        self.con.execute('CREATE TABLE delivery_routes(issue_id TEXT PRIMARY KEY,config TEXT)')
        self.con.execute('INSERT INTO delivery_routes VALUES(?,?)',('child',json.dumps(dict(enabled=True,author='author'))))
        self.b.capture_test_first_red=Mock()
        old=dict(id='failed',agent_id='author',status='failed',wakeup_id='old')
        new=dict(id='replacement',agent_id='author',status='running',wakeup_id='repair')
        receipt=dict(failed_task='failed',wakeup_id='repair')
        with patch.object(supervisor.native,'issue_task_runs',return_value=[old,new]),patch.object(dispatch,'dispatch'),\
                patch.object(supervisor.incremental_read_recovery,'reconcile',return_value=receipt):
            supervisor._step(self.b,{'source_task':'source'},self.state,Mock(),{})
            self.b.capture_test_first_red.assert_not_called()
            new['status']='completed'
            with patch.object(supervisor.evidence,'red',return_value={}) as red,patch.object(supervisor,'_record'), \
                    patch.object(supervisor,'reconcile_red_author',return_value=new) as recover:
                supervisor._step(self.b,{'source_task':'source'},self.state,Mock(),{})
                recover.assert_called_once()
                self.assertEqual(red.call_args.args[4],'replacement')
            new['wakeup_id']='unrelated'
            with self.assertRaisesRegex(ValueError,'unexpected author'):
                supervisor._step(self.b,{'source_task':'source'},self.state,Mock(),{})
