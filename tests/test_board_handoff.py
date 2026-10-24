import contextlib
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.board import Board


class ClosedParentHandoff(unittest.TestCase):
    def test_change_request_persists_its_exact_review_receipt(self):
        captured = {}
        def request_changes(_, task, *, reason, expected_run_id):
            captured.update(task=task, reason=reason, run=expected_run_id)
            return True, 'author'
        kb = SimpleNamespace(request_changes=request_changes)
        kbc = SimpleNamespace(connect_closing=lambda: contextlib.nullcontext(None))
        board = Board(None)
        run = SimpleNamespace(task='task', number=4, reviewing=True)
        with patch.object(board, 'ensure'), patch('fabriquinha.board.native', return_value=(kb,kbc,None)):
            board.finish_review(run, 'Fix the assertion', {'review':'exact-review'}, changes=True)
        self.assertEqual(json.loads(captured['reason']),
                         dict(summary='Fix the assertion', evidence={'review':'exact-review'}))
        self.assertEqual(captured['run'], 4)

    def test_completed_parent_has_no_current_run_but_keeps_its_handoff(self):
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        conn.executescript('CREATE TABLE task_links(parent_id,child_id);'
            'CREATE TABLE task_runs(id,task_id,outcome,metadata);'
            'CREATE TABLE task_events(task_id,run_id,kind);')
        conn.execute('INSERT INTO task_links VALUES(?,?)', ('parent','child'))
        conn.execute('INSERT INTO task_runs VALUES(?,?,?,?)', (4,'parent','completed',json.dumps({'tests':'frozen-evidence'})))
        conn.execute('INSERT INTO task_events VALUES(?,?,?)', ('parent',4,'completed'))
        parent = SimpleNamespace(status='done', current_run_id=None)
        child = SimpleNamespace(body=json.dumps({'inputs':{'tests':'parent:parent:tests'}}))
        kb = SimpleNamespace(get_task=lambda _, ident: {'parent':parent,'child':child}[ident])
        kbc = SimpleNamespace(connect_closing=lambda: contextlib.nullcontext(conn))
        board = Board(None)
        run = SimpleNamespace(task='child')
        with patch.object(board, 'ensure'), patch('fabriquinha.board.native',return_value=(kb,kbc,None)):
            self.assertEqual(board.input(run,'tests'),'frozen-evidence')


if __name__ == '__main__':
    unittest.main()
