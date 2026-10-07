import copy
import unittest
from broker.inherited_test_replan import proposal


class InheritedTestReplanTests(unittest.TestCase):
    def fixture(self):
        route=dict(issue_id='r2',cto='cto',techlead='lead',author='author',reviewer='reviewer')
        reference=dict(issue_id='r2',origin_issue='r1',original_depth=2,run_id='run',
            execution_contract_sha256='a'*64,criteria={'A01':'entire criterion'},
            readonly_tests=['tests/test_new.py'],editable_files=['app.js'],
            red=dict(task_id='red-task',red=dict(manifest_sha256='b'*64)))
        failure=dict(category='executed_test_failure',source_task='source',exit_code=1,
                     output_sha256='c'*64,tests_executed=323,failures=[dict(qualified_name='tests.test_new.Case.test_probe')])
        data=dict(source_task='source',target='cto',recipient_task='cto-task',wakeup_id='wake',
            validation_failure=failure,failed_execution_diagnostic=dict(status='diagnostic_only_not_approved',failure=failure))
        task=dict(id='cto-task',agent_id='cto',issue_id='r2',status='completed',wakeup_id='wake')
        decision=dict(action='request_test_revision',optional_files=[],reason='Investigate the harness from source.')
        reads={p:dict(lines=10,total_lines=10) for p in ('/evidence/candidate/app.js','/evidence/candidate/tests/test_new.py')}
        return route,reference,data,task,decision,reads

    def test_proposal_keeps_origin_depth_and_all_criteria_without_edit_authority(self):
        value=proposal(*self.fixture())
        self.assertEqual(value['original_depth'],2);self.assertEqual(value['origin_issue'],'r1')
        self.assertEqual(value['criteria'],{'A01':'entire criterion'})
        for flag in ('execution_authorized','test_edits_authorized','release_homologated','revision_depth_reset'):
            self.assertFalse(value[flag])

    def test_incomplete_or_foreign_decision_cannot_sponsor_replan(self):
        for slot,key,value in [(3,'agent_id','author'),(3,'wakeup_id','old'),(3,'status','failed'),
                               (1,'origin_issue','r2'),(1,'original_depth',0),(4,'optional_files',['test_new.py'])]:
            args=list(copy.deepcopy(self.fixture()));args[slot][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):proposal(*args)
        args=list(self.fixture());args[-1]={}
        with self.assertRaises(ValueError):proposal(*args)

    def test_missing_functional_evidence_cannot_turn_failed_execution_into_test_permission(self):
        args=list(copy.deepcopy(self.fixture()));args[2]['validation_failure']['exit_code']=0
        with self.assertRaises(ValueError):proposal(*args)

    def test_unknown_ack_is_observed_and_peer_review_cannot_grant_execution(self):
        import json,sqlite3,tempfile
        from pathlib import Path
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import patch
        from broker import inherited_test_replan as module,handoffs
        route,reference,data,task,decision,reads=self.fixture()
        value=proposal(route,reference,data,task,decision,reads)
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        handoffs.initialize(con);module.initialize(con)
        con.execute('CREATE TABLE leases(status TEXT)')
        con.execute('INSERT INTO delivery_routes VALUES (?,?)',('r2',json.dumps({**route,'enabled':True,'minimum_calls':32})))
        data.update(inherited_test_replan=value,artifact_diagnosis=True)
        handoffs.save(con,'source','r2','inherited_replan_required','lead',data,0)
        con.execute('INSERT INTO inherited_test_replans VALUES(?,?,?)',('source',json.dumps(value),json.dumps(dict(stage='peer_review_required',at=0))))
        calls=[]
        def wake(*args,**kwargs):
            calls.append(kwargs['allow_create'])
            if len(calls)==1:raise TimeoutError('uncertain acknowledgement')
            return dict(id='peer-wake')
        fx=SimpleNamespace(remaining_calls=lambda:64,implementation_available=lambda *a:True,
            ensure_wakeup=wake,decision=lambda t:decision,read_evidence=lambda t:reads)
        @contextmanager
        def db():yield con
        with tempfile.TemporaryDirectory() as root:
            Path(root,'native.json').write_text('{}')
            b=SimpleNamespace(db=db,STATE=Path(root),LOCK=__import__('threading').RLock())
            with patch.object(module.references,'qualified',return_value=reference),patch.object(module.handoff_runtime,'Effects',return_value=fx),patch.object(module.native,'issue_task_runs',return_value=[]):
                module.tick(b);module.tick(b)
                self.assertEqual(calls,[True,False])
                # Simulate a crash before saving the accepted wakeup pointers.
                stale=dict(data,target='cto',wakeup_id='wake')
                handoffs.save(con,'source','r2','inherited_replan_required','lead',stale,1)
                module.tick(b)
                fixed=json.loads(handoffs.load(con,'source')['data'])
                self.assertEqual(fixed['target'],'lead');self.assertEqual(fixed['wakeup_id'],'peer-wake')
                self.assertEqual(calls,[True,False])
            with patch.object(module.references,'qualified',return_value=reference),patch.object(module.handoff_runtime,'Effects',return_value=fx),patch.object(module.native,'issue_task_runs',return_value=[dict(id='peer-task',agent_id='lead',wakeup_id='peer-wake',status='completed')]):
                module.tick(b)
            state=json.loads(con.execute('SELECT state FROM inherited_test_replans').fetchone()[0])
            self.assertEqual(state['stage'],'peer_reviewed');self.assertFalse(state['execution_authorized'])
            self.assertEqual(handoffs.load(con,'source')['stage'],'inherited_replan_required')
        con.close()

    def test_format_recovery_preserves_failed_attempt_and_is_once_per_source(self):
        import json,sqlite3,tempfile,threading
        from pathlib import Path
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import patch
        from broker import inherited_test_replan as module,handoffs
        route,reference,data,task,decision,reads=self.fixture();value=proposal(route,reference,data,task,decision,reads)
        state=dict(stage='blocked',task_id='peer-task',wakeup_id='peer-wake')
        data.update(inherited_peer_review=state,inherited_test_replan=value)
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        handoffs.initialize(con);module.initialize(con)
        con.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
        con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,issue_id TEXT)')
        con.execute("INSERT INTO leases VALUES('request','closed')")
        con.execute("INSERT INTO native_bindings VALUES('request','peer-task','lead','r2')")
        con.execute('INSERT INTO inherited_test_replans VALUES(?,?,?)',('source',json.dumps(value),json.dumps(state)))
        handoffs.save(con,'source','r2','inherited_replan_required','cto',data,0)
        rejection=dict(operation='rejected_typed_decision_adapter_v1',category='typed_mixed_content',
            execution_id='request',upstream_sha256='d'*64,delivery_approval=False,worker_tool_executed=False,
            response_shape=dict(parsed=True,submissions=0,legacy_function_call=False,content_shape='nonempty',content_chars=760))
        peer=dict(id='peer-task',status='failed',wakeup_id='peer-wake',issue_id='r2')
        @contextmanager
        def db():yield con
        with tempfile.TemporaryDirectory() as root:
            Path(root,'native.json').write_text('{}')
            b=SimpleNamespace(db=db,STATE=Path(root),LOCK=threading.RLock())
            fx=SimpleNamespace(read_evidence=lambda t:reads)
            with patch.object(module.handoff_runtime,'Effects',return_value=fx),patch.object(module.native,'task_record',return_value=peer),patch.object(module.native,'issue_task_runs',return_value=[]):
                for change in (dict(execution_id='foreign'),dict(response_shape={**rejection['response_shape'],'submissions':1})):
                    with self.assertRaises(ValueError):module.recover_format(b,'source',{**rejection,**change})
                first=module.recover_format(b,'source',rejection)
                second=module.recover_format(b,'source',rejection)
            self.assertEqual(first,second);self.assertEqual(first['previous_state'],state)
            current=json.loads(con.execute('SELECT state FROM inherited_test_replans').fetchone()[0])
            self.assertEqual(current['stage'],'peer_review_required')
            self.assertNotEqual(current['recovery_marker'],module.digest(value))
            self.assertFalse(first['test_edits_authorized']);self.assertFalse(first['revision_depth_reset'])
            self.assertEqual(con.execute('SELECT count(*) FROM inherited_peer_format_recoveries').fetchone()[0],1)
        con.close()
