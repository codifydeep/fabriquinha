"""One durable format correction for an unforwarded forced artifact tool.

Never select one of several proposals, execute a tool or relax its schema.
Only the model can propose a new single call, validated by every original gate.
"""
import copy
import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from artifact_response_contract import metrics


def identity(body,execution):
    if not isinstance(execution,str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',execution):return None
    selected=metrics(body).get('artifact_selected_tool')
    if selected not in ('patch','read_file'):return None
    tools=[t.get('function',{}) for t in body.get('tools',[]) if t.get('function',{}).get('name')==selected]
    if len(tools)!=1:return None
    spec=tools[0].get('parameters',{});props=spec.get('properties',{})
    if selected=='read_file':
        if (tools[0].get('strict') is not True or spec.get('type')!='object'
                or spec.get('additionalProperties') is not False
                or set(spec.get('required',[]))!={'path','offset','limit'}
                or set(props)!={'path','offset','limit'}):return None
        values={}
        for key in props:
            enum=props[key].get('enum')
            if not isinstance(enum,list) or len(enum)!=1:return None
            values[key]=enum[0]
        path=values['path']
        if (props['path'].get('type')!='string' or not isinstance(path,str)
                or not re.fullmatch(r'/workspace/[A-Za-z0-9_./-]+',path)
                or any(part in ('','.','..') for part in path.split('/')[2:])
                or any(props[k].get('type')!='integer' or type(values[k]) is not int
                    or values[k]<1 for k in ('offset','limit')) or values['limit']>200):return None
        return dict(execution_id=execution,request_sha256=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest())
    if (spec.get('additionalProperties') is not False or set(spec.get('required',[]))!={'path','old_string','new_string'}
            or set(props)!={'path','old_string','new_string'}):return None
    paths=props['path'].get('enum')
    if (props['path'].get('type')!='string' or not isinstance(paths,list) or len(paths)!=1
            or not isinstance(paths[0],str) or '..' in paths[0].split('/')
            or not re.fullmatch(r'/workspace/tests/test_[A-Za-z0-9_.-]+\.py',paths[0])
            or any(props[k].get('type')!='string' or type(props[k].get('maxLength')) is not int
                or not 1<=props[k]['maxLength']<=4096 for k in ('old_string','new_string'))):return None
    return dict(execution_id=execution,request_sha256=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest())


@contextmanager
def ledger(counter_path):
    counter=Path(counter_path);path=counter.with_name('forced-tool-feedback.sqlite')
    if counter.is_symlink() or not counter.is_file() or path.is_symlink() or path.exists() and not path.is_file():
        raise RuntimeError('unsafe forced-tool feedback ledger')
    con=sqlite3.connect(path,timeout=5);path.chmod(0o600)
    try:
        con.execute('PRAGMA synchronous=FULL')
        con.execute('CREATE TABLE IF NOT EXISTS feedback(execution_id TEXT PRIMARY KEY,request_sha256 TEXT,'
            'first_call INTEGER,retry_call INTEGER,receipt TEXT,stage TEXT)')
        con.commit();yield con;con.commit()
    except BaseException:con.rollback();raise
    finally:con.close()


def preflight(counter_path,scope):
    if not counter_path or scope is None:return
    with ledger(counter_path) as con:
        row=con.execute('SELECT stage FROM feedback WHERE execution_id=?',(scope['execution_id'],)).fetchone()
        if row and row[0]!='passed':raise ValueError('forced-tool feedback exhausted')


def claim(counter_path,scope,error,body,first_call):
    if not counter_path or scope is None or getattr(error,'category',None)!='incomplete_forced_tool_response':return None
    diagnostic=getattr(error,'diagnostic',{})
    if (set(diagnostic)!={'schema','response_sha256','streaming','stream_complete','finish_reason','tool_calls','all_selected_tools'}
            or diagnostic['schema']!='forced-tool-shape-v1' or diagnostic['stream_complete'] is not True
            or type(diagnostic['streaming']) is not bool or diagnostic['finish_reason']!='tool_calls'
            or type(diagnostic['tool_calls']) is not int or not 2<=diagnostic['tool_calls']<=64
            or diagnostic['all_selected_tools'] is not True
            or not re.fullmatch(r'[a-f0-9]{64}',str(diagnostic['response_sha256']))):return None
    if type(first_call) is not int or first_call<1 or identity(body,scope['execution_id'])!=scope:
        raise ValueError('exact rejected forced tool request required')
    selected=metrics(body)['artifact_selected_tool']
    receipt=dict(operation='unforwarded_parallel_patch_feedback_v1' if selected=='patch'
        else 'unforwarded_parallel_read_feedback_v1',**scope,
        first_call=first_call,diagnostic=diagnostic,worker_tool_executed=False,response_forwarded=False,
        attempt_limit=1,delivery_approval=False)
    with ledger(counter_path) as con:
        con.execute('BEGIN IMMEDIATE')
        if con.execute('SELECT 1 FROM feedback WHERE execution_id=?',(scope['execution_id'],)).fetchone():return None
        if con.execute('SELECT COUNT(*) FROM feedback').fetchone()[0]>=4096:raise RuntimeError('feedback ledger capacity')
        con.execute('INSERT INTO feedback VALUES (?,?,?,?,?,?)',(scope['execution_id'],scope['request_sha256'],
            first_call,None,json.dumps(receipt,sort_keys=True),'claimed'))
    revised=copy.deepcopy(body)
    instruction=(
        'FORMAT CORRECTION: the prior response contained multiple read_file calls and NONE was forwarded or executed. '
        'Return exactly ONE read_file call for the currently pinned path, offset and limit in the original schema. '
        'Do not batch, duplicate calls, change the page, or propose writes. '
        'The original schema and tool guards still apply. This is one format correction, not delivery approval.'
        if selected=='read_file' else
        'FORMAT CORRECTION: the prior response contained multiple patch calls and NONE was forwarded or executed. '
        'Return exactly ONE patch call for the currently pinned NEW test, with one small old_string/new_string change. '
        'Do not batch or duplicate calls. Preserve all assertions, existing tests and product code. '
        'The original schema and tool guards still apply. This is one format correction, not delivery approval.')
    revised['messages'].append(dict(role='system',content=
        instruction))
    return revised


def retry_reserved(counter_path,scope,call):
    with ledger(counter_path) as con:
        row=con.execute('SELECT first_call,retry_call,stage FROM feedback WHERE execution_id=?',(scope['execution_id'],)).fetchone()
        if not row or row[1] is not None or row[2]!='claimed' or type(call) is not int or call<=row[0]:
            raise ValueError('exact once-only patch reservation required')
        con.execute('UPDATE feedback SET retry_call=? WHERE execution_id=?',(call,scope['execution_id']))


def finish(counter_path,scope,passed):
    with ledger(counter_path) as con:
        row=con.execute('SELECT retry_call,stage FROM feedback WHERE execution_id=?',(scope['execution_id'],)).fetchone()
        if not row or row[1]!='claimed' or passed and row[0] is None:raise ValueError('claimed patch feedback required')
        con.execute('UPDATE feedback SET stage=? WHERE execution_id=?',('passed' if passed else 'blocked',scope['execution_id']))
