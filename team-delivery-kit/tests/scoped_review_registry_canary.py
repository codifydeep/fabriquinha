"""Actual worker registry/read formatter qualification; no model or suite RPC."""
import hashlib,json,os,sqlite3,sys
sys.path[:0]=['/opt/hermes','/']
from tools.registry import registry,discover_builtin_tools
from acp_adapter.tools import _format_read_file_result
import review_read_gate as gate
import read_stream_receipts as receipts
from artifact_read_evidence import coverage

paths=json.loads(os.environ['DELIVERY_REVIEW_READ_PATHS_JSON'])
assert os.getuid()==10000 and os.environ['DELIVERY_EXECUTION_MODE']=='review'
discover_builtin_tools()
con=sqlite3.connect(':memory:')
con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT)')
con.execute('INSERT INTO native_bindings VALUES(?,?)',('canary','canary'))
before={p:hashlib.sha256(open(p,'rb').read()).hexdigest() for p in paths}
command=json.loads(os.environ['DELIVERY_TEST_COMMANDS_JSON'])[0].replace('cd /workspace && ','cd /delivery && ',1)
assert json.loads(registry.dispatch('terminal',dict(command=command)))['error']=='review_reads_incomplete'
pages=0
for path in paths:
    offset=1
    while True:
        args=dict(path=path,offset=offset,limit=100)
        result=registry.dispatch('read_file',args);data=json.loads(result)
        assert not data.get('error') and data['total_lines']>0
        formatted=_format_read_file_result(result,args)
        assert 'chars total, truncated)' not in formatted
        identifier='page-'+str(pages)
        frames=[dict(method='session/update',params=dict(update=u)) for u in (
            dict(sessionUpdate='tool_call',toolCallId=identifier,kind='read',title='read: '+path),
            dict(sessionUpdate='tool_call_update',toolCallId=identifier,status='completed',
                 content=[dict(type='content',content=dict(type='text',text=formatted))]))]
        receipts.store(con,dict(task_id='canary',request_id='canary'),frames,'review');pages+=1
        if offset+99>=data['total_lines']:break
        offset+=100
assert not gate.pending()
reads=coverage(receipts.load(con,'canary'))
assert set(reads)==set(paths) and all(v['lines']==v['total_lines'] for v in reads.values())
assert json.loads(registry.dispatch('terminal',dict(command=command)))['error']=='review_suite_capability_missing'
assert before=={p:hashlib.sha256(open(p,'rb').read()).hexdigest() for p in paths}
print(json.dumps(dict(operation='scoped_review_registry_canary_v1',status='passed',files_sha256=before,
    complete_reads={p:{k:r[k] for k in ('lines','total_lines')} for p,r in reads.items()},pages=pages,
    early_suite_denied=True,inputs_unchanged=True,model_calls=0,delivery_approval=False)))
