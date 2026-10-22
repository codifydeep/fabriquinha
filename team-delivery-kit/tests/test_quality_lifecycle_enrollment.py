"""Persistent enrollment tests, not native execution or delivery evidence."""
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from broker import quality_lifecycle_enrollment as enrollment
from broker import quality_lifecycle_v2 as policy
from test_portable_contract import contract


class QualityEnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.database = self.root/'state.sqlite'
        self.issue = '10000000-0000-4000-8000-000000000001'
        self.run = '10000000-0000-4000-8000-000000000002'
        self.author = '10000000-0000-4000-8000-000000000003'
        self.reviewer = '10000000-0000-4000-8000-000000000004'
        self.operation = '10000000-0000-4000-8000-000000000005'
        self.settings = dict(workspace_id='workspace', runtime_id='runtime',
            agents={self.author:'implementation', self.reviewer:'review'})
        (self.root/'native.json').write_text(json.dumps(self.settings))
        @contextmanager
        def db():
            con = sqlite3.connect(self.database)
            con.row_factory = sqlite3.Row
            try:
                with con: yield con
            finally: con.close()
        self.b = SimpleNamespace(db=db, LOCK=threading.RLock(), STATE=self.root,
            PREFIX='delivery-kit-test', issue_base=Mock(return_value=dict(
                issue_id=self.issue, base_sha='b'*40, volume='frozen-base', manifest_sha256='d'*64)))
        with db() as con:
            con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,issue_id TEXT)')
            con.execute('CREATE TABLE grants(task_id TEXT,used INTEGER,deadline REAL,request_id TEXT)')
            con.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
            con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
            con.execute('CREATE TABLE delivery_handoffs(issue_id TEXT,stage TEXT)')
            con.execute('CREATE TABLE contract_revisions(issue_id TEXT,body TEXT)')
            con.execute('CREATE TABLE product_scope_runs(issue_id TEXT,state TEXT)')
            con.execute('CREATE TABLE issue_bases(issue_id TEXT,base_sha TEXT,volume TEXT,manifest_sha256 TEXT)')
            con.execute('INSERT INTO issue_bases VALUES(?,?,?,?)',
                (self.issue,'b'*40,'frozen-base','d'*64))
            enrollment.maintenance.initialize(con)
            state=dict(operation_id=self.operation, namespace=self.b.PREFIX, stage='sealed', drained=True)
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',
                (self.operation,'sealed',json.dumps(state)))
        self.spec = contract()
        self.plan = dict(version=2,policy=policy.POLICY,run_id=self.run,issue_id=self.issue,
            contract_sha256=policy.digest(self.spec),base_sha='b'*40,author=self.author,
            reviewer=self.reviewer,criteria=['A01'],baseline_tests={'tests/test_old.py':'c'*64},
            new_tests=['tests/test_new.py'],product_files=['app.py'],
            protected_files=['AGENTS.md','tests/test_old.py','tests/test_new.py'],
            criterion_tests={'A01':[dict(path='tests/test_new.py',method='test_new')]})
        self.payload=dict(plan=self.plan,contract=self.spec,maintenance_operation=self.operation)
        for name,value in [('native_active',[]),('issue_record',dict(id=self.issue,workspace_id='workspace',
                title='Fixture acceptance',description='Acceptance data: A01 requires new behavior.')),
                           ('issue_task_runs',[])]:
            target=enrollment.maintenance if name=='native_active' else enrollment.native
            p=patch.object(target,name,return_value=value)
            self.addCleanup(p.stop);p.start()

    def test_enrollment_is_durable_immutable_and_grants_nothing(self):
        result=enrollment.enroll(self.b,self.payload)
        self.assertEqual(result['stage'],'enrolled_pending_adapter')
        self.assertEqual(result['repository'],'codifydeep/descartavel2')
        self.assertFalse(result['execution_authorized'])
        self.assertFalse(result['delivery_approval'])
        with self.b.db() as con:
            self.assertEqual(enrollment.lookup(con,self.issue),result)
            self.assertEqual(con.execute('SELECT count(*) FROM grants').fetchone()[0],0)
        with patch.object(enrollment.native,'issue_task_runs',side_effect=AssertionError('no re-enrollment')):
            self.assertEqual(enrollment.enroll(self.b,copy.deepcopy(self.payload)),result)

    def test_restarted_process_reads_same_intent_without_external_replay(self):
        before=enrollment.enroll(self.b,self.payload)
        restarted=SimpleNamespace(**vars(self.b))
        with patch.object(enrollment.native,'issue_record',side_effect=TimeoutError):
            self.assertEqual(enrollment.enroll(restarted,self.payload),before)
        with self.b.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM quality_lifecycle_enrollments').fetchone()[0],1)

    def test_legacy_or_previously_executed_issue_cannot_be_reclassified(self):
        for table,values in [('native_bindings',('req','old-task',self.issue)),
                ('delivery_routes',(self.issue,'{}')),('delivery_handoffs',(self.issue,'blocked')),
                ('contract_revisions',(self.issue,'{}')),('product_scope_runs',(self.issue,'{}'))]:
            with self.subTest(table=table):
                with self.b.db() as con:
                    con.execute('INSERT INTO '+table+' VALUES('+','.join('?' for _ in values)+')',values)
                with self.assertRaises(ValueError):enrollment.enroll(self.b,self.payload)
                with self.b.db() as con:con.execute('DELETE FROM '+table)
        with patch.object(enrollment.native,'issue_task_runs',return_value=[dict(issue_id=self.issue,id='old')]):
            with self.assertRaises(ValueError):enrollment.enroll(self.b,self.payload)

    def test_sealed_exact_maintenance_and_idle_inventory_required(self):
        for mutation in ('released','draining','wrong_namespace','not_drained'):
            with self.subTest(mutation=mutation),self.b.db() as con:
                raw=con.execute('SELECT receipt FROM controller_maintenance').fetchone()[0]
                s=json.loads(raw)
                if mutation=='wrong_namespace':s['namespace']='delivery-kit-other'
                elif mutation=='not_drained':s['drained']=False
                else:s['stage']=mutation
                con.execute('UPDATE controller_maintenance SET stage=?,receipt=?',
                    (s['stage'],json.dumps(s)))
            with self.assertRaises(ValueError):enrollment.enroll(self.b,self.payload)
            with self.b.db() as con:con.execute('UPDATE controller_maintenance SET stage=?,receipt=?',('sealed',raw))
        with patch.object(enrollment.maintenance,'native_active',return_value=['queued']):
            with self.assertRaises(ValueError):enrollment.enroll(self.b,self.payload)
        with self.b.db() as con:con.execute('INSERT INTO leases VALUES(?,?)',('req','closing'))
        with self.assertRaises(ValueError):enrollment.enroll(self.b,self.payload)

    def test_outstanding_capability_prevents_enrollment(self):
        import time
        for used in (0,1):
            with self.b.db() as con:
                con.execute('DELETE FROM grants')
                con.execute('INSERT INTO grants VALUES(?,?,?,?)',('task',used,time.time()+100,'req'))
            with self.subTest(used=used),self.assertRaises(ValueError):enrollment.enroll(self.b,self.payload)

    def test_contract_repository_base_and_roles_cannot_drift(self):
        for field,value in [('contract_sha256','0'*64),('base_sha','0'*40),
                ('author',self.reviewer),('reviewer',self.author)]:
            bad=copy.deepcopy(self.payload);bad['plan'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):enrollment.enroll(self.b,bad)
        bad=copy.deepcopy(self.payload);bad['contract']['repository']='another/repository'
        with self.assertRaises(ValueError):enrollment.enroll(self.b,bad)
        self.b.issue_base.return_value['base_sha']='0'*40
        with self.assertRaises(ValueError):enrollment.enroll(self.b,self.payload)

    def test_existing_identity_or_plan_cannot_be_replaced(self):
        result=enrollment.enroll(self.b,self.payload)
        for field,value in [('criteria',['A02']),('run_id','20000000-0000-4000-8000-000000000002')]:
            bad=copy.deepcopy(self.payload);bad['plan'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):enrollment.enroll(self.b,bad)
        with self.b.db() as con:self.assertEqual(enrollment.lookup(con,self.issue),result)

    def test_duplicate_run_id_cannot_claim_another_issue(self):
        enrollment.enroll(self.b,self.payload)
        bad=copy.deepcopy(self.payload);bad['plan']['issue_id']='20000000-0000-4000-8000-000000000001'
        with self.assertRaises(ValueError):enrollment.enroll(self.b,bad)

    def test_missing_inventory_or_timeout_never_leaves_partial_enrollment(self):
        with patch.object(enrollment.native,'issue_record',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):enrollment.enroll(self.b,self.payload)
        with self.b.db() as con:self.assertIsNone(enrollment.lookup(con,self.issue))
        self.assertEqual(enrollment.enroll(self.b,self.payload)['stage'],'enrolled_pending_adapter')

    def test_legacy_grants_are_refused_only_for_explicitly_enrolled_issue(self):
        with self.b.db() as con:enrollment.require_legacy_issue(con,self.issue)
        enrollment.enroll(self.b,self.payload)
        with self.b.db() as con:
            with self.assertRaises(ValueError):enrollment.require_legacy_issue(con,self.issue)
            enrollment.require_legacy_issue(con,'another-issue')

    def test_corrupt_record_fails_closed(self):
        enrollment.enroll(self.b,self.payload)
        with self.b.db() as con:
            con.execute("UPDATE quality_lifecycle_enrollments SET receipt='{}'")
        with self.b.db() as con,self.assertRaises(ValueError):enrollment.lookup(con,self.issue)

    def test_new_test_and_product_inventory_must_match_portable_contract(self):
        bad=copy.deepcopy(self.payload);bad['plan']['product_files']=['other.py']
        with self.assertRaises(ValueError):enrollment.enroll(self.b,bad)
        bad=copy.deepcopy(self.payload);bad['plan']['protected_files'].remove('AGENTS.md')
        with self.assertRaises(ValueError):enrollment.enroll(self.b,bad)

    def test_concurrent_operators_create_one_durable_enrollment(self):
        second=SimpleNamespace(**{**vars(self.b),'LOCK':threading.RLock()})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda b:enrollment.enroll(b,copy.deepcopy(self.payload)),(self.b,second)))
        self.assertEqual(results[0],results[1])
        with self.b.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM quality_lifecycle_enrollments').fetchone()[0],1)

    def test_slow_native_inventory_never_holds_admission_lock_or_database_writer(self):
        entered=threading.Event();release=threading.Event()
        def slow(*args):
            entered.set()
            if not release.wait(3):raise TimeoutError('test inventory timeout')
            return dict(id=self.issue,workspace_id='workspace')
        with patch.object(enrollment.native,'issue_record',side_effect=slow),ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(enrollment.enroll,self.b,self.payload)
            try:
                self.assertTrue(entered.wait(2))
                acquired=self.b.LOCK.acquire(blocking=False)
                self.assertTrue(acquired,'native observation held global admission lock')
                try:
                    with self.b.db() as con:
                        con.execute('BEGIN IMMEDIATE')
                        self.assertIsNone(enrollment.lookup(con,self.issue))
                finally:
                    if acquired:self.b.LOCK.release()
            finally:release.set()
            self.assertEqual(pending.result()['stage'],'enrolled_pending_adapter')

    def test_base_change_between_inventory_and_commit_is_refused(self):
        def change_base(*args):
            with self.b.db() as con:con.execute("UPDATE issue_bases SET manifest_sha256=?",('0'*64,))
            return []
        with patch.object(enrollment.native,'issue_task_runs',side_effect=change_base):
            with self.assertRaises(ValueError):enrollment.enroll(self.b,self.payload)
        with self.b.db() as con:self.assertIsNone(enrollment.lookup(con,self.issue))

    def server(self):
        import importlib.util,os
        path=Path(__file__).resolve().parents[1]/'broker/server.py'
        spec=importlib.util.spec_from_file_location('quality_enrollment_broker_test',path)
        module=importlib.util.module_from_spec(spec)
        with patch.dict(os.environ,{'BROKER_WORKER_IMAGE':'sha256:'+'a'*64,'BROKER_QUALITY_V2_ENABLED':'0'}):
            spec.loader.exec_module(module)
        for key,value in [('db',self.b.db),('STATE',self.root),('LOCK',self.b.LOCK)]:
            p=patch.object(module,key,value);self.addCleanup(p.stop);p.start()
        return module

    def test_real_native_grant_entrypoint_stops_before_any_legacy_effect(self):
        enrollment.enroll(self.b,self.payload)
        server=self.server()
        binding=dict(task_id=self.run,agent_id=self.author,issue_id=self.issue,scope='scope',mode='implementation')
        import sys
        with patch.dict(sys.modules,{'native':enrollment.native}),\
                patch.object(enrollment.native,'task_binding',return_value=binding),\
                patch.object(server,'issue_base') as base,patch.object(server,'issue_grant') as grant:
            with self.assertRaisesRegex(ValueError,'legacy grants forbidden'):
                server.native_grant(dict(task_id=self.run,agent_id=self.author))
            base.assert_not_called();grant.assert_not_called()

    def test_previously_minted_capability_is_rechecked_at_real_launch_boundary(self):
        import hashlib,time,sys
        enrollment.enroll(self.b,self.payload)
        server=self.server()
        with self.b.db() as con:
            con.execute('DROP TABLE grants');con.execute('DROP TABLE native_bindings')
            con.execute('CREATE TABLE grants(digest TEXT,task_id TEXT,attempt INTEGER,mode TEXT,request_id TEXT,deadline REAL,used INTEGER)')
            con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,scope TEXT,issue_id TEXT)')
            con.execute('INSERT INTO grants VALUES(?,?,?,?,?,?,?)',
                (hashlib.sha256(b'test-capability').hexdigest(),self.run,1,'implementation','req',time.time()+100,0))
            con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',('req',self.run,self.author,'scope',self.issue))
        with patch.dict(sys.modules,{'native':enrollment.native}),\
                patch.object(enrollment.native,'task_binding',return_value={'scope':'scope'}),\
                patch.object(server.controller_maintenance,'require_admission'),\
                patch.object(server,'submit') as submit:
            with self.assertRaisesRegex(ValueError,'legacy grants forbidden'):
                server.execute_grant('test-capability',{})
            submit.assert_not_called()
        with self.b.db() as con:self.assertEqual(con.execute('SELECT used FROM grants').fetchone()[0],0)

    def test_real_legacy_route_registration_refuses_v2_issue(self):
        from broker import handoff_runtime
        enrollment.enroll(self.b,self.payload)
        lead='10000000-0000-4000-8000-000000000006'
        cto='10000000-0000-4000-8000-000000000007'
        self.settings['agents'].update({lead:'planning',cto:'planning'})
        (self.root/'native.json').write_text(json.dumps(self.settings))
        route=dict(issue_id=self.issue,author=self.author,reviewer=self.reviewer,techlead=lead,cto=cto,
            contract_sha256=self.plan['contract_sha256'],review_instruction='Review independently',minimum_calls=4,enabled=True)
        with self.assertRaisesRegex(ValueError,'legacy grants forbidden'):handoff_runtime.register(self.b,route)
        with self.b.db() as con:self.assertEqual(con.execute('SELECT count(*) FROM delivery_routes').fetchone()[0],0)

    def test_legacy_source_pins_admit_only_exact_additive_fences_without_other_changes(self):
        import hashlib,re
        from broker import literal_author_bootstrap_recovery as author,review_context_recovery as review
        source=(Path(__file__).resolve().parents[1]/'broker/server.py').read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(),author.V2_REVIEW_LAUNCH_ROOT_SHA)
        self.assertEqual(author.V2_REVIEW_LAUNCH_ROOT_SHA,review.V2_REVIEW_LAUNCH_SERVER_SHA)
        review_hooks=rb'(?ms)^([ ]*)# BEGIN QUALITY_V2_REVIEW ([a-z_]+)\n.*?^\1# END QUALITY_V2_REVIEW \2\n'
        self.assertEqual([kind.decode() for _,kind in re.findall(review_hooks,source)],
            ['config','native_admission','execute_dispatch','transport_dispatch','running_identity','session_identity','prompt_dispatch'])
        source=re.sub(review_hooks,b'',source)
        self.assertEqual(hashlib.sha256(source).hexdigest(),author.V2_PROGRESS_ROOT_SHA)
        self.assertEqual(author.V2_PROGRESS_ROOT_SHA,review.V2_PROGRESS_SERVER_SHA)
        progress_hook=rb'(?ms)^([ ]*)# BEGIN QUALITY_V2 progress_reconciliation\n.*?^\1# END QUALITY_V2 progress_reconciliation\n'
        self.assertEqual(len(re.findall(progress_hook,source)),1)
        source=re.sub(progress_hook,b'',source)
        self.assertEqual(hashlib.sha256(source).hexdigest(),author.V2_AUTHOR_LAUNCH_ROOT_SHA)
        self.assertEqual(author.V2_AUTHOR_LAUNCH_ROOT_SHA,review.V2_AUTHOR_LAUNCH_SERVER_SHA)
        additions=rb'(?ms)^([ ]*)# BEGIN QUALITY_V2 ([a-z_]+)\n.*?^\1# END QUALITY_V2 \2\n'
        self.assertEqual([kind.decode() for _,kind in re.findall(additions,source)],
            ['launch_config','native_admission','execute_dispatch','transport_dispatch',
             'running_identity','session_identity','prompt_dispatch'])
        source=re.sub(additions,b'',source)
        changed=b"if grant['mode'] == 'implementation' and not current.get('quality_request_id') else None"
        self.assertEqual(source.count(changed),1)
        source=source.replace(changed,b"if grant['mode'] == 'implementation' else None",1)
        self.assertEqual(hashlib.sha256(source).hexdigest(),author.V2_ENROLLMENT_FENCE_ROOT_SHA)
        self.assertEqual(author.V2_ENROLLMENT_FENCE_ROOT_SHA,review.V2_ENROLLMENT_FENCE_SERVER_SHA)
        blocks=[
            b"    try:import quality_lifecycle_enrollment\n"
            b"    except ImportError:from broker import quality_lifecycle_enrollment\n"
            b"    with LOCK, db() as con:\n"
            b"        quality_lifecycle_enrollment.require_legacy_issue(con, binding['issue_id'])\n",
            b"            try:import quality_lifecycle_enrollment\n"
            b"            except ImportError:from broker import quality_lifecycle_enrollment\n"
            b"            quality_lifecycle_enrollment.require_legacy_issue(con, binding['issue_id'])\n",
        ]
        for block in blocks:
            self.assertEqual(source.count(block),1)
            source=source.replace(block,b'',1)
        self.assertEqual(hashlib.sha256(source).hexdigest(),author.AUTHOR_FEEDBACK_STRATEGY_ROOT_SHA)
        self.assertEqual(author.AUTHOR_FEEDBACK_STRATEGY_ROOT_SHA,review.AUTHOR_FEEDBACK_STRATEGY_SERVER_SHA)


if __name__=='__main__':unittest.main()
