"""Full observed ACP read results, before the UI's output truncation."""
import json


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS observed_read_stream(task_id TEXT, request_id TEXT, '
                'call_id TEXT, messages TEXT, PRIMARY KEY(task_id,call_id))')


def extract(notifications):
    starts={};results=[]
    for frame in notifications:
        if frame.get('method')!='session/update':continue
        update=(frame.get('params') or {}).get('update') or {}
        identifier=update.get('toolCallId')
        if not isinstance(identifier,str) or not identifier:continue
        if (update.get('sessionUpdate')=='tool_call' and update.get('kind')=='read'
                and isinstance(update.get('title'),str) and update['title'].startswith(
                    ('read: /evidence/candidate/','read: /evidence/previous/','read: /delivery/'))):
            starts[identifier]=update['title'].removeprefix('read: ')
        if update.get('sessionUpdate')!='tool_call_update' or update.get('status')!='completed' or identifier not in starts:
            continue
        blocks=update.get('content') or []
        text='\n'.join(part.get('content',{}).get('text','') for part in blocks
            if part.get('type')=='content' and part.get('content',{}).get('type')=='text')
        if not text.startswith('Read '+starts[identifier]) or len(text.encode())>131072:continue
        results.append([{'type':'tool_use','tool':'read_file','call_id':identifier,'input':{'path':starts[identifier]}},
                        {'type':'tool_result','tool':'read_file','call_id':identifier,'output':text}])
    return results


def store(con,binding,notifications,mode):
    if not binding or mode not in ('planning','review'):return
    initialize(con)
    from artifact_read_evidence import coverage
    for messages in extract(notifications):
        if not coverage(messages):continue  # never promote a cut/malformed page
        identifier=messages[0]['call_id'];encoded=json.dumps(messages,sort_keys=True)
        old=con.execute('SELECT request_id,messages FROM observed_read_stream WHERE task_id=? AND call_id=?',
                        (binding['task_id'],identifier)).fetchone()
        if old:
            if old[0]!=binding['request_id'] or old[1]!=encoded:raise ValueError('observed read identity drift')
        else:
            if con.execute('SELECT count(*) FROM observed_read_stream WHERE task_id=?',(binding['task_id'],)).fetchone()[0]>=128:
                raise ValueError('observed read page limit')
            con.execute('INSERT INTO observed_read_stream VALUES (?,?,?,?)',
                        (binding['task_id'],binding['request_id'],identifier,encoded))


def load(con,task):
    initialize(con)
    result=[]
    for row in con.execute('SELECT r.messages FROM observed_read_stream r JOIN native_bindings n '
                          'ON n.request_id=r.request_id AND n.task_id=r.task_id WHERE r.task_id=? ORDER BY r.rowid',(task,)):
        result.extend(json.loads(row[0]))
    return result


def merge(native_messages,durable):
    """Full controller transport replaces only the same UI call's read pair.

    Durable must come from load(task), which joins the native request binding.
    Other calls remain distinct; contradictory reads across calls still fail.
    """
    from artifact_read_evidence import coverage
    pairs={}
    for index in range(0,len(durable),2):
        pair=durable[index:index+2]
        if (len(pair)!=2 or pair[0].get('type')!='tool_use' or pair[1].get('type')!='tool_result'
                or pair[0].get('tool')!='read_file' or pair[1].get('tool')!='read_file'
                or not pair[0].get('call_id') or pair[0]['call_id']!=pair[1].get('call_id')
                or pair[0]['call_id'] in pairs or not coverage(pair)):
            raise ValueError('invalid durable read pair')
        pairs[pair[0]['call_id']]=pair
    result=[m for m in native_messages if not (m.get('call_id') in pairs
        and m.get('type') in ('tool_use','tool_result') and m.get('tool')=='read_file')]
    return result+[m for pair in pairs.values() for m in pair]


def observed(native_messages,durable):
    """Task-bound controller receipts are authoritative, not UI projections.

    Multica replaces provider call IDs with fresh transcript UUIDs. Do not guess
    an alias or merge conflicting UI-rendered lines into the original stream.
    Incomplete/conflicting durable pages suppress UI fallback for that file.
    """
    from artifact_read_evidence import observations
    validated=merge([],durable)
    paths={m['input']['path'] for m in validated if m['type']=='tool_use'}
    result={p:r for p,r in observations(native_messages).items() if p not in paths}
    result.update(observations(validated))
    return result
