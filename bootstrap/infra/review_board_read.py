"""Bounded read-only SQLite open, with observable WAL/SHM failure diagnostics.

Never use immutable=1: it may silently ignore uncheckpointed WAL state.
Only retry opening/probing a reader; never replay a controller mutation.
"""
from contextlib import contextmanager
import json
import logging
from pathlib import Path
import sqlite3
import time


class BoardReadUnavailable(RuntimeError):
    pass


@contextmanager
def board_read(path):
    path=Path(path)
    db=None
    for attempt in range(3):
        try:
            db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)
            db.row_factory=sqlite3.Row
            db.execute('SELECT count(*) FROM sqlite_master').fetchone()
            break
        except sqlite3.OperationalError as exc:
            if db is not None: db.close(); db=None
            code=getattr(exc,'sqlite_errorcode',None)
            detail=dict(category='board_read_unavailable',phase='open_readonly_board',
                attempt=attempt+1,sqlite_code=code,sqlite_name=getattr(exc,'sqlite_errorname',None),
                database_exists=path.exists(),wal_exists=Path(str(path)+'-wal').exists(),
                shm_exists=Path(str(path)+'-shm').exists(),error=str(exc),
                evidence_missing=False,next_action='technical_infrastructure_diagnosis')
            logging.getLogger(__name__).warning(json.dumps(detail))
            if attempt==2 or (code & 255 if code is not None else None) not in (sqlite3.SQLITE_CANTOPEN,sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED,sqlite3.SQLITE_READONLY):
                raise BoardReadUnavailable(json.dumps(detail)) from exc
            time.sleep(0.1*(attempt+1))
    try:
        yield db
    finally:
        if db is not None: db.close()
