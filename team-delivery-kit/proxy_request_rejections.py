"""Durable, sanitized local rejection evidence. Never stores request bodies."""
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid
from contextlib import closing

STAGES = {'admission', 'decode', 'contract', 'metrics', 'read_dispatch',
          'read_validation', 'read_ledger', 'preflight', 'upstream', 'response'}
ORIGINS = {'model_proxy', 'test_artifact_schema', 'write_tool_schema',
           'decision_schema', 'typed_decision_contract', 'typed_test_source',
           'deterministic_read_dispatch', 'artifact_response_contract',
           'read_stream_recovery', 'structured_response_contract'}


def describe(error, stage, execution, request_sha):
    if stage not in STAGES:
        raise ValueError('invalid rejection stage')
    if str(uuid.UUID(execution)) != execution:
        raise ValueError('canonical rejection execution required')
    if len(request_sha) != 64 or any(c not in '0123456789abcdef' for c in request_sha):
        raise ValueError('invalid request digest')
    origin = None
    trace = error.__traceback__
    while trace:
        module = Path(trace.tb_frame.f_code.co_filename).stem
        if module in ORIGINS:
            origin = {'module': module, 'line': trace.tb_lineno}
        trace = trace.tb_next
    return dict(operation='local_request_rejection_v1', execution_id=execution,
        request_sha256=request_sha, stage=stage, origin=origin,
        exception_type=type(error).__name__ if type(error) in (ValueError, TypeError,
            json.JSONDecodeError, RuntimeError) else 'other',
        error_sha256=hashlib.sha256(str(error).encode()).hexdigest(),
        retry_authorized=False, delivery_approval=False)


def record(counter_path, receipt):
    keys = {'operation','execution_id','request_sha256','stage','origin',
            'exception_type','error_sha256','retry_authorized','delivery_approval'}
    if (not isinstance(receipt,dict) or set(receipt)!=keys
            or receipt['operation']!='local_request_rejection_v1'
            or receipt['stage'] not in STAGES
            or receipt['exception_type'] not in ('ValueError','TypeError','JSONDecodeError','RuntimeError','other')
            or receipt['retry_authorized'] is not False or receipt['delivery_approval'] is not False
            or str(uuid.UUID(receipt['execution_id']))!=receipt['execution_id']
            or any(not isinstance(receipt[k],str) or len(receipt[k])!=64
                   or any(c not in '0123456789abcdef' for c in receipt[k])
                   for k in ('request_sha256','error_sha256'))):
        raise ValueError('invalid sanitized request receipt')
    origin=receipt['origin']
    if origin is not None and (not isinstance(origin,dict) or set(origin)!={'module','line'}
            or origin['module'] not in ORIGINS or type(origin['line']) is not int
            or not 0<origin['line']<100000):
        raise ValueError('invalid sanitized rejection origin')
    if not counter_path:
        return
    counter = Path(counter_path)
    path = counter.with_name('request-rejections.sqlite')
    if counter.is_symlink() or not counter.is_file() or path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('unsafe request rejection ledger')
    encoded = json.dumps(receipt, sort_keys=True)
    key = hashlib.sha256(encoded.encode()).hexdigest()
    with closing(sqlite3.connect(path, timeout=5)) as con, con:
        path.chmod(0o600)
        con.execute('PRAGMA synchronous=FULL')
        con.execute('CREATE TABLE IF NOT EXISTS rejections(identity TEXT PRIMARY KEY,execution_id TEXT,receipt TEXT)')
        con.execute('BEGIN IMMEDIATE')
        if con.execute('SELECT 1 FROM rejections WHERE identity=?', (key,)).fetchone():
            return
        if con.execute('SELECT count(*) FROM rejections').fetchone()[0] >= 8192:
            raise RuntimeError('request rejection ledger capacity')
        con.execute('INSERT INTO rejections VALUES(?,?,?)', (key, receipt['execution_id'], encoded))


def read(counter_path, execution):
    if str(uuid.UUID(execution)) != execution:
        raise ValueError('canonical rejection execution required')
    path = Path(counter_path).with_name('request-rejections.sqlite')
    if path.is_symlink() or not path.is_file():
        raise ValueError('request rejection ledger unavailable')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as con:
        return [json.loads(r[0]) for r in con.execute(
            'SELECT receipt FROM rejections WHERE execution_id=? ORDER BY rowid', (execution,))]
