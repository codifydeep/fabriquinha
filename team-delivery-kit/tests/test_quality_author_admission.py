"""Isolated native-provenance fixtures, not installed/native qualification."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import unittest
from unittest.mock import patch

from broker import quality_author_admission as author
import test_quality_lifecycle_enrollment as fixtures


class AuthorAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.QualityEnrollmentTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.b=self.f.b;self.e=author.enrollment.enroll(self.b,self.f.payload)
        self.task='50000000-0000-4000-8000-000000000001'
        self.record=dict(id=self.task,agent_id=self.f.author,issue_id=self.f.issue,status='running',
            workspace_id=self.f.settings['workspace_id'],runtime_id=self.f.settings['runtime_id'])
        with self.b.db() as con:
            con.execute('DELETE FROM controller_maintenance')
            con.execute('DROP TABLE native_bindings');con.execute('DROP TABLE grants')
            con.execute('CREATE TABLE native_bindings(request_id TEXT PRIMARY KEY,task_id TEXT,agent_id TEXT,scope TEXT,issue_id TEXT)')
            con.execute('CREATE TABLE grants(digest TEXT PRIMARY KEY,task_id TEXT,attempt INTEGER,mode TEXT,'
                'request_id TEXT,deadline REAL,used INTEGER,UNIQUE(task_id,attempt))')
        for name,value in [('task_record',self.record),('issue_task_runs',[self.record])]:
            p=patch.object(author.native,name,return_value=value);self.addCleanup(p.stop);p.start()

    def call(self):return author.admit(self.b,self.task,self.f.author,now=100)

    def count(self,table):
        with self.b.db() as con:return con.execute('SELECT count(*) FROM '+table).fetchone()[0]

    def test_atomically_binds_single_capability_and_tests_only_phase(self):
        grant=self.call()
        with self.b.db() as con:
            c=author.load(con,grant['request_id'])
            digest=con.execute('SELECT digest FROM grants').fetchone()[0]
        self.assertEqual(digest,hashlib.sha256(grant['capability'].encode()).hexdigest())
        self.assertNotIn(grant['capability'],json.dumps(c))
        self.assertEqual(c['scope'].split(':')[-1],self.task)
        selected=author.selection(self.b,grant['request_id'])
        self.assertEqual(selected['editable_paths'],['/workspace/tests/test_new.py'])
        self.assertEqual(selected['test_commands'],[])
        for k in ('product_edits_allowed','terminal_allowed','legacy_calibration_allowed','delivery_approval'):
            self.assertFalse(selected[k])
        from quality_phase_tools import validate
        config=author.tool_config(self.b,grant['request_id'])
        validate(config,grant['request_id'])
        self.assertEqual(config['editable_paths'],selected['editable_paths'])

    def test_duplicate_or_lost_capability_response_cannot_mint_another_attempt(self):
        grant=self.call()
        for _ in range(2):
            with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.count('grants'),1)
        self.assertEqual(self.count('quality_native_scopes'),1)
        self.assertEqual(author.selection(self.b,grant['request_id'])['phase'],'tests_only_v2')

    def test_non_author_wrong_issue_or_nonrunning_task_is_not_admitted(self):
        for field,value in [('agent_id',self.f.reviewer),('status','completed'),
                ('issue_id','50000000-0000-4000-8000-000000000002'),('runtime_id','other')]:
            with self.subTest(field=field),patch.object(author.native,'task_record',return_value={**self.record,field:value}):
                with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.count('grants'),0)

    def test_prior_native_task_cannot_be_implicitly_retried_or_converted(self):
        for runs in ([],[self.record,{**self.record,'id':self.f.run}]):
            with patch.object(author.native,'issue_task_runs',return_value=runs):
                with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.count('grants'),0)

    def test_sealed_maintenance_refuses_all_three_authority_inserts(self):
        with self.b.db() as con:
            state=dict(namespace=self.b.PREFIX,stage='sealed',operation_id=self.f.operation)
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',
                (self.f.operation,'sealed',json.dumps(state)))
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.count('grants'),0);self.assertEqual(self.count('native_bindings'),0)

    def test_native_timeout_or_changed_base_does_not_leave_partial_grant(self):
        with patch.object(author.native,'issue_task_runs',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):self.call()
        self.b.issue_base.return_value['manifest_sha256']='0'*64
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.count('grants'),0)

    def test_global_two_slot_limit_counts_unconsumed_reservations(self):
        with self.b.db() as con:
            for n in (1,2):con.execute('INSERT INTO grants VALUES(?,?,?,?,?,?,?)',
                (str(n),'other-'+str(n),1,'implementation','other-'+str(n),200,0))
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.count('grants'),2)

    def test_one_slot_per_agent_even_when_global_slot_is_available(self):
        with self.b.db() as con:
            con.execute('INSERT INTO grants VALUES(?,?,?,?,?,?,?)',('other','other',1,'implementation','other',200,0))
            con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',('other','other',self.f.author,'other','other'))
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.count('grants'),1)

    def test_mutated_phase_or_context_cannot_expand_worker_editables(self):
        grant=self.call()
        with self.b.db() as con:con.execute("UPDATE quality_native_scopes SET phase='implementation'")
        with self.assertRaises(ValueError):author.selection(self.b,grant['request_id'])
        with self.b.db() as con:con.execute("UPDATE quality_native_scopes SET phase='tests_only_v2'")
        with self.b.db() as con:
            raw=json.loads(con.execute('SELECT context FROM quality_author_admissions').fetchone()[0])
            raw['base']['volume']='attacker'
            con.execute('UPDATE quality_author_admissions SET context=?',(json.dumps(raw),))
        with self.assertRaises(ValueError):author.selection(self.b,grant['request_id'])

    def test_consumed_capability_without_observable_lease_does_not_free_capacity(self):
        with self.b.db() as con:
            con.execute('INSERT INTO grants VALUES(?,?,?,?,?,?,?)',('other','other',1,'implementation','other',0,1))
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.count('grants'),1)

    def test_concurrent_admission_mints_only_one_capability(self):
        def attempt(_):
            try:return self.call()
            except ValueError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,range(2)))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(self.count('grants'),1)

    def test_selection_enforces_tests_only_through_actual_acp_permission_handler(self):
        from broker.acp_transport import permission_response
        grant=self.call();selected=author.selection(self.b,grant['request_id'])
        options=[dict(kind='allow_once',optionId='allow_once'),dict(kind='reject_once',optionId='reject_once')]
        for path,expected in [('/workspace/tests/test_new.py','allow_once'),
                ('/workspace/app.py','reject_once'),('/workspace/tests/test_old.py','reject_once')]:
            request=dict(id=1,params=dict(options=options,toolCall=dict(kind='edit',title='Approve edit: '+path,
                rawInput=dict(path=path),content=[dict(type='diff',path=path)])))
            result=permission_response(request,'implementation',frozenset(selected['editable_paths']),
                frozenset(selected['test_commands']))
            self.assertEqual(result['result']['outcome']['optionId'],expected)
        request=dict(id=2,params=dict(options=options,toolCall=dict(kind='execute',title='shell sh',rawInput=dict(command='sh'))))
        result=permission_response(request,'implementation',frozenset(selected['editable_paths']),frozenset())
        self.assertEqual(result['result']['outcome']['optionId'],'reject_once')

    def test_transaction_failure_rolls_back_grant_binding_and_phase(self):
        with self.b.db() as con:
            author.initialize(con)
            con.execute("CREATE TRIGGER reject_phase BEFORE INSERT ON quality_native_scopes "
                "BEGIN SELECT RAISE(ABORT,'test failure'); END")
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):self.call()
        for table in ('grants','native_bindings','quality_native_scopes','quality_author_admissions'):
            self.assertEqual(self.count(table),0)

    def test_consumed_closed_admission_is_the_exact_source_expected_by_red_ingestion(self):
        grant=self.call()
        with self.b.db() as con:
            con.execute('UPDATE grants SET used=1 WHERE request_id=?',(grant['request_id'],))
            con.execute('INSERT INTO leases VALUES(?,?)',(grant['request_id'],'closed'))
            source=author.capture.source(con,self.task)
        self.assertEqual(source['request_id'],grant['request_id'])
        self.assertEqual(source['run_id'],self.f.run)
        self.assertEqual(source['plan_sha256'],author.quality.digest(self.f.plan))
        self.assertEqual(source['agent_id'],self.f.author)


if __name__=='__main__':unittest.main()
