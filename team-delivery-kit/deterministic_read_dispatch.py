"""Controller-authored read requests, never synthetic read results or decisions."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from read_stream_recovery import identity


def artifact_identity(body, execution_id):
    """Exact author reads only; schema is generated from the declared sources."""
    if not isinstance(execution_id,str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',execution_id):return None
    if body.get('tool_choice')!={'type':'function','function':{'name':'read_file'}}:return None
    from artifact_response_contract import metrics
    if metrics(body)['artifact_selected_tool']!='read_file':return None
    sources=set();revisions=set();artifacts=set();seeded=set()
    for m in body.get('messages',[]):
        content=m.get('content','')
        if m.get('role')=='user' and isinstance(content,str):
            sources.update(re.findall(r'^DELIVERY_TEST_SOURCE_V1:([^\n]+)$',content,re.M))
            revisions.update(re.findall(r'^DELIVERY_TEST_REVISION_V1:([^\n]+)$',content,re.M))
            artifacts.update(re.findall(r'^DELIVERY_TEST_ARTIFACT_V1:([^\n]+)$',content,re.M))
            seeded.update(re.findall(r'^DELIVERY_SEEDED_EDIT_REQUIRED_V1:([^\n]+)$',content,re.M))
    if revisions:
        # The schema requires full inspection of the historical NEW test before
        # editing. Admit that exact revision target, not arbitrary extra paths.
        if len(revisions)!=1 or revisions!=artifacts:return None
        target=next(iter(revisions))
        if not (target.rsplit('/',1)[-1].startswith('test_') and target.endswith('.py')
                or target.endswith(('.test.js','.spec.js'))):return None
        sources.update(revisions)
    tools=[t['function'] for t in body.get('tools',[]) if t.get('function',{}).get('name')=='read_file']
    if len(tools)!=1 or tools[0].get('strict') is not True:return None
    schema=tools[0].get('parameters',{});props=schema.get('properties',{})
    if set(props)!={'path','offset','limit'} or set(schema.get('required',[]))!=set(props) or schema.get('additionalProperties') is not False:return None
    if any(not isinstance(v.get('enum'),list) or len(v['enum'])!=1 for v in props.values()):return None
    args={k:v['enum'][0] for k,v in props.items()};path=args['path']
    if (path not in sources or not isinstance(path,str) or not re.fullmatch(r'/workspace/[A-Za-z0-9_./-]+',path)
            or any(p in ('','.', '..') for p in path.split('/')[2:]) or props['path'].get('type')!='string'
            or any(props[k].get('type')!='integer' or type(args[k]) is not int or args[k]<1 for k in ('offset','limit'))
            or args['limit']!=(200 if seeded and seeded==revisions==artifacts else 50)):return None
    scope=hashlib.sha256(json.dumps(dict(namespace='author-read-v1',execution=execution_id,model=body.get('model'),**args),sort_keys=True).encode()).hexdigest()
    return dict(scope=scope,execution_id=execution_id,request_sha256=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest())


def make(body,execution_id):
    marked=any(m.get('role')=='user' and isinstance(m.get('content'),str)
        and re.search(r'^DELIVERY_DETERMINISTIC_READ_V1$',m['content'],re.M) for m in body.get('messages',[]))
    if not marked:return None
    scope=identity({**body,'stream':True},execution_id) or artifact_identity(body,execution_id)
    if scope is None:
        if body.get('tool_choice')=={'type':'function','function':{'name':'read_file'}}:
            raise ValueError('invalid deterministic read contract')
        return None  # decision phase and other tools are never synthesized
    # Transport bytes are different identities even for the same source page.
    # Retain v1 rows for audit; never overwrite their response hashes.
    scope={**scope,'scope':hashlib.sha256(json.dumps(dict(
        namespace='controller-read-transport-v2',source_scope=scope['scope'],
        streamed=body.get('stream') is True),sort_keys=True).encode()).hexdigest()}
    function=next(t['function'] for t in body['tools'] if t.get('function',{}).get('name')=='read_file')
    args={key:value['enum'][0] for key,value in function['parameters']['properties'].items()}
    dispatch_id='call_controller_read_'+scope['scope'][:24]
    common={'id':'chatcmpl-controller-'+scope['scope'][:24],'model':body['model'],'created':0}
    call={'id':dispatch_id,'type':'function','function':{'name':'read_file','arguments':json.dumps(args,sort_keys=True)}}
    if body.get('stream') is True:
        first={**common,'object':'chat.completion.chunk','choices':[{'index':0,'delta':{'role':'assistant','tool_calls':[{**call,'index':0}]},'finish_reason':None}]}
        last={**common,'object':'chat.completion.chunk','choices':[{'index':0,'delta':{},'finish_reason':'tool_calls'}]}
        data=('data: '+json.dumps(first)+'\n\ndata: '+json.dumps(last)+'\n\ndata: [DONE]\n\n').encode()
        media='text/event-stream'
    else:
        data=json.dumps({**common,'object':'chat.completion','choices':[{'index':0,
            'message':{'role':'assistant','content':None,'tool_calls':[call]},'finish_reason':'tool_calls'}]}).encode()
        media='application/json'
    return {'scope':scope,'data':data,'media_type':media,'dispatch_id':dispatch_id}


@contextmanager
def ledger(counter_path):
    if not counter_path:raise RuntimeError('durable deterministic read counter required')
    counter=Path(counter_path);path=counter.with_name('deterministic-reads.sqlite')
    if counter.is_symlink() or not counter.is_file() or path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError('unsafe deterministic read ledger')
    con=sqlite3.connect(path,timeout=5);path.chmod(0o600)
    try:
        con.execute('PRAGMA synchronous=FULL')
        con.execute('CREATE TABLE IF NOT EXISTS dispatches(scope TEXT PRIMARY KEY,execution_id TEXT,response_sha256 TEXT,provenance TEXT)')
        con.commit();yield con;con.commit()
    except BaseException:con.rollback();raise
    finally:con.close()


def record(counter_path,dispatch):
    scope=dispatch['scope'];digest=hashlib.sha256(dispatch['data']).hexdigest()
    with ledger(counter_path) as con:
        con.execute('BEGIN IMMEDIATE')
        prior=con.execute('SELECT execution_id,response_sha256 FROM dispatches WHERE scope=?',(scope['scope'],)).fetchone()
        if prior:
            if prior!=(scope['execution_id'],digest):raise ValueError('deterministic read identity drift')
            return
        if con.execute('SELECT count(*) FROM dispatches').fetchone()[0]>=8192:raise RuntimeError('deterministic read ledger capacity')
        con.execute('INSERT INTO dispatches VALUES (?,?,?,?)',(scope['scope'],scope['execution_id'],digest,'controller_request_not_read_evidence'))


def status(counter_path,execution_id):
    if not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',execution_id):raise ValueError('exact dispatch execution required')
    with ledger(counter_path) as con:
        count=con.execute('SELECT count(*) FROM dispatches WHERE execution_id=?',(execution_id,)).fetchone()[0]
    return {'execution_id':execution_id,'controller_read_requests':count,'provenance':'controller_request_not_read_evidence'}
