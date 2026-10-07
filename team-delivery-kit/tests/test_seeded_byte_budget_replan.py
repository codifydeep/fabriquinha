import hashlib,json,sqlite3,unittest
import tempfile,threading
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
from unittest.mock import patch
from broker.seeded_byte_budget_replan import initialize,qualified,verify_proof


class SeededByteBudgetTests(unittest.TestCase):
    def test_only_exact_preserved_owned_canonical_near_capacity_file_qualifies(self):
        scope='scope';volume='delivery-kit-port2-work-'+hashlib.sha256(scope.encode()).hexdigest()[:32]
        proof=dict(volume=volume,bytes=32683,sha256='a'*64,regular=True,canonical=True,owner=0,nlink=1,writable_mode=True)
        verify_proof(proof,'a'*64,scope,'delivery-kit-port2')
        for change in (dict(bytes=32769),dict(bytes=1000),dict(sha256='b'*64),dict(owner=10000),
                       dict(volume='foreign'),dict(canonical=False),dict(nlink=2),dict(writable_mode=False)):
            with self.assertRaises(ValueError):verify_proof({**proof,**change},'a'*64,scope,'delivery-kit-port2')

    def test_prose_cannot_grant_replan_and_source_receipt_is_exact(self):
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        self.assertFalse(qualified(con,'issue','source',{'byte_budget_replan':{'claimed':True}}))
        initialize(con);receipt=dict(operation='preserved_seed_byte_budget_replan_v1',delivery_approval=False)
        con.execute('INSERT INTO seeded_byte_budget_replans VALUES(?,?,?)',('issue','source',json.dumps(receipt)))
        self.assertTrue(qualified(con,'issue','source',dict(byte_budget_replan=receipt)))
        self.assertFalse(qualified(con,'issue','other',dict(byte_budget_replan=receipt)))
        self.assertFalse(qualified(con,'issue','source',dict(byte_budget_replan={**receipt,'delivery_approval':True})))

    def test_registration_keeps_original_failure_and_requires_actual_tool_rejections(self):
        from broker import seeded_byte_budget_replan as module,native,handoffs,remediation_runtime_guard as guard
        con=sqlite3.connect(':memory:');self.addCleanup(con.close);con.row_factory=sqlite3.Row
        handoffs.initialize(con)
        con.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
        con.execute('CREATE TABLE native_bindings(task_id TEXT,issue_id TEXT,agent_id TEXT,request_id TEXT,scope TEXT)')
        con.execute('CREATE TABLE test_first_red(issue_id TEXT)')
        route=dict(author='author',cto='cto',enabled=True)
        con.execute('INSERT INTO delivery_routes(issue_id,config) VALUES(?,?)',('issue',json.dumps(route)))
        con.execute("INSERT INTO leases VALUES('req','closed')")
        con.execute("INSERT INTO native_bindings VALUES('source','issue','author','req','scope')")
        old=dict(phase='test_first',error='test_first_correction_failed_after_cto_diagnosis',source_task='source')
        handoffs.save(con,'source','issue','test_first_blocked','cto',old,0)
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory);(state/'native.json').write_text('{}')
            @contextmanager
            def db():yield con
            b=SimpleNamespace(db=db,LOCK=threading.RLock(),STATE=state,PREFIX='delivery-kit-port2',OWNER='owned',
                docker=lambda *args:dict(Labels={'delivery-kit.owner':'owned','delivery-kit.scope':'scope'}))
            volume='delivery-kit-port2-work-'+hashlib.sha256(b'scope').hexdigest()[:32]
            proof=dict(volume=volume,bytes=32683,sha256='a'*64,regular=True,canonical=True,owner=0,nlink=1,writable_mode=True)
            value=dict(amendment={'operation':'fixed'},previous_new_test_delivery=dict(test_sha256={'tests/test_new.py':'a'*64}))
            task=dict(id='source',agent_id='author',issue_id='issue',status='failed',created_at='1')
            outputs=[dict(type='tool_result',tool='patch',output='patch failed for /workspace/tests/test_new.py: Failed to write changes: Failed to write file: invalid fenced write target or size')]*2
            with patch.object(guard,'qualified',return_value=value),patch.object(native,'task_record',return_value=task),\
                 patch.object(native,'issue_task_runs',return_value=[task]),patch.object(native,'task_messages',return_value=outputs) as messages:
                messages.return_value=[]
                with self.assertRaises(ValueError):module.register(b,'source',proof)
                messages.return_value=outputs
                receipt=module.register(b,'source',proof)
                self.assertEqual(receipt['previous'],old)
                self.assertFalse(receipt['author_retry_authorized'])
                self.assertFalse(receipt['revision_depth_reset'])
                self.assertEqual(module.register(b,'source',proof),receipt)
                row=con.execute('SELECT stage,data FROM delivery_handoffs WHERE source_task=?',('source',)).fetchone()
                self.assertEqual(row[0],'technical_decision_required')
                self.assertTrue(module.qualified(con,'issue','source',json.loads(row[1])))
