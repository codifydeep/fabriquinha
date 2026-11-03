import json
import unittest
import tempfile
import sys
from pathlib import Path
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import digest
from fabriquinha.recovery import Diagnostic


class DiagnosticRetryBoundary(unittest.TestCase):
    def test_identical_failure_is_not_executed_a_third_time(self):
        from fabriquinha.recovery import register_diagnostic
        class Operations:
            incident={}
            def __init__(self):self.calls=0
            def actions(self):return ['hold']
            def validate(self,args):return {}
            def report_page(self,args):return {}
            def decide(self,args):self.calls+=1;raise ValueError('invalid scope')
        operations=Operations();registered={}
        registry=SimpleNamespace(register=lambda **kwargs:registered.update({kwargs['name']:kwargs}))
        with patch.dict(sys.modules,{'tools.registry':SimpleNamespace(registry=registry)}),patch('fabriquinha.recovery.Diagnostic',return_value=operations):
            register_diagnostic(None,None,None)
        call=registered['diagnostic_decide']['handler'];args={'action':'hold'}
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,'invalid scope'):call(args)
        with self.assertRaisesRegex(ValueError,'already rejected twice'):call(args)
        self.assertEqual(operations.calls,2)
        with self.assertRaisesRegex(ValueError,'invalid scope'):call({'action':'hold','reason':'new evidence'})
        self.assertEqual(operations.calls,3)


class FreezeResolution(unittest.TestCase):
    def setUp(self):
        self.body={'kind':'implementation','inputs':{'tests':'f'*64}}
        self.task=SimpleNamespace(body=json.dumps(self.body))
        self.d=Diagnostic.__new__(Diagnostic)
        self.d.actions=lambda:['repair_tests']
        self.d.original={'task':'implementation','contract':digest(self.body)}
        self.d.run=SimpleNamespace(release='release')
        self.d.incident={'snapshot':'candidate'}
        self.d.store=Mock();self.d.store.receipt.return_value={'binding':{'release':'release'}}
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.d.store.root=Path(temporary.name)
        self.d.q=Mock();self.d.q.frozen_plan.return_value={'snapshot':'frozen'}
        self.d.board=Mock()
        self.api=(SimpleNamespace(get_task=lambda *a:self.task),SimpleNamespace(connect_closing=lambda:nullcontext(None)),None)

    def test_resolves_source_input_and_protects_exact_frozen_tests(self):
        with patch('fabriquinha.recovery.native',return_value=self.api):
            key,_=self.d.repair_freeze()
        self.assertEqual(key,'f'*64)
        self.d.q.protect.assert_called_once_with('frozen','candidate',exact_tests=True)

    def test_changed_source_contract_and_foreign_release_rejected(self):
        self.task.body=json.dumps({**self.body,'kind':'tests'})
        with patch('fabriquinha.recovery.native',return_value=self.api),self.assertRaisesRegex(ValueError,'contract'):
            self.d.repair_freeze()
        self.task.body=json.dumps(self.body)
        self.d.store.receipt.return_value={'binding':{'release':'other'}}
        with patch('fabriquinha.recovery.native',return_value=self.api),self.assertRaisesRegex(ValueError,'foreign'):
            self.d.repair_freeze()

    def test_baseline_test_drift_is_not_authorized_by_resolution(self):
        self.d.q.protect.side_effect=ValueError('frozen tests changed')
        with patch('fabriquinha.recovery.native',return_value=self.api),self.assertRaisesRegex(ValueError,'changed'):
            self.d.repair_freeze()
