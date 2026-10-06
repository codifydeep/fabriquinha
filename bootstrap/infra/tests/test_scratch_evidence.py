import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scratch_evidence import snapshot
from scratch_validation import verify_registered
from delivery_receipts import EvidenceStore

class ScratchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board=Path(self.tmp.name)/'board'
        self.work=self.board/'workspaces/t_123abc'
        self.work.mkdir(parents=True)
        self.db=sqlite3.connect(self.board/'kanban.db')
        self.db.row_factory=sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE task_events(id INTEGER PRIMARY KEY,task_id TEXT,kind TEXT,payload TEXT)')
        self.db.execute('INSERT INTO task_events VALUES(1,?,?,?)',('t_123abc','review_requested',json.dumps(dict(implementer='backend_data',reviewer='techlead'))))
        (self.work/'test_score.py').write_text('original regression')
        sha=hashlib.sha256((self.work/'test_score.py').read_bytes()).hexdigest()
        (self.board/'validation-contracts.json').write_text(json.dumps({'t_123abc':dict(regression_sha256=sha,minimum_tests=6,implementer='backend_data')}))
        self.report=dict(task='t_123abc',stage='scratch-validation',deployment_performed=False,
            regression_sha256=sha,tests_run=6,red_failures=4)
        self.write_report()
        (self.work/'red.log').write_text('Ran 6 tests in 0.001s\n\nFAILED (failures=4)\n')
        (self.work/'green.log').write_text('Ran 6 tests in 0.001s\n\nOK\n')

    def write_report(self):
        (self.work/'validation-result.json').write_text(json.dumps(self.report))

    def verify(self):
        verify_registered(self.db,'t_123abc',dict(workspace_path=str(self.work)))

    def test_archived_bytes_survive_original_removal(self):
        digest=snapshot(self.db,'t_123abc',self.work)
        (self.work/'red.log').unlink()
        receipt=EvidenceStore(self.board/'evidence','t_123abc').load(digest)
        self.assertEqual(len(receipt['artifacts']),4)

    def test_empty_file_is_preserved_in_manifest(self):
        (self.work/'empty').touch()
        digest=snapshot(self.db,'t_123abc',self.work)
        self.assertEqual(EvidenceStore(self.board/'evidence','t_123abc').load(digest)['empty_files'],['empty'])

    def test_symlink_refuses_cleanup_archive(self):
        (self.work/'link').symlink_to(self.board/'kanban.db')
        with self.assertRaises(ValueError): snapshot(self.db,'t_123abc',self.work)

    def test_report_matches_actual_counts(self): self.verify()

    def test_seven_claimed_when_six_executed_is_rejected(self):
        self.report['tests_run']=7
        self.write_report()
        with self.assertRaisesRegex(ValueError,'expected 6'): self.verify()

    def test_fictitious_deployment_is_rejected(self):
        self.report['deployment_performed']=True
        self.write_report()
        with self.assertRaisesRegex(ValueError,'deployment'): self.verify()

    def test_green_is_not_valid_red(self):
        (self.work/'red.log').write_text((self.work/'green.log').read_text())
        with self.assertRaisesRegex(ValueError,'failed Red'): self.verify()

    def test_regression_mutation_is_rejected(self):
        (self.work/'test_score.py').write_text('weakened')
        with self.assertRaisesRegex(ValueError,'regression'): self.verify()

    def prepare_parent(self):
        parent=self.board/'workspaces/t_parent'
        parent.mkdir()
        self.db.execute('CREATE TABLE tasks(id TEXT, status TEXT, workspace_path TEXT)')
        self.db.execute('INSERT INTO tasks VALUES(?,?,?)',('t_parent','done',str(parent)))
        for name in ['score.py','test_new_score.py']:
            (self.work/name).write_text('original '+name)
        for name in ['score.py','test_score.py','test_new_score.py','red.log','green.log']:
            (parent/name).write_bytes((self.work/name).read_bytes())
        (self.work/'qa.log').write_bytes((self.work/'green.log').read_bytes())
        path=self.board/'validation-contracts.json'
        contracts=json.loads(path.read_text())
        contracts['t_123abc']['parent']='t_parent'
        path.write_text(json.dumps(contracts))

    def test_exact_parent_and_independent_qa_pass(self):
        self.prepare_parent()
        self.verify()

    def test_qa_cannot_rewrite_parent_tests(self):
        self.prepare_parent()
        (self.work/'test_new_score.py').write_text('rewritten')
        with self.assertRaisesRegex(ValueError,'exact parent'): self.verify()

    def test_qa_cannot_run_partial_suite(self):
        self.prepare_parent()
        (self.work/'qa.log').write_text('Ran 1 test in 0.001s\n\nOK\n')
        with self.assertRaisesRegex(ValueError,'full-suite'): self.verify()
