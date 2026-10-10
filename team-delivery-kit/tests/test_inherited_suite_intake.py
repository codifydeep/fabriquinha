import copy
import json
import unittest
import sqlite3
import threading
import hashlib
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from broker import inherited_suite_intake as intake, technical_remediation_plan as plans
import test_diagnostic_evidence_context as fixtures
from execution_context import freeze


class InheritedSuiteIntakeTests(unittest.TestCase):
    def fixture(self):
        cfg, _, row, route, task, binding, decision, reads, context = fixtures.DiagnosticEvidenceTests().fixture()
        route.update(issue_id=row['issue_id'], reviewer='reviewer', techlead='lead',
                     contract_sha256='a'*64, execution_context=freeze(
                         'Goal. Acceptance: ["entire approved scope"]','Independent review'))
        previous=dict(source_task='previous', root_issue='root', original_depth=2,
            revision_lineage=['second','first'], criteria={'A01':'entire approved scope'},
            contract_sha256='a'*64, base={'base_sha':'c'*40,'manifest_sha256':'d'*64},
            baseline_edits_allowed=False, historical_snapshots_editable=False,
            release_homologated=False, steps=[{}, {'owner':'author'}])
        reference=dict(issue_id=row['issue_id'], origin_issue='r1', source_task='previous',
            original_depth=2, execution_contract_sha256=plans.digest(previous),
            route_sha256=plans.digest({k:v for k,v in route.items() if k!='enabled'}),
            criteria=previous['criteria'], red={'task_id':'red','volume':'red-volume',
                'red':{'test_sha256':{'tests/test_new.py':'b'*64},'manifest_sha256':'a'*64}})
        data=json.loads(row['data']);data['diagnostic_evidence_context']=context
        data['validation_failure'].update(failures=[{'qualified_name':'tests.test_new.Case.test_x'}],
            phase='frozen_green',exit_code=1)
        context['failure_sha256']=fixtures.spike.digest(data['validation_failure'])
        data['source_status']='completed';data['attempts']=2
        data['completed_validation_diagnostic']={'failure':data['validation_failure'],
            'status':'diagnostic_only_not_approved'}
        row['data']=json.dumps(data)
        reads['/evidence/previous/tests/test_new.py']={'lines':10,'total_lines':10}
        return row,route,previous,reference,task,binding,decision,reads

    def test_distinct_planning_intake_preserves_history_and_grants_no_execution(self):
        args=self.fixture();old=copy.deepcopy(args)
        value=intake.configuration(*args)
        self.assertEqual(args,old)
        self.assertEqual(value['intake_kind'],'exhausted_frozen_suite_v1')
        self.assertEqual(value['criteria'],args[2]['criteria'])
        self.assertEqual(value['revision_lineage'],args[2]['revision_lineage'])
        self.assertEqual(value['preserved_source_attempts'],2)
        amendment=value['amendment']
        self.assertEqual(amendment['kind'],'inherited_frozen_suite')
        self.assertEqual(amendment['seed_red'],args[3]['red'])
        self.assertFalse(amendment['execution_authorized'])
        self.assertFalse(amendment['revision_depth_reset'])
        self.assertFalse(value['experiment']['proof']['facts']['test_defect_proven'])
        note=plans.instruction(value,{'stage':'plan_dispatch'})
        self.assertNotIn('count only /service-mode',note)
        self.assertNotIn('fails Node syntax',note)
        self.assertIn('A01',note)
        self.assertLess(len(note),3800)

    def test_foreign_context_partial_reads_roles_and_recursive_amendment_rejected(self):
        for change in ('context','source','decision','partial','previous','roles','lineage','repeat','binding'):
            args=list(copy.deepcopy(self.fixture()));row,route,previous,reference,task,binding,decision,reads=args
            data=json.loads(row['data'])
            if change=='context':data['diagnostic_evidence_context']['proof_sha256']='e'*64
            if change=='source':task['issue_id']='foreign'
            if change=='decision':decision['action']='request_correction'
            if change=='partial':reads['/evidence/previous/tests/test_new.py']['lines']=1
            if change=='previous':reference['execution_contract_sha256']='e'*64
            if change=='roles':route['techlead']='cto'
            if change=='lineage':previous['revision_lineage']=[]
            if change=='repeat':previous['amendment']={'kind':'inherited_frozen_suite'}
            if change=='binding':binding['status']='running'
            row['data']=json.dumps(data)
            with self.subTest(change=change),self.assertRaises(ValueError):intake.configuration(*args)

    def test_restart_observes_same_plan_and_preserves_handoff_evidence(self):
        args=self.fixture();row,route=args[:2];value=intake.configuration(*args)
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        intake.handoffs.initialize(con);con.execute('CREATE TABLE leases(status TEXT)')
        con.execute('INSERT INTO delivery_routes VALUES(?,?)',(row['issue_id'],json.dumps(route)))
        intake.handoffs.save(con,row['source_task'],row['issue_id'],row['stage'],row['owner'],json.loads(row['data']),0)
        current=intake.handoffs.load(con,row['source_task'])
        @contextmanager
        def db():
            with con:yield con
        b=SimpleNamespace(db=db,LOCK=threading.RLock())
        with patch.object(intake,'qualify',return_value=(current,route,value)) as qualified:
            state=intake.register(b,row['source_task'])
            self.assertEqual(intake.register(b,row['source_task']),state)
            self.assertEqual(qualified.call_count,1)
        saved=intake.handoffs.load(con,row['source_task']);data=json.loads(saved['data'])
        old=json.loads(row['data'])
        for key in ('decision','validation_failure','diagnostic_evidence_context','attempts'):
            self.assertEqual(data[key],old[key])
        self.assertFalse(json.loads(con.execute('SELECT config FROM delivery_routes').fetchone()[0])['enabled'])
        self.assertFalse(state['execution_authorized']);self.assertFalse(state['release_homologated'])
        self.assertEqual(con.execute('SELECT count(*) FROM technical_remediation_plans').fetchone()[0],1)

    def test_executor_rechecks_original_root_admission_and_failure(self):
        args=self.fixture();value=intake.configuration(*args);previous=args[2]
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        con.execute('CREATE TABLE remediation_executions(source_task TEXT,contract TEXT)')
        con.execute('CREATE TABLE remediation_admissions(source_task TEXT,intent TEXT)')
        con.execute('CREATE TABLE frozen_suite_failures(task_id TEXT,receipt TEXT)')
        con.execute('INSERT INTO remediation_executions VALUES(?,?)',(previous['source_task'],json.dumps(previous)))
        intent=dict(root_issue=previous['root_issue'],execution_contract_sha256=plans.digest(previous))
        con.execute('INSERT INTO remediation_admissions VALUES(?,?)',(previous['source_task'],json.dumps(intent)))
        con.execute('INSERT INTO frozen_suite_failures VALUES(?,?)',(value['source_task'],json.dumps(value['historical_failure'])))
        intake.validate_parent(con,value)
        for change in ('root','lineage','base','failure'):
            config=copy.deepcopy(value)
            if change=='root':config['root_issue']='different'
            if change=='lineage':config['revision_lineage']=[]
            if change=='base':config['base']['base_sha']='e'*40
            if change=='failure':config['historical_failure']['tests_executed']=1
            with self.subTest(change=change),self.assertRaises(ValueError):intake.validate_parent(con,config)

    def test_byte_verification_consumes_only_completed_exact_archived_job(self):
        from broker import validation_job
        red=self.fixture()[3]['red'];source='source';volume='candidate';image='sha256:'+'c'*64
        identity=dict(task=source,kind='green',payload=dict(Image=image,Entrypoint=['python'],
            Cmd=['/test_first_verify.py'],NetworkDisabled=True,
            Labels={'delivery-kit.owner':'owner','delivery-kit.source-task':source},
            Env=['TEST_FIRST_TEST_HASHES='+json.dumps(red['red']['test_sha256']),
                 'TEST_FIRST_RED_MANIFEST_SHA256='+red['red']['manifest_sha256']],
            HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',Mounts=[
                dict(Type='volume',Source=volume,Target='/delivery',ReadOnly=True),
                dict(Type='volume',Source=red['volume'],Target='/red',ReadOnly=True)])))
        state=dict(stage='complete',result=dict(exit_code=0,approval=False,output='verified',
            output_sha256=hashlib.sha256(b'verified').hexdigest(),
            validation_contract_sha256=validation_job.digest(identity)))
        intake.verify_hash_receipt(identity,state,source,volume,red,image,'owner')
        for change in ('pending','exit','output','identity','mount','env','approval'):
            i,s=copy.deepcopy((identity,state))
            if change=='pending':s['stage']='running'
            if change=='exit':s['result']['exit_code']=1
            if change=='output':s['result']['output']='different'
            if change=='identity':s['result']['validation_contract_sha256']='f'*64
            if change=='mount':i['payload']['HostConfig']['Mounts'][0]['ReadOnly']=False
            if change=='env':i['payload']['Env'].append('UNRELATED_SECRET=not-a-credential')
            if change=='approval':s['result']['approval']=True
            with self.subTest(change=change),self.assertRaises(ValueError):
                intake.verify_hash_receipt(i,s,source,volume,red,image,'owner')

    def test_rejected_intake_is_visible_and_not_identically_requalified(self):
        args=self.fixture();row,route=args[:2]
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        intake.handoffs.initialize(con);con.execute('CREATE TABLE leases(status TEXT)')
        con.execute('INSERT INTO delivery_routes VALUES(?,?)',(row['issue_id'],json.dumps(route)))
        intake.handoffs.save(con,row['source_task'],row['issue_id'],row['stage'],row['owner'],json.loads(row['data']),0)
        @contextmanager
        def db():
            with con:yield con
        b=SimpleNamespace(db=db,LOCK=threading.RLock())
        with patch.object(intake,'register',side_effect=ValueError('source mismatch')) as register:
            intake.tick(b);intake.tick(b)
            self.assertEqual(register.call_count,1)
        current=intake.handoffs.load(con,row['source_task']);data=json.loads(current['data'])
        self.assertEqual(current['owner'],'cto')
        self.assertEqual(data['inherited_suite_intake_hold']['category'],'ValueError')
        self.assertFalse(data['inherited_suite_intake_hold']['execution_authorized'])
        self.assertIn('qualification',data['required_action'])
        self.assertEqual(data['validation_failure'],json.loads(row['data'])['validation_failure'])
