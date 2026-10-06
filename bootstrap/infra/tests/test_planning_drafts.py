import sqlite3
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from planning_drafts import initialize,save,edit,digest

class DraftTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:'); self.db.row_factory=sqlite3.Row; self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE planning_drafts(task TEXT PRIMARY KEY,run INTEGER,content TEXT)')
        initialize(self.db)
    def test_patch_and_adopt_preserve_history(self):
        save(self.db,'t',1,'Original text','write')
        result=edit(self.db,'t',2,digest('Original text'),[dict(old='Original',new='Updated')])
        self.assertEqual(result['sha256'],digest('Updated text'))
        self.assertEqual(self.db.execute('SELECT run FROM planning_drafts').fetchone()[0],2)
        self.assertTrue(self.db.execute('SELECT 1 FROM planning_draft_history WHERE content=?',('Original text',)).fetchone())
    def test_stale_and_ambiguous_patches_rejected(self):
        save(self.db,'t',1,'same same','write')
        with self.assertRaises(ValueError): edit(self.db,'t',2,'0'*64,[])
        with self.assertRaises(ValueError): edit(self.db,'t',2,digest('same same'),[dict(old='same',new='x')])
    def test_bounded_writes_and_exact_adoption(self):
        save(self.db,'t',1,'one','write')
        edit(self.db,'t',2,digest('one'),[])
        save(self.db,'t',2,'two','write');save(self.db,'t',2,'three','write')
        with self.assertRaises(ValueError): save(self.db,'t',2,'four','write')
        self.assertEqual(self.db.execute('SELECT content FROM planning_drafts').fetchone()[0],'three')
