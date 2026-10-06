"""One durable retry for an unforwarded error on an exact forced evidence read.

No payloads, source paths or provider error strings enter this ledger. A claim
survives restart and is never rearmed, including when a process dies before send.
"""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from contextlib import contextmanager


def identity(body,execution_id):
    if not isinstance(execution_id,str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',execution_id):
        return None
    if body.get('stream') is not True or body.get('tool_choice')!={'type':'function','function':{'name':'read_file'}}:
        return None
    marked=any(m.get('role')=='user' and isinstance(m.get('content'),str)
        and re.search(r'^DELIVERY_STRUCTURED_DECISION_V1:',m['content'],re.M) for m in body.get('messages',[]))
    tools=[t.get('function',{}) for t in body.get('tools',[]) if t.get('function',{}).get('name')=='read_file']
    if not marked or len(tools)!=1 or tools[0].get('strict') is not True:return None
    schema=tools[0].get('parameters',{});props=schema.get('properties',{})
    if (schema.get('additionalProperties') is not False or set(schema.get('required',[]))!={'path','offset','limit'}
            or set(props)!={'path','offset','limit'}):return None
    values={}
    for key in props:
        enum=props[key].get('enum')
        if not isinstance(enum,list) or len(enum)!=1:return None
        values[key]=enum[0]
    path=values['path']
    if (not isinstance(path,str) or not re.fullmatch(r'/evidence/(?:candidate|previous)/[A-Za-z0-9_./-]+',path)
            or '..' in path.split('/') or props['path'].get('type')!='string'
            or any(props[k].get('type')!='integer' or type(values[k]) is not int or values[k]<1 for k in ('offset','limit'))
            or values['limit']>100):return None
    scope=hashlib.sha256(json.dumps({'execution':execution_id,'model':body.get('model'),**values},sort_keys=True).encode()).hexdigest()
    return {'scope':scope,'execution_id':execution_id,
            'request_sha256':hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()}


@contextmanager
def connect(counter_path):
    counter=Path(counter_path)
    path=counter.with_name('read-stream-recovery.sqlite')
    if counter.is_symlink() or not counter.is_file() or path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError('unsafe read recovery ledger')
    con=sqlite3.connect(path,timeout=5)
    path.chmod(0o600)
    try:
        con.execute('PRAGMA synchronous=FULL')
        con.execute('CREATE TABLE IF NOT EXISTS recovery(scope TEXT PRIMARY KEY, execution_id TEXT, request_sha256 TEXT, '
                    'first_call INTEGER, retry_call INTEGER, stage TEXT, outcome TEXT)')
        con.commit()
        yield con
        con.commit()
    except BaseException:
        con.rollback();raise
    finally:con.close()


def preflight(counter_path,scope):
    if not counter_path or scope is None:return
    with connect(counter_path) as con:
        row=con.execute('SELECT stage FROM recovery WHERE scope=?',(scope['scope'],)).fetchone()
        if row and row[0]!='passed':raise ValueError('read stream recovery exhausted')


def claim(counter_path,scope,first_call,category,media_type):
    if not counter_path or scope is None or category!='upstream_stream_error' or media_type!='text/event-stream':return None
    if type(first_call) is not int or first_call<1:raise ValueError('valid failed call required')
    with connect(counter_path) as con:
        con.execute('BEGIN IMMEDIATE')
        if con.execute('SELECT 1 FROM recovery WHERE scope=?',(scope['scope'],)).fetchone():return None
        if con.execute('SELECT count(*) FROM recovery').fetchone()[0]>=4096:raise RuntimeError('read recovery ledger capacity')
        con.execute('INSERT INTO recovery VALUES (?,?,?,?,?,?,?)',
                    (scope['scope'],scope['execution_id'],scope['request_sha256'],first_call,None,'claimed','upstream_stream_error'))
    return scope


def retry_reserved(counter_path,scope,call):
    with connect(counter_path) as con:
        row=con.execute('SELECT first_call,retry_call,stage FROM recovery WHERE scope=?',(scope['scope'],)).fetchone()
        if not row or row[1] is not None or row[2]!='claimed' or type(call) is not int or call<=row[0]:
            raise ValueError('exact read retry reservation required')
        con.execute('UPDATE recovery SET retry_call=? WHERE scope=?',(call,scope['scope']))


def finish(counter_path,scope,passed,outcome):
    if outcome not in ('validated_read','upstream_stream_error','validation_rejected','upstream_status','interrupted'):
        raise ValueError('fixed read recovery outcome required')
    with connect(counter_path) as con:
        row=con.execute('SELECT stage,retry_call FROM recovery WHERE scope=?',(scope['scope'],)).fetchone()
        if not row or row[0]!='claimed' or (passed and row[1] is None):raise ValueError('claimed read recovery required')
        con.execute('UPDATE recovery SET stage=?,outcome=? WHERE scope=?',
                    ('passed' if passed else 'blocked',outcome,scope['scope']))
