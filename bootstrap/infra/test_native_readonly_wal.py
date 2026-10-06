"""Run as non-root: reproduce absent SHM, fail closed, then recover a reader."""
from pathlib import Path
import os
import sqlite3
import tempfile
from unittest.mock import patch
from review_board_read import board_read,BoardReadUnavailable

assert os.geteuid()!=0, 'run this acceptance as non-root'
with tempfile.TemporaryDirectory() as tmp:
    directory=Path(tmp); path=directory/'board.db'
    writer=sqlite3.connect(path)
    writer.execute('PRAGMA journal_mode=WAL')
    writer.execute('CREATE TABLE evidence(value)'); writer.commit(); writer.close()
    assert not Path(str(path)+'-shm').exists()
    path.chmod(0o444); directory.chmod(0o555)
    try:
        with patch('review_board_read.time.sleep'):
            try:
                with board_read(path): pass
            except BoardReadUnavailable as exc:
                assert '"shm_exists": false' in str(exc)
                print('Reproduced read-only WAL failure with absent SHM; fail-closed diagnostic OK')
            else: raise AssertionError('fixture did not reproduce missing-SHM failure')
    finally: directory.chmod(0o755); path.chmod(0o644)
    writer=sqlite3.connect(path)
    writer.execute('INSERT INTO evidence VALUES(42)'); writer.commit()
    directory.chmod(0o555); path.chmod(0o444)
    try:
        with board_read(path) as reader:
            assert reader.execute('SELECT value FROM evidence').fetchone()[0]==42
            try: reader.execute('INSERT INTO evidence VALUES(43)')
            except sqlite3.OperationalError: pass
            else: raise AssertionError('readonly reader allowed mutation')
        print('Restored WAL reader sees committed evidence, without writes or stale immutable mode')
    finally:
        directory.chmod(0o755); path.chmod(0o644); writer.close()
