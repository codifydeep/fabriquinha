from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from immutable_delivery import DeliveryStore

class ImmutableTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.work=self.root/'work'; self.work.mkdir()
        (self.work/'score.py').write_text('original')
        self.store=DeliveryStore(self.root/'private')
        self.kw=dict(attempt='attempt1',task='t_one',author='backend_data',run=1)

    def test_snapshot_survives_author_changes(self):
        revision=self.store.capture(self.work,**self.kw)
        (self.work/'score.py').write_text('changed')
        self.assertEqual((self.store.path('attempt1','t_one',revision)/'files/score.py').read_text(),'original')
        diff=self.store.differences('attempt1','t_one',revision,self.work)
        self.assertEqual(diff[0]['category'],'delivery_changed')
        self.assertNotEqual(diff[0]['actual'],diff[0]['expected'])

    def test_restart_capture_is_idempotent(self):
        first=self.store.capture(self.work,**self.kw)
        store=DeliveryStore(self.root/'private')
        self.assertEqual(first,store.capture(self.work,**self.kw))

    def test_new_execution_has_new_revision(self):
        first=self.store.capture(self.work,**self.kw)
        self.kw['run']=2
        self.assertNotEqual(first,self.store.capture(self.work,**self.kw))

    def test_symlink_cannot_capture_external_files(self):
        (self.work/'link').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError,'symlink'): self.store.capture(self.work,**self.kw)

    def test_corrupt_snapshot_is_rejected(self):
        revision=self.store.capture(self.work,**self.kw)
        path=self.store.path('attempt1','t_one',revision)/'files/score.py'
        path.chmod(0o600); path.write_text('tampered')
        with self.assertRaisesRegex(ValueError,'corrupt'): self.store.load('attempt1','t_one',revision)
