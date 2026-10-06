"""Measure actual read_file pagination on a frozen snapshot; no agent writes."""
from contextlib import redirect_stdout,redirect_stderr
import hashlib
from io import StringIO
import json
from pathlib import Path
import re
import sqlite3
import sys
import uuid

from artifact_read_evidence import coverage

session=sys.argv[1];assert str(uuid.UUID(session))==session
with sqlite3.connect('file:/session/state.db?mode=ro',uri=True) as con:
    texts=[r[0] for r in con.execute('SELECT COALESCE(api_content,content) FROM messages '
        'WHERE session_id=? AND role=? ORDER BY id',(session,'user'))]
text=next(t for t in reversed(texts) if 'DELIVERY_TEST_REVISION_V1:' in t)
paths=set(re.findall(r'^DELIVERY_TEST_(?:SOURCE|REVISION)_V1:([^\n]+)$',text,re.M))
assert 1<=len(paths)<=5
before={}
for path in paths:
    p=Path(path);assert path.startswith('/workspace/') and '..' not in p.parts
    assert p.is_file() and not p.is_symlink()
    before[path]=hashlib.sha256(p.read_bytes()).hexdigest()
with redirect_stdout(StringIO()),redirect_stderr(StringIO()):
    from tools.file_tools import read_file_tool
counts={}
for page in (50,200):
    messages=[];calls=0
    for path in sorted(paths):
        offset=1
        while offset is not None:
            assert calls<64
            with redirect_stdout(StringIO()),redirect_stderr(StringIO()):
                result=read_file_tool(path,offset=offset,limit=page,task_id='page-probe-'+str(page))
            assert isinstance(result,str)
            value=json.loads(result);assert not value.get('error')
            identifier='probe_'+str(calls)
            messages+=[dict(role='assistant',tool_calls=[dict(id=identifier,function=dict(
                name='read_file',arguments=json.dumps(dict(path=path,offset=offset,limit=page))))]),
                dict(role='tool',tool_call_id=identifier,content=result)]
            calls+=1
            receipt=coverage(messages,wire=True).get(path)
            assert receipt and receipt['next_offset']!=offset
            offset=receipt['next_offset']
    receipts=coverage(messages,wire=True)
    assert set(receipts)==paths and all(r['lines']==r['total_lines'] for r in receipts.values())
    counts[page]=calls
assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in before.items())
assert counts[200]<counts[50]
print(json.dumps(dict(operation='frozen_native_read_page_probe_v1',files=len(paths),
    calls_50=counts[50],calls_200=counts[200],all_lines_observed=True,snapshot_unchanged=True,
    model_calls=0,agent_inspection_verified=False,delivery_approval=False,full_rpc_qualified=False)))
