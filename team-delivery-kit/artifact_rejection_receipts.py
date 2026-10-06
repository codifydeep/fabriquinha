"""Sanitized, execution-bound rejected test-write receipts; no payload storage."""
import json
import uuid
import sqlite3
from pathlib import Path
from contextlib import contextmanager

@contextmanager
def ledger(counter_path):
    if not counter_path:raise ValueError('durable counter required')
    counter=Path(counter_path);path=counter.with_name('artifact-rejections.sqlite')
    if counter.is_symlink() or not counter.is_file() or path.is_symlink():raise ValueError('unsafe receipt ledger')
    c=sqlite3.connect(path,timeout=5);path.chmod(0o600)
    try:
        c.execute('PRAGMA synchronous=FULL');c.execute('BEGIN IMMEDIATE')
        yield c;c.commit()
    except BaseException:c.rollback();raise
    finally:c.close()

CATEGORIES={'artifact_test_methods_missing','artifact_test_syntax_invalid'}

def from_event(event):
    if (event.get('event')!='model_proxy_request' or event.get('status')!=502
            or event.get('artifact_selected_tool')!='write_file'
            or event.get('artifact_contract_present') is not True
            or event.get('artifact_rejection_category') not in CATEGORIES):return None
    execution=event.get('execution_id')
    if not isinstance(execution,str) or str(uuid.UUID(execution))!=execution:return None
    call=event.get('call_number')
    if type(call) is not int or call<1:return None
    result=dict(operation='rejected_test_write_v1',execution_id=execution,call_number=call,
        category=event['artifact_rejection_category'],tool='write_file',write_executed=False,
        tests_executed=False,red_verified=False,delivery_approval=False)
    structure=event.get('artifact_rejection_diagnostic')
    keys={'schema','content_sha256','utf8_bytes','classes','functions','test_methods',
          'top_level_string_only','embedded_test_methods'}
    if isinstance(structure,dict) and structure.get('schema')=='python-artifact-structure-v1':
        transport={'schema','content_sha256','utf8_bytes','physical_newlines','escaped_newlines','comment_lines'}
        valid_sets=(keys,transport,keys|transport)
        import re
        counts={'utf8_bytes','classes','functions','test_methods','embedded_test_methods',
                'physical_newlines','escaped_newlines','comment_lines'}
        if (set(structure) not in valid_sets or not re.fullmatch(r'[0-9a-f]{64}',str(structure.get('content_sha256')))
                or 'top_level_string_only' in structure and type(structure['top_level_string_only']) is not bool
                or any(type(structure[k]) is not int or not 0<=structure[k]<=32768 for k in counts&structure.keys())):
            raise ValueError('invalid structural receipt')
        result['structure']=structure
    return result

def record(counter_path,event):
    receipt=from_event(event)
    if receipt is None:return
    with ledger(counter_path) as c:
        c.execute('CREATE TABLE IF NOT EXISTS artifact_rejections(execution_id TEXT,call_number INTEGER,receipt TEXT,PRIMARY KEY(execution_id,call_number))')
        encoded=json.dumps(receipt,sort_keys=True)
        old=c.execute('SELECT receipt FROM artifact_rejections WHERE execution_id=? AND call_number=?',
                      (receipt['execution_id'],receipt['call_number'])).fetchone()
        if old and old[0]!=encoded:raise ValueError('artifact receipt drift')
        if not old:c.execute('INSERT INTO artifact_rejections VALUES(?,?,?)',
                            (receipt['execution_id'],receipt['call_number'],encoded))

def read(counter_path,execution):
    if str(uuid.UUID(execution))!=execution:raise ValueError('canonical execution required')
    with ledger(counter_path) as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='artifact_rejections'").fetchone():return []
        return [json.loads(r[0]) for r in c.execute('SELECT receipt FROM artifact_rejections WHERE execution_id=? ORDER BY call_number',(execution,))]
