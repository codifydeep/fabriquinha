import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_board_read import board_read,BoardReadUnavailable


class ReadTests(unittest.TestCase):
    def test_missing_database_is_bounded_not_missing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp, patch('review_board_read.time.sleep') as sleep:
            with self.assertRaisesRegex(BoardReadUnavailable,'"evidence_missing": false'):
                with board_read(Path(tmp)/'absent.db'): pass
            self.assertEqual(sleep.call_count,2)
            self.assertFalse((Path(tmp)/'absent.db').exists())

    def test_transient_open_recovers_and_never_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'board.db'
            def restore(_):
                with sqlite3.connect(path) as db: db.execute('CREATE TABLE fixture(value)')
            with patch('review_board_read.time.sleep',side_effect=restore) as sleep:
                with board_read(path) as db:
                    self.assertEqual(sleep.call_count,1)
                    with self.assertRaises(sqlite3.OperationalError): db.execute('INSERT INTO fixture VALUES(1)')

    def test_reads_uncheckpointed_wal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'board.db'
            writer=sqlite3.connect(path)
            try:
                writer.execute('PRAGMA journal_mode=WAL')
                writer.execute('CREATE TABLE fixture(value)'); writer.commit()
                writer.execute('INSERT INTO fixture VALUES(42)'); writer.commit()
                with board_read(path) as db: self.assertEqual(db.execute('SELECT value FROM fixture').fetchone()[0],42)
            finally: writer.close()
