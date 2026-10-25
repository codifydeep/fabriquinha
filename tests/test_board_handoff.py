import contextlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.board import Board, Run
from fabriquinha.artifacts import Store
from fabriquinha.config import Project
from test_delivery_core import configuration


class ClosedParentHandoff(unittest.TestCase):
    def test_plan_findings_survive_a_new_adapter_and_validate_the_reviewed_document(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=Store(root/'private');project=Project.parse(configuration())
            run=Run('plan',3,'lead','plan',False,'lead','v1','contract')
            author=replace(run,number=1);reviewer=replace(run,number=2,actor='cto',reviewing=True)
            proposal=store.record('work_plan',author.binding(),dict(project=project.fingerprint(),
                approval='approved-business-scope',document={'architecture':'Existing architecture'}))
            verdict=dict(decision='changes',reason='Revise this plan',findings=['Preserve the offline boundary in the second package.'])
            payload=dict(project=project.fingerprint(),plan=proposal,verdict=verdict)
            conn=sqlite3.connect(root/'board.db');conn.row_factory=sqlite3.Row;self.addCleanup(conn.close)
            conn.execute('CREATE TABLE task_events(id INTEGER PRIMARY KEY,task_id,run_id,kind,payload)')
            def event(receipt):
                conn.execute('DELETE FROM task_events')
                conn.execute('INSERT INTO task_events VALUES(1,?,?,?,?)',('plan',2,'changes_requested',
                    json.dumps(dict(reason=json.dumps(dict(summary='Revise this plan',evidence={'plan_review':receipt}))))))
                conn.commit()
            api=SimpleNamespace(connect_closing=lambda:contextlib.nullcontext(conn))
            def read():
                # New controller objects, no in-memory/session feedback cache.
                board=Board(project)
                with patch.object(board,'ensure'),patch.object(board,'input',return_value='approved-business-scope'), \
                        patch('fabriquinha.board.native',return_value=(None,api,None)):
                    return board.review_feedback(run,Store(root/'private'))
            event(store.record('plan_review',reviewer.binding(),payload))
            result=read()
            self.assertTrue(result,'Plan author must receive the actual independent findings')
            self.assertEqual(result[0]['verdict'],verdict)
            self.assertEqual(result[0]['plan'],proposal)
            for invalid in (replace(reviewer,task='other'),replace(reviewer,release='other'),
                            replace(reviewer,number=9),replace(reviewer,actor='lead'),replace(reviewer,contract='other')):
                event(store.record('plan_review',invalid.binding(),payload))
                with self.subTest(binding=invalid),self.assertRaises(ValueError):read()
            for invalid in (replace(author,actor='backend'),replace(author,reviewing=True),replace(author,number=4)):
                wrong=store.record('work_plan',invalid.binding(),dict(project=project.fingerprint(),
                    approval='approved-business-scope',document={}))
                event(store.record('plan_review',reviewer.binding(),{**payload,'plan':wrong}))
                with self.subTest(author=invalid),self.assertRaises(ValueError):read()
            wrong=store.record('work_plan',author.binding(),dict(project=project.fingerprint(),approval='different-brief',document={}))
            event(store.record('plan_review',reviewer.binding(),{**payload,'plan':wrong}))
            with self.assertRaises(ValueError):read()

    def test_complete_review_findings_are_scoped_to_author_contract_and_reviewer_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'private');work=Path(directory)/'work';work.mkdir()
            (work/'app.py').write_text('VALUE = 1\n');snapshot=store.capture(work)
            project=Project.parse(configuration());board=Board(project)
            run=Run('task',3,'backend','tests',False,'backend','v1','contract')
            reviewer=replace(run,number=2,actor='lead',reviewing=True)
            verdict=dict(decision='changes',reason='Fix behavior',findings=[dict(path='app.py',line=1,detail='Assert actual behavior')])
            payload=dict(project=project.fingerprint(),snapshot=snapshot,verdict=verdict)
            conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row;self.addCleanup(conn.close)
            conn.execute('CREATE TABLE task_events(id INTEGER PRIMARY KEY,task_id,run_id,kind,payload)')
            def event(receipt):
                conn.execute('DELETE FROM task_events')
                conn.execute('INSERT INTO task_events VALUES(1,?,?,?,?)',('task',2,'changes_requested',
                    json.dumps(dict(reason=json.dumps(dict(evidence={'review':receipt}))))))
            kbc=SimpleNamespace(connect_closing=lambda:contextlib.nullcontext(conn))
            with patch.object(board,'ensure'),patch('fabriquinha.board.native',return_value=(None,kbc,None)):
                event(store.record('test_review',reviewer.binding(),payload))
                result=board.review_feedback(run,store)
                self.assertEqual(result[0]['verdict'],verdict)
                for invalid in (replace(reviewer,task='another'),replace(reviewer,contract='other'),
                                replace(reviewer,number=99),replace(reviewer,actor='backend'),
                                replace(reviewer,reviewing=False)):
                    event(store.record('test_review',invalid.binding(),payload))
                    with self.subTest(binding=invalid),self.assertRaises(ValueError):board.review_feedback(run,store)

    def test_package_coverage_is_read_from_current_server_contract(self):
        task=SimpleNamespace(body=json.dumps(dict(release_plan='reviewed-plan',criteria=['APPROVED'])))
        api=SimpleNamespace(connect_closing=lambda:contextlib.nullcontext(None))
        kb=SimpleNamespace(get_task=lambda *args:task);board=Board(None)
        with patch.object(board,'ensure'),patch('fabriquinha.board.native',return_value=(kb,api,None)):
            self.assertEqual(board.criteria(SimpleNamespace(task='current')),('APPROVED',))
            for body in ({'criteria':['caller-value']},{'release_plan':'review','criteria':[]},
                         {'release_plan':'review','criteria':['A','A']}):
                task.body=json.dumps(body)
                with self.assertRaises(ValueError):board.criteria(SimpleNamespace(task='current'))

    def test_release_evidence_cannot_use_manual_done_as_an_independent_review(self):
        conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row;self.addCleanup(conn.close)
        conn.executescript('CREATE TABLE task_events(id,task_id,run_id,kind,payload);CREATE TABLE task_runs(id,metadata);')
        task=SimpleNamespace(status='done',assignee='lead',body=json.dumps(dict(version=1,kind='tests',release='v1')))
        run=SimpleNamespace(id=2,outcome='completed',profile='lead',metadata={'tests':'frozen'})
        kb=SimpleNamespace(get_task=lambda *args:task,latest_run=lambda *args:run)
        kbc=SimpleNamespace(connect_closing=lambda:contextlib.nullcontext(conn))
        conn.execute('INSERT INTO task_runs VALUES(1,?)',(json.dumps({'red':'actual-red'}),))
        conn.execute('INSERT INTO task_events VALUES(1,?,?,?,?)',('task',1,'review_requested',json.dumps({'implementer':'backend'})))
        conn.execute('INSERT INTO task_events VALUES(3,?,?,?,?)',('task',2,'completed','{}'))
        with patch('fabriquinha.board.native',return_value=(kb,kbc,None)):
            with self.assertRaises(ValueError):Board(Project.parse(configuration())).closed_review('task')
            conn.execute('INSERT INTO task_events VALUES(2,?,?,?,?)',('task',2,'claimed',json.dumps({'source_status':'review'})))
            result=Board(Project.parse(configuration())).closed_review('task')
            self.assertEqual(result[0].author,'backend');self.assertEqual(result[2],{'red':'actual-red'})
            run.profile=task.assignee='backend'
            with self.assertRaises(ValueError):Board(Project.parse(configuration())).closed_review('task')

    def test_current_review_accepts_configured_substitute_not_an_unlisted_role(self):
        project = Project.parse({**configuration(), 'reviewers': {'backend':['lead','cto']}})
        conn = sqlite3.connect(':memory:'); self.addCleanup(conn.close)
        conn.execute('CREATE TABLE task_events(task_id,run_id,kind,payload,id INTEGER PRIMARY KEY)')
        conn.execute('INSERT INTO task_events VALUES(?,?,?,?,?)',
                     ('task',4,'review_requested',json.dumps({'implementer':'backend'}),1))
        conn.execute('INSERT INTO task_events VALUES(?,?,?,?,?)',
                     ('task',5,'claimed',json.dumps({'source_status':'review'}),2))
        task = SimpleNamespace(status='running',current_run_id=5,assignee='cto',
            body=json.dumps(dict(version=1,kind='implementation',release='v1')))
        kb = SimpleNamespace(get_task=lambda *args:task)
        kbc = SimpleNamespace(connect_closing=lambda:contextlib.nullcontext(conn))
        with patch('fabriquinha.board.native',return_value=(kb,kbc,None)):
            current = Board(project).current('task',5)
            self.assertEqual((current.author,current.actor),('backend','cto'))
            for denied in ('backend','unlisted'):
                task.assignee=denied
                with self.subTest(actor=denied), self.assertRaises(ValueError):
                    Board(project).current('task',5)

    def test_handoff_selects_only_an_approved_non_conflicting_substitute(self):
        project = Project.parse({**configuration(), 'reviewers': {'backend': ['lead', 'cto']}})
        captured = {}
        def request_review(_, task, **values):
            captured.update(values)
            return True
        kb = SimpleNamespace(request_review=request_review)
        kbc = SimpleNamespace(connect_closing=lambda: contextlib.nullcontext(None))
        board = Board(project)
        run = SimpleNamespace(task='task', number=4, author='backend', reviewing=False)
        with patch.object(board, 'ensure'), patch('fabriquinha.board.native', return_value=(kb,kbc,None)):
            board.review(run, 'Review delivery', {'green':'receipt'}, exclude=('lead',))
        self.assertEqual(captured['reviewer'], 'cto')
        self.assertEqual(captured['expected_run_id'], 4)
        captured.clear()
        with patch.object(board, 'ensure'), patch('fabriquinha.board.native', return_value=(kb,kbc,None)):
            with self.assertRaises(ValueError):
                board.review(run, 'Review delivery', {}, exclude=('lead','cto'))
        self.assertEqual(captured, {})

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
