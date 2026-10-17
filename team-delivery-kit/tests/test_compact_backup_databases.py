import gzip
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
import compact_backup_databases as cleanup


class BackupCompactionTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name).resolve()/'backups';self.root.mkdir()

    def database(self,name):
        path=self.root/name
        with closing(sqlite3.connect(path)) as c:
            with c:
                c.execute('CREATE TABLE data(value)');c.execute('INSERT INTO data VALUES(?)',('x'*1200000,))
        return path

    def test_verified_round_trip_and_private_archive(self):
        path=self.database('history.sqlite');before=path.read_bytes();r=cleanup.compact(path,cleanup.identity(path))
        self.assertFalse(path.exists());self.assertEqual(gzip.decompress(Path(r['archive']).read_bytes()),before)
        self.assertEqual(Path(r['archive']).stat().st_mode&0o777,0o600)

    def test_existing_archive_is_not_overwritten_and_source_survives(self):
        path=self.database('history.sqlite');archive=Path(str(path)+'.gz');archive.write_bytes(b'existing')
        with self.assertRaises(ValueError):cleanup.compact(path,cleanup.identity(path))
        self.assertTrue(path.exists());self.assertEqual(archive.read_bytes(),b'existing')

    def test_companions_symlinks_and_changed_sources_are_refused(self):
        path=self.database('history.sqlite');key=cleanup.identity(path)
        Path(str(path)+'-wal').touch()
        with self.assertRaises(ValueError):cleanup.compact(path,key)
        self.assertEqual(cleanup.candidates(self.root),[])
        Path(str(path)+'-wal').unlink();(self.root/'alias.sqlite').symlink_to(path)
        self.assertEqual(len(cleanup.candidates(self.root)),1)
        path.touch()
        with self.assertRaises(ValueError):cleanup.compact(path,key)

    def test_default_is_preview_and_newest_two_are_kept(self):
        for i in range(3):self.database(str(i)+'.sqlite')
        preview=cleanup.run(self.root);self.assertEqual(preview['selected'],1);self.assertTrue(all(p.exists() for p,_ in cleanup.candidates(self.root)))
        applied=cleanup.run(self.root,True);self.assertEqual(applied['compacted'],1)
        self.assertEqual(len(cleanup.candidates(self.root)),2)

    def test_live_or_aliased_root_is_not_accepted(self):
        with self.assertRaises(ValueError):cleanup.root_path(self.root.parent)
        alias=self.root.parent/'alias';alias.symlink_to(self.root)
        with self.assertRaises(ValueError):cleanup.root_path(alias)

    def test_closed_wal_mode_backup_is_checked_without_creating_companions(self):
        path=self.database('wal-history.sqlite')
        with closing(sqlite3.connect(path)) as con:
            con.execute('PRAGMA journal_mode=WAL')
        self.assertFalse(cleanup.companions(path))
        cleanup.compact(path,cleanup.identity(path))
        self.assertFalse(cleanup.companions(path));self.assertFalse(path.exists())
