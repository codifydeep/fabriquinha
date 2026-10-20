from contextlib import closing
import gzip
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from broker import compressed_state_backup as backup


class CompressedBackupTests(unittest.TestCase):
    def test_restore_reconstructs_zeroed_scratch_and_retains_all_source_rows(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state={'operation_id':'op','stage':'sealed'}
            with closing(sqlite3.connect(root/'source.sqlite')) as c:
                c.execute('CREATE TABLE controller_maintenance(operation_id,receipt)')
                c.execute('INSERT INTO controller_maintenance VALUES(?,?)',('op',json.dumps(state)))
                c.execute('CREATE TABLE work(state)');c.execute('INSERT INTO work VALUES(?)',('private history '*1000,));c.commit()
                real=backup.restore_zeroed;observed=[]
                def restore(archive,scratch,size):
                    # Corrupt old scratch content first. Only actual restoration
                    # from the verified gzip archive can recover SQLite and SHA.
                    with scratch.open('r+b') as f:f.write(b'not a valid SQLite header')
                    observed.append(size);return real(archive,scratch,size)
                with patch.object(backup,'restore_zeroed',side_effect=restore):
                    result=backup.backup(c,root/'copy.sqlite.gz',root/'scratch.sqlite',state)
                self.assertEqual(result['restore_integrity'],'ok');self.assertEqual(len(observed),1)
                self.assertFalse((root/'scratch.sqlite').exists());self.assertFalse(result['delivery_approval'])
                self.assertEqual(c.execute('SELECT count(*) FROM work').fetchone()[0],1)
                with gzip.open(root/'copy.sqlite.gz','rb') as f:self.assertEqual(f.read(16),b'SQLite format 3\0')

    def test_existing_or_uncertain_files_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d,closing(sqlite3.connect(':memory:')) as c:
            root=Path(d);archive=root/'existing.gz';archive.write_bytes(b'unknown')
            with self.assertRaises(ValueError):backup.backup(c,archive,root/'scratch.sqlite',{})
            self.assertEqual(archive.read_bytes(),b'unknown')

    def test_archive_quota_preserves_scratch_for_observation(self):
        with tempfile.TemporaryDirectory() as d,closing(sqlite3.connect(':memory:')) as c:
            root=Path(d);c.execute('CREATE TABLE work(value)');c.execute('INSERT INTO work VALUES(?)',('data',));c.commit()
            with self.assertRaises(ValueError):backup.backup(c,root/'partial.gz',root/'scratch.sqlite',{},max_archive_bytes=1)
            with closing(sqlite3.connect(root/'scratch.sqlite')) as preserved:
                self.assertEqual(preserved.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertEqual(preserved.execute('SELECT value FROM work').fetchone()[0],'data')
            self.assertTrue((root/'partial.gz').exists())
