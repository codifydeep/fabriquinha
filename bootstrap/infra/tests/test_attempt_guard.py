import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from attempt_guard import validate_mutation
from coordination_store import CoordinationStore


class AttemptGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        board=self.root/'board2'
        board.mkdir()
        self.db=sqlite3.connect(board/'kanban.db')
        self.addCleanup(self.db.close)
        self.execution=self.root/'execution.json'
        self.execution.write_text(json.dumps(dict(board='board2',attempt='r2',product_dispatch_enabled=False,rehearsal_passed=False)))
        (board/'board.json').write_text(json.dumps(dict(execution_attempt='r2')))
        self.store=CoordinationStore(self.root/'coordination.db')
        self.addCleanup(self.store.close)
        self.store.create_attempt('r2','board2','v0.1')

    def test_product_mutation_refused_before_rehearsal(self):
        with self.assertRaises(PermissionError):
            validate_mutation(self.db,self.execution)

    def test_read_only_cannot_be_bypassed_by_cli(self):
        (self.root/'board2'/'READ_ONLY').touch()
        with self.assertRaises(PermissionError):
            validate_mutation(self.db,self.execution)

    def test_wrong_generation_refused_even_after_enable(self):
        self.execution.write_text(json.dumps(dict(board='board2',attempt='r3',product_dispatch_enabled=True,rehearsal_passed=True)))
        with self.assertRaises(PermissionError):
            validate_mutation(self.db,self.execution)

    def test_matching_rehearsed_generation_allowed(self):
        self.execution.write_text(json.dumps(dict(board='board2',attempt='r2',product_dispatch_enabled=True,rehearsal_passed=True)))
        validate_mutation(self.db,self.execution)

    def test_terminal_ledger_blocks_even_if_enable_flags_are_stale(self):
        self.execution.write_text(json.dumps(dict(board='board2',attempt='r2',product_dispatch_enabled=True,rehearsal_passed=True)))
        self.store.transition('r2','EM_DESCOBERTA','CANCELADA_PELO_CEO','ceo',{'reason':'test'})
        with self.assertRaisesRegex(PermissionError,'terminal'):
            validate_mutation(self.db,self.execution)
