"""Private bounded parse-location receipts, never rejected content or authority."""
import hashlib
import json
import uuid
from deterministic_read_dispatch import ledger
from structured_response_contract import _unique


def describe(data,media):
    stage='outer_json';content=[];calls=[];finish=None
    result=dict(operation='calibration_response_shape_v1',upstream_sha256=hashlib.sha256(data).hexdigest(),
        carrier='sse' if media.startswith('text/event-stream') else 'json',
        finish=None,tool_calls=0,content_bytes=0,json_error=None,phase='unobserved',
        response_forwarded=False,worker_tool_executed=False,delivery_approval=False)
    try:
        if result['carrier']=='sse':
            for line in data.decode().splitlines():
                if not line.startswith('data:'):continue
                raw=line[5:].strip()
                if raw=='[DONE]':continue
                stage='stream_frame_json';frame=json.loads(raw,object_pairs_hook=_unique)
                for choice in frame.get('choices',[]):
                    delta=choice.get('delta',{})
                    if isinstance(delta.get('content'),str):content.append(delta['content'])
                    for call in delta.get('tool_calls',[]):
                        index=call.get('index')
                        if type(index) is not int or not 0<=index<8:raise ValueError()
                        while len(calls)<=index:calls.append('')
                        calls[index]+=call.get('function',{}).get('arguments','')
                    if choice.get('finish_reason') in ('stop','length','tool_calls','content_filter'):finish=choice['finish_reason']
        else:
            value=json.loads(data,object_pairs_hook=_unique);choice=value['choices'][0];message=choice['message']
            if isinstance(message.get('content'),str):content.append(message['content'])
            calls=[x.get('function',{}).get('arguments','') for x in message.get('tool_calls',[])][:8]
            if choice.get('finish_reason') in ('stop','length','tool_calls','content_filter'):finish=choice['finish_reason']
        result.update(finish=finish,tool_calls=len(calls),content_bytes=len(''.join(content).encode()))
        if calls:
            stage='tool_arguments_json'
            for value in calls:json.loads(value,object_pairs_hook=_unique)
        else:
            stage='terminal_content_json';json.loads(''.join(content),object_pairs_hook=_unique)
        result['phase']='json_parsed'
    except json.JSONDecodeError as error:
        result.update(phase=stage,json_error=dict(position=error.pos,line=error.lineno,column=error.colno))
    except Exception:result['phase']=stage+'_unclassified'
    return result


def record(counter,execution,call,data,media):
    if execution is None or counter is None:return
    if str(uuid.UUID(execution))!=execution or type(call) is not int or call<1:raise ValueError('bound parse observation required')
    value=describe(data,media);encoded=json.dumps(value,sort_keys=True)
    with ledger(counter) as con:
        con.execute('CREATE TABLE IF NOT EXISTS calibration_response_observations(execution_id TEXT,call_number INTEGER,receipt TEXT,PRIMARY KEY(execution_id,call_number))')
        old=con.execute('SELECT receipt FROM calibration_response_observations WHERE execution_id=? AND call_number=?',(execution,call)).fetchone()
        if old and old[0]!=encoded:raise ValueError('parse observation drift')
        if not old:con.execute('INSERT INTO calibration_response_observations VALUES(?,?,?)',(execution,call,encoded))
