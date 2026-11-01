import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fabriquinha.effects import write_json
from fabriquinha.upstream_upgrade import apply,manifest

class Upgrade(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        base=Path(self.temp.name).resolve();self.root=base/'live';self.root.mkdir();self.backup=base/'backup';self.backup.mkdir()
        write_json(self.root/'installation.json',dict(project='p',upstream='old',validation_bundle='unchanged'))
        write_json(self.root/'control.json',dict(project='p',upstream='old',paused=True,episode='pause-1'))
        (self.root/'runtime.lock').touch();(self.root/'control.lock').touch()
        (self.root/'evidence').write_text('immutable')
        import shutil
        shutil.copytree(self.root,self.backup/'state')
        write_json(self.backup/'plan.json',dict(version=1,root=str(self.root),before=manifest(self.root),
            old='old',new='new',project='p',episode='pause-1',drained=True))
    def test_upgrade_idempotent_and_rollback(self):
        original=manifest(self.root)
        self.assertTrue(apply(self.root,self.backup)['paused'])
        self.assertEqual(apply(self.root,self.backup)['upstream'],'new')
        apply(self.root,self.backup,rollback=True)
        self.assertEqual(manifest(self.root),original)
    def test_interrupted_between_bindings(self):
        def fail(path,value):
            if path.name=='control.json':raise RuntimeError('interruption')
            write_json(path,value)
        with patch('fabriquinha.upstream_upgrade.write_json',side_effect=fail):
            with self.assertRaises(RuntimeError):apply(self.root,self.backup)
        self.assertEqual(json.loads((self.root/'control.json').read_bytes())['upstream'],'old')
        self.assertEqual(apply(self.root,self.backup)['upstream'],'new')
    def test_evidence_or_counter_drift_refused(self):
        (self.root/'evidence').write_text('changed')
        with self.assertRaisesRegex(ValueError,'drift'):apply(self.root,self.backup)
    def test_stale_binding_refused(self):
        value=json.loads((self.root/'control.json').read_bytes());value['paused']=False
        write_json(self.root/'control.json',value)
        with self.assertRaises(ValueError):apply(self.root,self.backup)
    def test_backup_corruption_refused(self):
        (self.backup/'state/evidence').write_text('changed')
        with self.assertRaisesRegex(ValueError,'integrity'):apply(self.root,self.backup)
    def test_owner_busy_refused(self):
        from fabriquinha.runtime import Owner
        with Owner(self.root):
            with self.assertRaises(BlockingIOError):apply(self.root,self.backup)
    def test_prepare_refuses_active_or_unpaused_runtime(self):
        from types import SimpleNamespace
        from contextlib import nullcontext
        from fabriquinha.upstream_upgrade import prepare
        control=SimpleNamespace(lock=lambda:nullcontext(),read=lambda:dict(error=None,paused=False))
        runtime=SimpleNamespace(root=self.root,control=control,pause_status=lambda conn:dict(drained=False))
        for paused in (False,True):
            control.read=lambda:dict(error=None,paused=paused)
            with patch('fabriquinha.upstream_upgrade.subprocess.check_output',side_effect=['bf0203a794a07aac3ff764972ab9087baa4e4f4e','']),patch('fabriquinha.kanban_lane.native',return_value=(None,SimpleNamespace(connect_closing=lambda:nullcontext()),None)):
                with self.assertRaisesRegex(ValueError,'pause|drained'):
                    prepare(runtime,self.backup/'fresh',self.root)
            self.assertFalse((self.backup/'fresh').exists())
