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
from author_read_policy import page_size

session=sys.argv[1];assert str(uuid.UUID(session))==session
source_task=sys.argv[2];assert str(uuid.UUID(source_task))==source_task
with sqlite3.connect('file:/session/state.db?mode=ro',uri=True) as con:
    texts=[r[0] for r in con.execute('SELECT COALESCE(api_content,content) FROM messages '
        'WHERE session_id=? AND role=? ORDER BY id',(session,'user'))]
    tool_turns=sum(bool(json.loads(r[0])) for r in con.execute(
        'SELECT tool_calls FROM messages WHERE session_id=? AND role=? AND tool_calls IS NOT NULL',
        (session,'assistant')))
text=next(t for t in reversed(texts) if 'DELIVERY_TEST_REVISION_V1:' in t)
assert page_size({'messages':[dict(role='user',content=text)]})==50
assert page_size({'messages':[dict(role='user',content=text+'\nDELIVERY_AUTHOR_READ_PAGE_V1:200\n')]})==200
paths=set(re.findall(r'^DELIVERY_TEST_(?:SOURCE|REVISION)_V1:([^\n]+)$',text,re.M))
assert 1<=len(paths)<=5
before={}
manifest_raw=Path('/workspace/manifest.json').read_bytes()
manifest=json.loads(manifest_raw)['files']
base=json.loads(Path('/base/manifest.json').read_text())['files']
for path,record in manifest.items():
    p=Path(path);assert not p.is_absolute() and '..' not in p.parts
    f=Path('/workspace')/p;assert f.is_file() and not f.is_symlink()
    raw=f.read_bytes();assert len(raw)==record['bytes']
    assert hashlib.sha256(raw).hexdigest()==record['sha256']
for path,digest in base.items():
    if path!='contract.json':assert manifest[path]['sha256']==digest
targets=set(re.findall(r'^DELIVERY_TEST_REVISION_V1:/workspace/([^\n]+)$',text,re.M))
assert len(targets)==1 and not targets&set(base)
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
print(json.dumps(dict(operation='frozen_native_read_page_probe_v2',source_task=source_task,
    session_id=session,manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
    policy_sha256=hashlib.sha256(Path(page_size.__code__.co_filename).read_bytes()).hexdigest(),
    baseline_unchanged=True,test_sha256={p:manifest[p]['sha256'] for p in targets},files=len(paths),
    historical_tool_turns=tool_turns,
    calls_50=counts[50],calls_200=counts[200],all_lines_observed=True,snapshot_unchanged=True,
    model_calls=0,agent_inspection_verified=False,delivery_approval=False,full_rpc_qualified=False)))
