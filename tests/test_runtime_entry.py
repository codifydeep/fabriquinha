"""The public entry uses the frozen tree and never implicitly resumes dispatch."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
spec=importlib.util.spec_from_file_location('runtime_entry',ROOT/'scripts/run_hermes_runtime.py')
entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)


class RuntimeEntry(unittest.TestCase):
    def test_command_is_fixed_scoped_and_preserves_control_operation(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary).resolve();source=base/'source';source.mkdir()
            (source/'src').mkdir();root=base/'private';root.mkdir();upstream=base/'hermes';upstream.mkdir()
            with patch.object(entry,'verify',return_value={'verified':True}) as verified:
                command,env=entry.command(source,'a'*64,Path(sys.executable),root,upstream,'status')
            verified.assert_called_once_with(source,'a'*64)
            self.assertEqual(command,[str(Path(sys.executable).absolute()),'-B','-m','fabriquinha.runtime','status',
                '--root',str(root),'--upstream',str(upstream)])
            self.assertEqual(env['PYTHONPATH'],str(source/'src'))
            self.assertEqual(env['FABRIQUINHA_SOURCE_DIGEST'],'a'*64)
            self.assertEqual(env['PYTHONDONTWRITEBYTECODE'],'1')
            self.assertEqual(env['PYTHONSAFEPATH'],'1')
            self.assertEqual(env['PYTHONNOUSERSITE'],'1')
            self.assertNotIn('resume',command)

    def test_worker_or_bad_operational_arguments_are_rejected_before_exec(self):
        with patch.object(entry,'verify') as verify:
            for operation,options in [('worker',{}),('resume',{}),('status',{'episode':'a'*32}),
                    ('serve',{'interval':float('nan')}),('serve',{'interval':0}),('resume',{'episode':'old'})]:
                with self.subTest(operation=operation,options=options),self.assertRaises(ValueError):
                    entry.command(ROOT,'a'*64,Path(sys.executable),ROOT,ROOT,operation,**options)
            verify.assert_not_called()

    def test_source_drift_refuses_command_without_reading_installation_or_secrets(self):
        with patch.object(entry,'verify',side_effect=ValueError('source changed')):
            with self.assertRaisesRegex(ValueError,'source changed'):
                entry.command(ROOT,'a'*64,Path(sys.executable),ROOT/'not-created',ROOT,'serve')
        self.assertFalse((ROOT/'not-created').exists())

    def test_resume_only_passes_explicit_current_episode_to_native_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve()
            with patch.object(entry,'verify'):
                command,_=entry.command(root,'a'*64,Path(sys.executable),root,root,'resume',episode='b'*32)
            self.assertEqual(command[-2:],['--expect-pause','b'*32])


if __name__=='__main__':unittest.main()
