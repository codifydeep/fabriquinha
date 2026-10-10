import copy
import unittest
from unittest.mock import patch
from broker.review_successor_resolution import prepare
from broker.review_successor_withdrawal import prepare as withdraw
from broker.technical_remediation_plan import digest
from test_review_successor_withdrawal import SuccessorWithdrawalTests


class SuccessorResolutionTests(unittest.TestCase):
    def fixture(self):
        config,state,route,red,review,source,parent,admission,runs,wakes,contract=SuccessorWithdrawalTests().fixture()
        contract['run_id']='parent-run'
        contract['original_depth']=2
        parent['contract_sha256']=digest(contract)
        config['r1_feedback']['previous_execution_sha256']=digest(contract)
        parent['superseded_by_feedback']['config_sha256']=digest(config)
        admission['superseded_admission']=dict(stage='phases_admitted',budget_admitted=True,
            release_homologated=False,steps={'R1':{'issue_id':'original','stage':'phase_enabled'}})
        red.update(issue_id='original',red={'manifest_sha256':'a'*64})
        held,proof=withdraw(config,state,route,red,review,source,parent,admission,runs,wakes,contract)
        decision=dict(action='approve_test_revision',manifest_sha256='a'*64,findings=[])
        trial=dict(status='approved',source_task='author',manifest_sha256='a'*64,review_task='new-review',
            decision=decision,review_reconsideration=dict(operation='immutable_review_reconsideration_v1',
                manifest_sha256='a'*64,delivery_approval=False,test_changes_authorized=False))
        parent['r1_gate']=dict(operation='immutable_remediation_r1_gate_v1',run_id=contract['run_id'],
            execution_contract_sha256=digest(contract),red=red,review_task='new-review',
            review_decision=decision,product_execution_authorized=False,release_homologated=False)
        return [source,parent,contract,admission,config,held,trial]

    def test_live_validation_and_cas_never_activate_routes_or_accept_stale_review(self):
        import contextlib,json,pathlib,sqlite3,tempfile
        from types import SimpleNamespace
        from broker import review_successor_resolution as resolution,remediation_test_review,native
        for failure in (None,'plan','evidence','task','cas'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as directory:
                source,parent,contract,admission,config,held,trial=self.fixture()
                trial['wakeup_id']='review-wake'
                path=pathlib.Path(directory)/'state.sqlite'
                @contextlib.contextmanager
                def db():
                    con=sqlite3.connect(path)
                    try:
                        with con:yield con
                    finally:con.close()
                b=SimpleNamespace(db=db)
                route={'author':'author-role','techlead':'lead'}
                with db() as c:
                    c.execute('CREATE TABLE remediation_admissions(source_task TEXT,state TEXT)')
                    c.execute('CREATE TABLE remediation_executions(source_task TEXT,contract TEXT,state TEXT)')
                    c.execute('CREATE TABLE technical_remediation_plans(source_task TEXT,config TEXT,state TEXT)')
                    c.execute('CREATE TABLE test_revision_trials(issue_id TEXT,state TEXT)')
                    c.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
                    c.execute('INSERT INTO remediation_admissions VALUES(?,?)',(source,json.dumps(admission)))
                    c.execute('INSERT INTO remediation_executions VALUES(?,?,?)',(source,json.dumps(contract),json.dumps(parent)))
                    c.execute('INSERT INTO technical_remediation_plans VALUES(?,?,?)',('author',json.dumps(config),json.dumps(held)))
                    c.execute('INSERT INTO test_revision_trials VALUES(?,?)',('original',json.dumps(trial)))
                    c.execute('INSERT INTO delivery_routes VALUES(?,?)',('original',json.dumps(route)))
                fx=SimpleNamespace(plan=lambda _: (_ for _ in ()).throw(ValueError('plan')) if failure=='plan' else None,
                    native=SimpleNamespace(settings={},decision=lambda _:trial['decision']))
                def task(*_):
                    if failure=='cas':
                        with db() as c:c.execute('UPDATE delivery_routes SET config=?',(json.dumps({**route,'enabled':True}),))
                    return dict(status='completed' if failure!='task' else 'running',issue_id='original',
                        wakeup_id='review-wake',agent_id='lead')
                with patch.object(remediation_test_review,'verify',side_effect=ValueError('evidence') if failure=='evidence' else None) as verify, \
                        patch.object(native,'task_record',side_effect=task):
                    if failure:
                        with self.assertRaises(ValueError):resolution.resolve(b,source,fx)
                    else:
                        restored=resolution.resolve(b,source,fx)
                        self.assertEqual(restored['stage'],'phases_admitted')
                        verify.assert_called_once()
                with db() as c:
                    self.assertEqual(json.loads(c.execute('SELECT state FROM remediation_executions').fetchone()[0]),parent)
                    self.assertEqual(json.loads(c.execute('SELECT state FROM technical_remediation_plans').fetchone()[0]),held)
                    actual=json.loads(c.execute('SELECT state FROM remediation_admissions').fetchone()[0])
                    self.assertEqual(actual,admission if failure else restored)

    def test_restore_only_original_admission_preserving_every_prior_record(self):
        args=self.fixture();before=copy.deepcopy(args);restored=prepare(*args)
        self.assertEqual(args,before)
        self.assertEqual(restored['steps'],args[3]['superseded_admission']['steps'])
        self.assertEqual(restored['stage'],'phases_admitted')
        proof=restored['withdrawn_successor_resolution']
        self.assertEqual(proof['prior_admission'],args[3])
        self.assertEqual(proof['consumed_feedback_round'],2)
        self.assertEqual(proof['manifest_sha256'],'a'*64)
        for key in ('phase_activated','author_restarted','release_homologated'):self.assertFalse(proof[key])
        self.assertNotIn('R2',restored['steps'])

    def test_reject_stale_gate_changed_successor_or_unapproved_product_authority(self):
        changes=[(1,['r1_gate','review_task'],'other'),(1,['r1_gate','product_execution_authorized'],True),
            (1,['contract_sha256'],'b'*64),(1,['superseded_by_feedback','config_sha256'],'b'*64),
            (2,['run_id'],'changed'),(3,['category'],'operator_pause'),
            (3,['superseded_admission','steps','R2'],{'stage':'enabled'}),
            (3,['superseded_admission','budget_admitted'],False),
            (5,['stage'],'plan_dispatch'),(5,['review_mediation_withdrawal','tasks_observed'],1),
            (6,['status'],'blocked'),(6,['manifest_sha256'],'b'*64),
            (6,['decision','findings'],[{'kind':'missing_coverage'}]),
            (6,['review_reconsideration','delivery_approval'],True)]
        for index,path,value in changes:
            args=copy.deepcopy(self.fixture());target=args[index]
            for key in path[:-1]:target=target[key]
            target[path[-1]]=value
            with self.assertRaises(ValueError,msg=str(path)):prepare(*args)

    def test_admission_invokes_resolution_before_normal_phase_checks(self):
        import inspect
        from broker import remediation_admission
        # A wiring assertion, not proof of a live transition; integration below
        # must still qualify real plan/review evidence and transactional CAS.
        self.assertIn('review_successor_resolution.resolve',inspect.getsource(remediation_admission.reconcile))
