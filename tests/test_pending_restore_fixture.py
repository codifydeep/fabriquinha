import json
from contextlib import closing
from pathlib import Path
import sqlite3
import shutil
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import qualify_state_restore as fixture


class PendingRestoreFixture(unittest.TestCase):
    def prepare(self,root,qualification=True):
        root.mkdir();(root/'home').mkdir()
        (root/'project.json').write_text(json.dumps({'qualification':qualification}))
        (root/'route.json').write_text(json.dumps({'base_url':'http://127.0.0.1:9/v1','api_key':'unused-fixture'}))
        (root/'evidence.txt').write_text('preserve exact evidence')
        with closing(sqlite3.connect(root/'home/kanban.db')) as conn, conn:
            conn.execute('create table evidence(value text)')
            conn.execute("insert into evidence values('original')")

    def test_production_or_provider_configuration_is_never_restored(self):
        for production in [True,False]:
            with self.subTest(production=production),tempfile.TemporaryDirectory() as folder:
                root=Path(folder)/'fixture';self.prepare(root,not production)
                if not production:(root/'provider-policy.json').write_text('{}')
                with patch.object(fixture,'ROOT',Path(folder).resolve()),patch.object(fixture.subprocess,'run',return_value=NS(returncode=0)),patch.object(fixture,'Runtime') as runtime:
                    with self.assertRaisesRegex(ValueError,'credential-free'):
                        fixture.restore_pending_integration_fixture(root,Path(folder))
                    runtime.assert_not_called()
                self.assertEqual((root/'evidence.txt').read_text(),'preserve exact evidence')
                self.assertFalse(root.with_name('fixture-restore-backup').exists())

    def test_same_path_copy_preserves_backup_original_and_pending_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'fixture';self.prepare(root)
            runtime=NS(pause=lambda:dict(agents_stopped=True,pending_effects=['b','a'],control={'episode':'exact'}),
                control=NS(read=lambda:{'episode':'exact'}),resume=lambda episode:{'pending_effects':['a','b']})
            connections=[];connect=sqlite3.connect;copytree=shutil.copytree
            def opened(*args,**kwargs):
                conn=connect(*args,**kwargs);connections.append(conn);return conn
            def copied(*args,**kwargs):
                for conn in connections:
                    with self.assertRaises(sqlite3.ProgrammingError):conn.execute('select 1')
                return copytree(*args,**kwargs)
            with patch.object(fixture,'ROOT',Path(folder).resolve()),patch.object(fixture.subprocess,'run',return_value=NS(returncode=0)),patch.object(fixture,'Runtime',return_value=runtime),patch.object(fixture.sqlite3,'connect',side_effect=opened),patch.object(fixture.shutil,'copytree',side_effect=copied):
                result=fixture.restore_pending_integration_fixture(root,Path(folder))
            self.assertTrue(result['pending_effects_preserved'])
            self.assertFalse(result['production_restore_qualified'])
            for path in [root,root.with_name('fixture-restore-backup'),root.with_name('fixture-pre-restore')]:
                self.assertEqual((path/'evidence.txt').read_text(),'preserve exact evidence')
                with closing(sqlite3.connect(path/'home/kanban.db')) as conn:
                    self.assertEqual(conn.execute('select value from evidence').fetchone()[0],'original')
