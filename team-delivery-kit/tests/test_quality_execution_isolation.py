"""V2 isolation boundary tests; no native delivery qualification."""
import ast
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock,patch
from broker import quality_execution_isolation as isolation


class ExecutionIsolationTests(unittest.TestCase):
    def setUp(self):
        self.b=SimpleNamespace(QUALITY_EXCLUSIVE_ENABLED=True,QUALITY_V2_ENABLED=True,QUALITY_REVIEW_ENABLED=True,
            QUALITY_IMPLEMENTATION_ENABLED=True,QUALITY_TEAM_ENABLED=True,QUALITY_CTO='cto',PREFIX='delivery-kit-test')
        self.team=SimpleNamespace(tick=Mock(return_value={'stage':'observed'}))
        self.progress=SimpleNamespace(tick=Mock(return_value={'stage':'observed'}))
        self.begin=patch.object(isolation.maintenance,'begin_cycle',return_value=True).start()
        self.end=patch.object(isolation.maintenance,'end_cycle').start()
        self.addCleanup(patch.stopall)
    def tick(self):return isolation.tick(self.b,team=self.team,progress=self.progress)

    def test_only_v2_coordinators_are_called_under_maintenance_barrier(self):
        self.assertEqual(self.tick()['stage'],'observed')
        self.team.tick.assert_called_once_with(self.b);self.progress.tick.assert_called_once_with(self.b)
        self.begin.assert_called_once_with(self.b);self.end.assert_called_once_with(self.b)

    def test_failure_releases_cycle_without_falling_back_to_legacy(self):
        self.team.tick.side_effect=RuntimeError('synthetic crash')
        with self.assertRaises(RuntimeError):self.tick()
        self.end.assert_called_once_with(self.b);self.progress.tick.assert_not_called()

    def test_partial_flags_or_maintenance_never_dispatch(self):
        self.b.QUALITY_REVIEW_ENABLED=False
        self.assertEqual(self.tick()['stage'],'configuration_blocked');self.begin.assert_not_called()
        self.b.QUALITY_REVIEW_ENABLED=True;self.begin.return_value=False
        self.assertEqual(self.tick()['stage'],'maintenance')
        self.team.tick.assert_not_called();self.end.assert_not_called()

    def test_unknown_issue_rejected_without_touching_history(self):
        @contextmanager
        def db():yield object()
        self.b.db=db;issue='10000000-0000-4000-8000-000000000001'
        with patch.object(isolation.enrollment,'lookup',return_value=None):
            with self.assertRaises(ValueError):isolation.require_enrolled(self.b,issue)
        record=dict(namespace=self.b.PREFIX)
        with patch.object(isolation.enrollment,'lookup',return_value=record):
            self.assertEqual(isolation.require_enrolled(self.b,issue),record)

    def test_server_routes_exclusive_and_legacy_in_mutually_exclusive_branches(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'broker/server.py').read_text())
        branch=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and isinstance(n.test,ast.Name)
            and n.test.id=='QUALITY_EXCLUSIVE_ENABLED' and any(isinstance(x,ast.Import) for x in n.body)
            and isinstance(n.orelse[0] if n.orelse else None,ast.If))
        self.assertIn('quality_execution_isolation.tick',ast.unparse(branch.body[-1]))
        self.assertIn('controller_maintenance.begin_cycle',ast.unparse(branch.orelse[0].test))
        grant=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='issue_grant')
        self.assertEqual(ast.unparse(grant.body[0].test),'QUALITY_EXCLUSIVE_ENABLED')
        self.assertIsInstance(grant.body[0].body[0],ast.Raise)

    def test_actual_watchdog_never_calls_legacy_barrier_or_coordinator_in_exclusive_mode(self):
        path=Path(__file__).resolve().parents[1]/'broker/server.py'
        tree=ast.parse(path.read_bytes());main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        watchdog=next(n for n in main.body if isinstance(n,ast.FunctionDef) and n.name=='watchdog')
        class StopWatchdog(BaseException):pass
        count=[]
        def sleep(seconds):
            count.append(seconds)
            if len(count)==10:raise StopWatchdog()
        barrier=SimpleNamespace(begin_cycle=Mock(side_effect=AssertionError('legacy barrier reached')))
        exclusive=SimpleNamespace(tick=Mock())
        namespace=dict(tick=Mock(),handoff_context=lambda:self.b,controller_maintenance=barrier,
            QUALITY_EXCLUSIVE_ENABLED=True,time=SimpleNamespace(sleep=sleep))
        exec(compile(ast.Module(body=[watchdog],type_ignores=[]),str(path),'exec'),namespace)
        with patch.dict(sys.modules,{'quality_execution_isolation':exclusive}),self.assertRaises(StopWatchdog):
            namespace['watchdog']()
        exclusive.tick.assert_called_once_with(self.b);barrier.begin_cycle.assert_not_called()


if __name__=='__main__':unittest.main()
