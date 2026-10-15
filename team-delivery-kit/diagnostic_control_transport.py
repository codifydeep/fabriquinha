"""Opt-in DATA carrier. Never executes a virtual function or repairs model JSON.

Only after canonical mandatory reads: retain real read_file, require a tool
choice, and consume the distinct data carrier locally. Full canonical schema
validation remains authoritative; provider hints intentionally contain no union.
"""
import copy
import hashlib
import json
import re
import uuid
import calibration_response_contract as contract
from structured_response_contract import _unique,StructuredResponseRejected

MARKER='DELIVERY_DIAGNOSTIC_CONTROL_TRANSPORT_V1'
NAME='return_diagnostic_control_data'


def require(ok):
    if not ok:raise ValueError('exact diagnostic data transport required')


def binding(body):
    found=[]
    for m in body.get('messages',[]):
        if m.get('role')!='user':continue
        text=m.get('content','')
        if isinstance(text,list):text='\n'.join(p.get('text','') for p in text if isinstance(p,dict) and p.get('type')=='text')
        if isinstance(text,str):found.extend(line[len(MARKER)+1:] for line in text.splitlines() if line.startswith(MARKER+':'))
    if not found:return None
    require(len(found)==1 and bool(re.fullmatch('[a-f0-9]{64}',found[0])))
    value=contract.request(body);require(value is not None and value['phase']=='bundle' and value['source_sha256']==found[0]);return value


def selected(body):
    value=binding(body)
    if value is None or body.get('tool_choice')!='auto':return None
    require(body.get('model')=='anthropic/claude-haiku-5.5')
    canonical=contract.apply(copy.deepcopy(body))
    require(canonical['tool_choice']=='auto' and body.get('tools')==canonical['tools']
        and body.get('response_format') is None and (body.get('provider') or {}).get('require_parameters') is True)
    return value


def project(body):
    value=selected(body)
    if value is None:return None
    success,objection=contract.schema(value)['anyOf']
    props=copy.deepcopy(success['properties']);props['action']['enum']=['propose_calibration_bundle','calibration_objection']
    props['reason']=copy.deepcopy(objection['properties']['reason'])
    # Provider-compatible hints, NOT the canonical union and NOT validation.
    hints=dict(type='object',properties=props,required=['action','execution_authorized','delivery_approval'],additionalProperties=False)
    require('anyOf' not in json.dumps(hints))
    result=copy.deepcopy(body);result.pop('response_format',None)
    result['tools'].append(dict(type='function',function=dict(name=NAME,strict=False,parameters=hints,
        description='Return diagnostic control data only. No tool execution, files changed, registration or approval.')))
    result.update(tool_choice='required',parallel_tool_calls=False)
    result['provider']={**result.get('provider',{}),'require_parameters':False}
    result['messages'].append(dict(role='system',content='DIAGNOSTIC DATA TRANSPORT. Use read_file for additional frozen dependencies. '
        'Finish by calling '+NAME+' with the exact complete proposal object or calibration_objection object as arguments. '
        'No prose, JSON text answer or markdown. This function is a DATA carrier only: never executed by the worker. '
        'The unchanged full local schema validates every field. No operation or delivery is approved.'))
    return result


def packet(data,media):
    """One terminal tool call, including bounded streamed fragments/trailer."""
    meta={};name='';arguments='';finished=False;done=False;trailer=False;seen=False;identity=None
    def metadata(frame):
        for key in ('id','created','model','system_fingerprint','usage'):
            if key in frame:meta[key]=frame[key]
    def add(call):
        nonlocal name,arguments,seen,identity
        require(call.get('type') in (None,'function') and type(call.get('index',0)) is int and call.get('index',0)==0)
        if call.get('id') is not None:
            require(isinstance(call['id'],str) and 1<=len(call['id'])<=200 and identity in (None,call['id']));identity=call['id']
        fn=call.get('function',{});n=fn.get('name','');a=fn.get('arguments','')
        require(n is None or isinstance(n,str));require(a is None or isinstance(a,str));n=n or '';a=a or ''
        require(isinstance(n,str) and isinstance(a,str));name+=n;arguments+=a;seen=True
        require(len(name)<=100 and len(arguments.encode())<=786432)
    if media.startswith('text/event-stream'):
        for line in data.decode().splitlines():
            if not line.startswith('data:'):continue
            text=line[5:].strip()
            if text=='[DONE]':require(finished and not done);done=True;continue
            require(not done);frame=json.loads(text,object_pairs_hook=_unique);require(not frame.get('error'));metadata(frame)
            choices=frame.get('choices',[])
            if not choices:continue
            require(len(choices)==1 and type(choices[0].get('index',0)) is int and choices[0].get('index',0)==0)
            choice=choices[0];delta=choice.get('delta',{})
            require(delta.get('content') in (None,'') and not delta.get('function_call') and delta.get('role') in (None,'assistant'))
            if finished:
                require(not trailer and choice.get('finish_reason')=='tool_calls' and set(delta)<={'role','content','tool_calls'}
                    and not delta.get('tool_calls'));trailer=True;continue
            calls=delta.get('tool_calls',[]);require(isinstance(calls,list) and len(calls)<=1)
            if calls:add(calls[0])
            finish=choice.get('finish_reason')
            if finish is not None:require(finish=='tool_calls');finished=True
        require(done and finished)
    else:
        frame=json.loads(data,object_pairs_hook=_unique);require(not frame.get('error'));metadata(frame)
        choices=frame.get('choices',[]);require(len(choices)==1 and type(choices[0].get('index',0)) is int
            and choices[0].get('index',0)==0 and choices[0].get('finish_reason')=='tool_calls')
        message=choices[0]['message'];require(message.get('content') in (None,'') and not message.get('function_call'))
        calls=message.get('tool_calls',[]);require(len(calls)==1);add(calls[0])
    require(seen and bool(name) and bool(arguments));return name,arguments,meta,identity


def emit(arguments,media,meta):
    if media.startswith('text/event-stream'):
        common={k:v for k,v in meta.items() if k!='usage'};common['object']='chat.completion.chunk'
        frames=[{**common,'choices':[dict(index=0,delta=dict(role='assistant',content=arguments),finish_reason=None)]},
            {**common,'choices':[dict(index=0,delta={},finish_reason='stop')]}]
        if 'usage' in meta:frames.append({**common,'choices':[],'usage':meta['usage']})
        return (''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n').encode(),'text/event-stream'
    return json.dumps({**meta,'object':'chat.completion','choices':[dict(index=0,message=dict(role='assistant',content=arguments),finish_reason='stop')]}).encode(),'application/json'


def translate(body,data,media):
    value=selected(body)
    if value is None:return data,media,None
    try:
        name,arguments,meta,identity=packet(data,media)
        require(name in (NAME,'read_file'))
        target='text/event-stream' if body.get('stream') is True else 'application/json' if body.get('stream') is False else media
        if name=='read_file' and (media.startswith('text/event-stream') or target!=media):
            require(identity is not None)
            call=dict(id=identity,type='function',function=dict(name=name,arguments=arguments))
            if target.startswith('text/event-stream'):
                common={k:v for k,v in meta.items() if k!='usage'}
                frames=[{**common,'choices':[dict(index=0,delta=dict(role='assistant',tool_calls=[{**call,'index':0}]),finish_reason='tool_calls')]}]
                if 'usage' in meta:frames.append({**common,'choices':[],'usage':meta['usage']})
                output=(''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n').encode();out_media='text/event-stream'
            else:
                output=json.dumps({**meta,'choices':[dict(index=0,message=dict(role='assistant',content=None,tool_calls=[call]),finish_reason='tool_calls')]}).encode();out_media='application/json'
        else:output,out_media=(data,media) if name=='read_file' else emit(arguments,target,meta)
        try:contract.validate_reply(body,output,out_media)
        except contract.CalibrationResponseRejected as error:
            raise StructuredResponseRejected('calibration_response_invalid',
                {**error.diagnostic,'upstream_sha256':hashlib.sha256(data).hexdigest()}) from None
        if name=='read_file':return output,out_media,None
        return output,out_media,dict(operation='diagnostic_control_data_carrier_v1',source_sha256=value['source_sha256'],
            upstream_sha256=hashlib.sha256(data).hexdigest(),arguments_sha256=hashlib.sha256(arguments.encode()).hexdigest(),
            payload_sha256=contract.digest(json.loads(arguments,object_pairs_hook=_unique)),
            output_sha256=hashlib.sha256(output).hexdigest(),canonical_schema_validation_preserved=True,
            worker_tool_executed=False,execution_authorized=False,delivery_approval=False)
    except StructuredResponseRejected:raise
    except (ValueError,KeyError,TypeError,IndexError):raise StructuredResponseRejected('nonterminal_or_non_json_response') from None


def validate_receipt(value):
    require(set(value)=={'operation','source_sha256','upstream_sha256','arguments_sha256','payload_sha256','output_sha256',
        'canonical_schema_validation_preserved','worker_tool_executed','execution_authorized','delivery_approval'}
        and value['operation']=='diagnostic_control_data_carrier_v1' and value['canonical_schema_validation_preserved'] is True
        and all(value[k] is False for k in ('worker_tool_executed','execution_authorized','delivery_approval'))
        and all(bool(re.fullmatch('[a-f0-9]{64}',value[k])) for k in value if k.endswith('_sha256')))
    return value


def record(counter,execution,call,receipt):
    if counter is None or execution is None:return
    require(str(uuid.UUID(execution))==execution and type(call) is int and call>0);validate_receipt(receipt)
    from deterministic_read_dispatch import ledger
    encoded=json.dumps(receipt,sort_keys=True)
    with ledger(counter) as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute('CREATE TABLE IF NOT EXISTS diagnostic_control_carriers(execution_id TEXT,call_number INTEGER,receipt TEXT,PRIMARY KEY(execution_id,call_number))')
        row=con.execute('SELECT receipt FROM diagnostic_control_carriers WHERE execution_id=? AND call_number=?',(execution,call)).fetchone()
        if row:require(row[0]==encoded)
        else:con.execute('INSERT INTO diagnostic_control_carriers VALUES(?,?,?)',(execution,call,encoded))


def read(counter,execution):
    require(str(uuid.UUID(execution))==execution)
    from deterministic_read_dispatch import ledger
    with ledger(counter) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='diagnostic_control_carriers'").fetchone():return []
        return [{**validate_receipt(json.loads(row[1])), 'execution_id':execution,'call_number':row[0]}
            for row in con.execute('SELECT call_number,receipt FROM diagnostic_control_carriers WHERE execution_id=? ORDER BY call_number',(execution,))]
