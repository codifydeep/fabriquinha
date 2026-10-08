import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import test_product_scope_revision as fixtures
from broker.product_scope_revision import digest,qualify_review
from broker.product_scope_materialize import materialize


class ProductScopeMaterializeTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.ProductScopeRevisionTests();f.setUp()
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)/'base';self.base.mkdir()
        self.target=Path(self.temp.name)/'revision';self.target.mkdir()
        files={'AGENTS.md':b'governance\n','app.py':b'original app\n',
               'app/db.py':b'original facade\n','app/store.py':b'original store\n',
               'tests/test_old.py':b'assert original\n',
               'contract.json':json.dumps(f.original,sort_keys=True,separators=(',',':')).encode()}
        for name,data in files.items():
            p=self.base/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        self.manifest={'base_sha':'a'*40,'files':{name:hashlib.sha256(data).hexdigest() for name,data in files.items()}}
        self.encoded=json.dumps(self.manifest,sort_keys=True,separators=(',',':')).encode()
        (self.base/'manifest.json').write_bytes(self.encoded)
        review=dict(operation='review_product_scope_revision_v1',proposal_sha256=digest(f.proposal),
                    decision='approve',reason='Necessary code scope only.')
        proposal_task=dict(id='cto-task',agent_id='cto',issue_id='issue',status='completed')
        review_task=dict(id='review-task',agent_id='lead',issue_id='issue',status='completed')
        qualification=qualify_review(f.context,f.proposal,review,proposal_task,review_task,f.context['eligible_code_sha256'])
        self.state=dict(stage='plan_approved',author_blocked=True,delivery_approval=False,
            context=f.context,original_contract=f.original,proposal=f.proposal,proposal_sha256=digest(f.proposal),
            proposal_task=proposal_task,review=review,review_task=review_task,qualification=qualification,
            observed_read_hashes=f.context['eligible_code_sha256'])

    def run_materialize(self,state=None):
        return materialize(self.base,self.target,state or self.state,hashlib.sha256(self.encoded).hexdigest())

    def test_only_contract_changes_original_git_base_and_tests_are_preserved(self):
        receipt=self.run_materialize()
        contract=json.loads((self.target/'contract.json').read_bytes())
        manifest=json.loads((self.target/'manifest.json').read_bytes())
        self.assertEqual(manifest['base_sha'],self.manifest['base_sha'])
        self.assertEqual(set(manifest['files']),set(self.manifest['files']))
        for name in self.manifest['files']:
            if name!='contract.json':
                self.assertEqual((self.target/name).read_bytes(),(self.base/name).read_bytes())
                self.assertEqual(manifest['files'][name],self.manifest['files'][name])
        for field in self.state['original_contract'].keys()-{'editable_files','protected_files'}:
            self.assertEqual(contract[field],self.state['original_contract'][field])
        self.assertEqual(receipt['frozen_test_sha256'],self.state['context']['frozen_test_sha256'])
        self.assertFalse(receipt['write_grant_issued']);self.assertFalse(receipt['delivery_approval'])
        self.assertFalse(receipt['historical_red_recreated'])

    def test_resume_is_idempotent_and_conflicting_destination_is_not_overwritten(self):
        receipt=self.run_materialize()
        self.assertEqual(self.run_materialize(),receipt)
        p=self.target/'app/db.py';p.chmod(0o644);p.write_bytes(b'foreign')
        with self.assertRaises(ValueError):self.run_materialize()
        self.assertEqual(p.read_bytes(),b'foreign')

    def test_invalid_review_or_source_is_rejected_before_any_copy(self):
        for mutation in ({'stage':'awaiting_review'},{'author_blocked':False},
                         {'qualification':dict(self.state['qualification'],write_grant_issued=True)},
                         {'review':dict(self.state['review'],proposal_sha256='0'*64)}):
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                self.run_materialize(dict(self.state,**mutation))
            self.assertEqual(list(self.target.iterdir()),[])
        (self.base/'app/db.py').write_bytes(b'modified baseline')
        with self.assertRaises(ValueError):self.run_materialize()
        self.assertEqual(list(self.target.iterdir()),[])

    def test_source_or_destination_symlink_cannot_escape_the_selected_volume(self):
        (self.target/'app').symlink_to(self.base/'app',target_is_directory=True)
        with self.assertRaises(ValueError):self.run_materialize()
        self.assertEqual((self.base/'app/db.py').read_bytes(),b'original facade\n')

    def test_interrupted_pending_file_is_completed_before_atomic_publication(self):
        parent=self.target/'app';parent.mkdir()
        pending=parent/'.db.py.scope-pending';pending.write_bytes(b'original fac')
        result=self.run_materialize()
        self.assertEqual((parent/'db.py').read_bytes(),b'original facade\n')
        self.assertFalse(pending.exists())
        self.assertEqual(self.run_materialize(),result)

    def test_completed_pending_ack_and_corrupt_pending_are_not_overwritten(self):
        parent=self.target/'app';parent.mkdir()
        pending=parent/'.db.py.scope-pending';pending.write_bytes(b'original facade\n')
        pending.chmod(0o444)
        self.run_materialize()
        self.assertFalse(pending.exists())
        pending.write_bytes(b'foreign data')
        with self.assertRaises(ValueError):self.run_materialize()
        self.assertEqual(pending.read_bytes(),b'foreign data')
