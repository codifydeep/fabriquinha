import hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from product_pr_review import PRReview

class PRReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);(root/'pr-packets').mkdir()
        self.packet=dict(pr=22,head='a'*40,base='b'*40,ci=dict(event='pull_request',head_sha='a'*40,conclusion='success'))
        raw=json.dumps(self.packet).encode();self.rev=hashlib.sha256(raw).hexdigest()
        (root/'pr-packets/t.json').write_bytes(raw)
        binding=Mock(return_value=dict(task='t',run=2,profile='cto',attempt='real',mode='review'))
        binding.cards={'t':dict(author='techlead',packet_sha256=self.rev)}
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.service=PRReview(root,binding,None,self.db);self.service.deliver=Mock(side_effect=lambda e:e)
        self.req=dict(task='t',run=2,claim='c',attempt='real',operation='product_verdict',revision=self.rev,decision='approve',reason='Verified exact source tree, parent history and passing real CI.')
    def test_independent_exact_packet(self):
        result=self.service.handle(self.req)
        self.assertEqual(result['reviewer'],'cto');self.assertFalse(result['merge_authorized'])
    def test_stale_revision_denied(self):
        with self.assertRaises(PermissionError):self.service.handle(dict(self.req,revision='old'))
    def test_write_denied(self):
        with self.assertRaises(PermissionError):self.service.handle(dict(self.req,operation='product_edit'))
    def test_conflict_denied(self):
        self.service.handle(self.req)
        with self.assertRaises(PermissionError):self.service.handle(dict(self.req,decision='request_changes'))
    def test_wrong_ci_denied_without_persisting(self):
        self.service.packet=Mock(return_value=(dict(self.packet,ci=dict(event='workflow_dispatch',head_sha='a'*40,conclusion='success')),self.rev))
        with self.assertRaises(PermissionError):self.service.handle(self.req)
        self.assertEqual(self.db.execute('select count(*) from product_pr_verdicts').fetchone()[0],0)
