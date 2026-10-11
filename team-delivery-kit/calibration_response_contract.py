"""Current calibration wire contract, not worker or delivery authorization.

The data producer can inspect additional frozen source files before submitting.
Dynamic fixture dictionaries are validated locally, not misrepresented as a
provider's closed strict schema. Policy attestations use a closed strict schema.
Native identities/read receipts and sandbox evidence remain separate gates.
"""
import hashlib
import json
import re
from artifact_read_evidence import observations,next_read

MARKER='DELIVERY_CALIBRATION_RESPONSE_V1'
CONTEXT='DELIVERY_CALIBRATION_RESPONSE_CONTEXT_V1'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def context(phase,paths,source_sha256,policy_sha256=None,controls_manifest_sha256=None,*,engine=None):
    value=dict(phase=phase,required_paths=sorted(set(paths)),source_sha256=source_sha256,
        policy_sha256=policy_sha256,controls_manifest_sha256=controls_manifest_sha256)
    if engine is not None:value['engine']=engine
    validate_context(value);return value


def validate_context(value):
    fields={'phase','required_paths','source_sha256','policy_sha256','controls_manifest_sha256'}
    if not isinstance(value,dict) or set(value) not in (fields,fields|{'engine'}):
        raise ValueError('exact calibration response context required')
    if 'engine' in value and value['engine'] not in ('unittest_path_fixture_v1','unittest_path_fixtures_v2'):
        raise ValueError('known controller-selected calibration engine required')
    phase=value['phase'];paths=value['required_paths']
    if phase not in ('bundle','attestation','review') or not isinstance(paths,list) or not 1<=len(paths)<=512:
        raise ValueError('bounded calibration phase/reads required')
    if paths!=sorted(set(paths)) or any(not safe_path(p,phase) for p in paths):
        raise ValueError('exact frozen calibration read paths required')
    for key in ('source_sha256','policy_sha256','controls_manifest_sha256'):
        sha=value[key]
        if key!='source_sha256' and phase=='bundle':
            if sha is not None:raise ValueError('producer cannot claim policy hashes')
        elif not isinstance(sha,str) or not re.fullmatch('[a-f0-9]{64}',sha):
            raise ValueError('controller calibration hash required')
    return value


def safe_path(path,phase):
    roots='candidate|previous' if phase=='bundle' else 'candidate|previous|controls|policy'
    return isinstance(path,str) and re.fullmatch(r'/evidence/(?:'+roots+r')/[A-Za-z0-9_./-]+',path) is not None\
        and all(part not in ('','..','.') for part in path.split('/')[1:])


def capsule(value):
    validate_context(value)
    return MARKER+':'+digest(value)+'\n'+CONTEXT+':'+json.dumps(value,sort_keys=True,separators=(',',':'))+'\n'


def request(body):
    lines=[]
    for message in body.get('messages',[]):
        if message.get('role')!='user':continue
        raw=message.get('content','')
        if isinstance(raw,list):raw='\n'.join(p.get('text','') for p in raw if isinstance(p,dict) and p.get('type')=='text')
        if isinstance(raw,str):lines.extend(raw.splitlines())
    markers=[s.removeprefix(MARKER+':') for s in lines if s.startswith(MARKER+':')]
    if not markers:return None
    contexts=[s.removeprefix(CONTEXT+':') for s in lines if s.startswith(CONTEXT+':')]
    if len(markers)!=1 or len(contexts)!=1:raise ValueError('one current calibration capsule required')
    value=json.loads(contexts[0]);validate_context(value)
    if markers[0]!=digest(value):raise ValueError('calibration capsule hash drift')
    return value


def schema(value):
    def obj(properties):return dict(type='object',properties=properties,required=list(properties),additionalProperties=False)
    def text(limit=200):return dict(type='string',minLength=1,maxLength=limit)
    def array(item,maximum=256):return dict(type='array',items=item,minItems=1,maxItems=maximum)
    false=dict(type='boolean',enum=[False])
    objection=obj(dict(action=dict(type='string',enum=['calibration_objection']),reason=text(1200),
        execution_authorized=false,delivery_approval=false))
    if value['phase']!='bundle':
        action='propose_calibration' if value['phase']=='attestation' else 'approve_calibration'
        success=obj(dict(action=dict(type='string',enum=[action]),
            policy_sha256=dict(type='string',enum=[value['policy_sha256']]),
            controls_manifest_sha256=dict(type='string',enum=[value['controls_manifest_sha256']]),
            execution_authorized=false,delivery_approval=false))
    else:
        classes=dict(type='object',minProperties=1,maxProperties=128,additionalProperties=array(text()))
        module=obj(dict(path=text(),fixture_attribute=text(),product_path=text(),positive_fixture=text(),classes=classes))
        negative=obj(dict(id=text(),module=text(),class_name=text(),method=text(),fixture=text(),criteria=array(text(),32)))
        engine=value.get('engine','unittest_path_fixture_v1')
        if engine=='unittest_path_fixtures_v2':
            fixture=obj(dict(attribute=text(),product_path=text(),positive_fixture=text()))
            module=obj(dict(path=text(),fixtures=array(fixture,16),classes=classes))
            replacement=obj(dict(attribute=text(),fixture=text()))
            negative=obj(dict(id=text(),module=text(),class_name=text(),method=text(),
                replacements=array(replacement,16),criteria=array(text(),32)))
        success=obj(dict(action=dict(type='string',enum=['propose_calibration_bundle']),
            engine=dict(type='string',enum=[engine]),modules=array(module,32),negatives=array(negative),
            previous_methods=dict(type='object',minProperties=1,maxProperties=32,additionalProperties=classes),
            controls=dict(type='object',minProperties=1,maxProperties=288,additionalProperties=text(65536)),
            execution_authorized=false,delivery_approval=false))
    return dict(anyOf=[success,objection])


def apply(body):
    value=request(body)
    if value is None:return None
    reads=observations(body['messages'],wire=True)
    missing=[p for p in value['required_paths'] if p not in reads]
    tools=[t for t in body.get('tools',[]) if t.get('function',{}).get('name')=='read_file']
    if missing:
        if len(tools)!=1:raise ValueError('one actual readonly inspection tool required')
        path=missing[0];offset=next_read(body['messages'],path)
        parameters=dict(type='object',properties=dict(path=dict(type='string',enum=[path]),
            offset=dict(type='integer',enum=[offset]),limit=dict(type='integer',enum=[100])),
            required=['path','offset','limit'],additionalProperties=False)
        body['tools']=[{**tools[0],'function':{**tools[0]['function'],'strict':True,'parameters':parameters}}]
        body.pop('response_format',None)
        body['tool_choice']=dict(type='function',function=dict(name='read_file'))
        body['messages'].append(dict(role='system',content='CALIBRATION INSPECTION: read_file '+path+
            ' offset='+str(offset)+' limit=100. No decision before actual full-file receipts.'))
    elif value['phase']=='bundle':
        if len(tools)!=1:raise ValueError('producer readonly inspection tool required')
        parameters=dict(type='object',properties=dict(
            path=dict(type='string',pattern=r'^/evidence/(?:candidate|previous)/[A-Za-z0-9_./-]+$',maxLength=512),
            offset=dict(type='integer',minimum=1),limit=dict(type='integer',minimum=1,maximum=100)),
            required=['path','offset','limit'],additionalProperties=False)
        body['tools']=[{**tools[0],'function':{**tools[0]['function'],'strict':True,'parameters':parameters}}]
        body['tool_choice']='auto';body.pop('response_format',None)
        body['messages'].append(dict(role='system',content='CURRENT CALIBRATION DATA PHASE. '
            'Ignore historical decision formats. Inspect additional candidate product dependencies using only read_file. '
            'Then return exactly propose_calibration_bundle JSON as instructed, or '
            '{"action":"calibration_objection","reason":"concrete cause","execution_authorized":false,"delivery_approval":false}. '
            'No markdown, edits, shell, tests, execution authorization or delivery approval.'))
    else:
        body['tools']=[];body['tool_choice']='none'
        body['response_format']=dict(type='json_schema',json_schema=dict(name='delivery_generic_calibration_v1',strict=True,schema=schema(value)))
    body['provider']={**body.get('provider',{}),'require_parameters':True}
    return body


class CalibrationResponseRejected(ValueError):
    def __init__(self,diagnostic):
        self.diagnostic=diagnostic
        super().__init__('calibration response rejected')


def validate_reply(body,data,media_type):
    try:return _validate_reply(body,data,media_type)
    except Exception as error:
        from jsonschema.exceptions import ValidationError
        keywords={'type','enum','required','additionalProperties','minLength','maxLength','minItems',
            'maxItems','minProperties','maxProperties','pattern','minimum','maximum','anyOf'}
        fields={'action','engine','modules','negatives','previous_methods','controls','execution_authorized',
            'delivery_approval','reason','path','fixture_attribute','product_path','positive_fixture','classes',
            'id','module','class_name','method','fixture','criteria','fixtures','attribute','replacements'}
        constraints=set();locations=set();missing=set()
        if isinstance(error,ValidationError):
            pending=[error]
            for _ in range(1024):
                if not pending:break
                item=pending.pop()
                constraints.add(item.validator if item.validator in keywords else 'other')
                locations.update(part for part in item.absolute_schema_path if isinstance(part,str) and part in fields)
                if item.validator=='required' and isinstance(item.instance,dict):
                    missing.update(part for part in item.validator_value if part in fields and part not in item.instance)
                pending.extend(item.context)
            category='schema_violation'
        elif isinstance(error,json.JSONDecodeError):category='invalid_json'
        else:category='invalid_transport_or_tool'
        diagnostic=dict(version='calibration-constraint-v1',category=category,
            constraints=sorted(constraints),fields=sorted(locations),missing_fields=sorted(missing),
            upstream_sha256=hashlib.sha256(data).hexdigest())
        raise CalibrationResponseRejected(diagnostic) from None


def _validate_reply(body,data,media_type):
    """Validate producer tool turns or final JSON; never manufactures read proof."""
    value=request(body)
    if value is None or isinstance(body.get('tool_choice'),dict):return False
    if value['phase']!='bundle':return False # Normal strict decision validator.
    from jsonschema import Draft202012Validator
    from structured_response_contract import _unique
    content=[];calls={};finish=None;done=False;trailer=False
    if media_type.startswith('text/event-stream'):
        for line in data.decode().splitlines():
            if not line.startswith('data:'):continue
            raw=line[5:].strip()
            if raw=='[DONE]':
                if done or finish is None:raise ValueError('incomplete calibration stream')
                done=True;continue
            if done:raise ValueError('calibration data after terminal')
            frame=json.loads(raw,object_pairs_hook=_unique)
            if frame.get('error'):raise ValueError('provider calibration stream error')
            choices=frame.get('choices',[])
            if not choices:continue
            if len(choices)!=1 or choices[0].get('index',0)!=0:raise ValueError('ambiguous calibration choice')
            entry=choices[0];delta=entry.get('delta',{})
            if delta.get('function_call'):raise ValueError('legacy calibration function call forbidden')
            if finish is not None:
                if trailer or delta or entry.get('finish_reason')!=finish:raise ValueError('calibration data after finish')
                trailer=True
                continue
            if delta.get('content'):content.append(delta['content'])
            for call in delta.get('tool_calls',[]):
                index=call.get('index');function=call.get('function',{})
                if type(index) is not int or not 0<=index<8:raise ValueError('bounded tool index required')
                item=calls.setdefault(index,dict(name='',arguments=''))
                item['name']+=function.get('name','');item['arguments']+=function.get('arguments','')
            if entry.get('finish_reason') is not None:finish=entry['finish_reason']
        if not done:raise ValueError('incomplete calibration stream')
    else:
        reply=json.loads(data,object_pairs_hook=_unique);choices=reply.get('choices',[])
        if len(choices)!=1:raise ValueError('one calibration choice required')
        entry=choices[0];finish=entry.get('finish_reason');message=entry['message']
        if message.get('function_call'):raise ValueError('legacy calibration function call forbidden')
        content=[message.get('content') or '']
        calls={i:call['function'] for i,call in enumerate(message.get('tool_calls',[]))}
    if calls:
        if finish!='tool_calls' or len(calls)>8:raise ValueError('actual readonly tool turn required')
        for call in calls.values():
            args=json.loads(call['arguments'],object_pairs_hook=_unique)
            if (call['name']!='read_file' or set(args)!= {'path','offset','limit'} or not safe_path(args['path'],'bundle')
                    or type(args['offset']) is not int or args['offset']<1
                    or type(args['limit']) is not int or not 1<=args['limit']<=100):
                raise ValueError('calibration tool must be a bounded frozen read')
    else:
        if finish!='stop':raise ValueError('terminal calibration JSON required')
        raw=''.join(content)
        if not 1<=len(raw.encode())<=786432:raise ValueError('bounded calibration artifact required')
        item=json.loads(raw,object_pairs_hook=_unique)
        Draft202012Validator(schema(value)).validate(item)
    return True
