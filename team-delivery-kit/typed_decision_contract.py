"""Opt-in non-executing typed decision submission at the controller proxy.

Only schema-valid model tool arguments become terminal JSON. No worker tool is
executed, no prose is mined, and no approval/permission is manufactured.
"""
import copy
import hashlib
import json
import re
from jsonschema import Draft202012Validator
from structured_response_contract import StructuredResponseRejected,_unique

NAME='submit_delivery_decision'
MARKER='DELIVERY_TYPED_DECISION_V1'
REVIEW_NAME='submit_test_review'
REVIEW_MARKER='DELIVERY_TYPED_REVIEW_V1'
EVIDENCE_NAME='submit_deployment_evidence'
EVIDENCE_MARKER='DELIVERY_TYPED_DEPLOYMENT_EVIDENCE_V1'
VALIDATION_NAME='submit_deployment_validation_request'
DECOMPOSITION_MARKER='DELIVERY_TYPED_DECOMPOSITION_V1'
LENGTH_MARKER='DELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1'
RECOVERY_NAME='submit_worker_recovery_request'
RECOVERY_MARKER='DELIVERY_TYPED_WORKER_RECOVERY_V1'


def length_feedback_enabled(body):
    return body.get('tool_choice') in ({'type':'function','function':{'name':NAME}},
        {'type':'function','function':{'name':RECOVERY_NAME}}) and any(
        m.get('role')=='user' and isinstance(m.get('content'),str)
        and re.search(r'^'+LENGTH_MARKER+r'$',m['content'],re.M) for m in body.get('messages',[]))


def length_feedback_preflight(counter_path,execution_id,body):
    if not length_feedback_enabled(body):return
    from deterministic_read_dispatch import ledger
    with ledger(counter_path) as con:
        con.execute('CREATE TABLE IF NOT EXISTS technical_length_feedback(execution_id TEXT PRIMARY KEY,receipt TEXT)')
        if con.execute('SELECT 1 FROM technical_length_feedback WHERE execution_id=?',(execution_id,)).fetchone():
            raise StructuredResponseRejected('typed_length_feedback_consumed')


def claim_length_feedback(counter_path,execution_id,error,body,first_call):
    feedback=getattr(error,'length_feedback',None)
    if not feedback or not length_feedback_enabled(body):return None
    if not isinstance(execution_id,str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',execution_id):return None
    from deterministic_read_dispatch import ledger
    receipt={'operation':'technical_length_feedback_v1','first_call':first_call,
        'rejected_upstream_sha256':error.receipt['upstream_sha256'],'attempt_limit':1,
        'worker_tool_executed':False,'delivery_approval':False}
    with ledger(counter_path) as con:
        con.execute('CREATE TABLE IF NOT EXISTS technical_length_feedback(execution_id TEXT PRIMARY KEY,receipt TEXT)')
        if con.execute('SELECT 1 FROM technical_length_feedback WHERE execution_id=?',(execution_id,)).fetchone():return None
        con.execute('INSERT INTO technical_length_feedback VALUES (?,?)',(execution_id,json.dumps(receipt,sort_keys=True)))
    revised=copy.deepcopy(body);revised['messages'].extend(feedback)
    return revised


def apply(body):
    recoveries={v for m in body.get('messages',[]) if m.get('role')=='user' and isinstance(m.get('content'),str)
        for v in re.findall(r'^'+RECOVERY_MARKER+r':([a-f0-9]{64})$',m['content'],re.M)}
    if recoveries:
        notes='\n'.join(m['content'] for m in body['messages'] if m.get('role')=='user' and isinstance(m.get('content'),str))
        spec=body.get('response_format',{}).get('json_schema',{})
        expected={'type':'object','properties':{
            'action':{'type':'string','enum':['retry_author','escalate_cto']},
            'reason':{'type':'string','minLength':1,'maxLength':1200},
            'optional_files':{'type':'array','items':{'type':'string'},'maxItems':0}},
            'required':['action','reason','optional_files'],'additionalProperties':False}
        if (len(recoveries)!=1 or spec.get('name')!='delivery_decision_v1' or spec.get('strict') is not True
                or spec.get('schema')!=expected or any(not re.search(r'^'+mark+r'$',notes,re.M) for mark in
                    ('DELIVERY_STRUCTURED_DECISION_V1:technical','DELIVERY_EXECUTION_REPAIR_V1','DELIVERY_WORKER_INTERRUPTION_RECOVERY_V1'))
                or re.search(r'^DELIVERY_TYPED_(?:DECISION|REVIEW|DECOMPOSITION|DEPLOYMENT|WORK_PROPOSAL)',notes,re.M)):
            raise ValueError('exact isolated worker recovery request contract required')
        result=copy.deepcopy(body);result.pop('response_format',None);result.pop('parallel_tool_calls',None)
        result['tools']=[{'type':'function','function':{'name':RECOVERY_NAME,'strict':True,
            'description':'Submit recovery-request data only. This tool never runs a worker or grants retry authority; the controller checks independent CTO identity, durable evidence and the unused allowance.',
            'parameters':expected}}]
        result['tool_choice']={'type':'function','function':{'name':RECOVERY_NAME}}
        result['messages'].append({'role':'user','content':LENGTH_MARKER+'\n'})
        result['messages'].append({'role':'system','content':'Call '+RECOVERY_NAME+' exactly once with actual arguments. '
            'No prose or simulated tool call. reason target420characters, limit1200. No operation executes; '
            'no Red, tests, worker restart, merge or approval is implied.'})
        return result
    from work_proposal_contract import schema as work_schema
    proposals={v for m in body.get('messages',[]) if m.get('role')=='user' and isinstance(m.get('content'),str)
        for v in re.findall(r'^DELIVERY_TYPED_WORK_PROPOSAL_V1:([a-f0-9]{64})$',m['content'],re.M)}
    if proposals:
        if len(proposals)!=1:raise ValueError('one work proposal digest required')
        sha=proposals.pop();spec=body.get('response_format',{}).get('json_schema',{})
        if spec.get('name')!='delivery_work_proposal_v1' or spec.get('strict') is not True or spec.get('schema')!=work_schema(sha):
            raise ValueError('exact non-authorizing work proposal schema required')
        result=copy.deepcopy(body);result.pop('response_format',None)
        result['tools']=[{'type':'function','function':{'name':NAME,'strict':True,
            'description':'Submit work proposal data only; no task executes and no release is approved.', 'parameters':spec['schema']}}]
        result['tool_choice']={'type':'function','function':{'name':NAME}}
        return result
    validations={v for m in body.get('messages',[]) if m.get('role')=='user' and isinstance(m.get('content'),str)
        for v in re.findall(r'^DELIVERY_TYPED_DEPLOYMENT_VALIDATION_V1:([a-f0-9]{64})$',m['content'],re.M)}
    if validations:
        from decision_schema import validation_schema
        if len(validations)!=1 or any(re.search(r'^DELIVERY_TYPED_(?:DECISION|REVIEW|DECOMPOSITION|DEPLOYMENT_EVIDENCE)_V1',
                str(m.get('content','')),re.M) for m in body['messages']):raise ValueError('conflicting typed validation contracts')
        sha=next(iter(validations));spec=body.get('response_format',{}).get('json_schema',{})
        if (spec.get('name')!='delivery_deployment_validation_v1' or spec.get('strict') is not True
                or spec.get('schema')!=validation_schema(sha)):raise ValueError('fixed validation request schema required')
        result=copy.deepcopy(body);result.pop('response_format',None);result.pop('parallel_tool_calls',None)
        result['tools']=[{'type':'function','function':{'name':VALIDATION_NAME,'strict':True,
            'description':'Request one fixed QA operation. No worker tool executes; controller validates caller and scope.',
            'parameters':spec['schema']}}]
        result['tool_choice']={'type':'function','function':{'name':VALIDATION_NAME}}
        result['messages'].append({'role':'system','content':'Call '+VALIDATION_NAME+' once. Use actual tool arguments, '
            'not text simulation. reason <=600 characters. This only requests QA; no test has executed yet.'})
        return result
    evidence={sha for m in body.get('messages',[]) if m.get('role')=='user' and isinstance(m.get('content'),str)
        for sha in re.findall(r'^'+EVIDENCE_MARKER+r':([a-f0-9]{64})$',m['content'],re.M)}
    if evidence:
        if len(evidence)!=1 or any(re.search(r'^DELIVERY_TYPED_(?:DECISION|REVIEW|DECOMPOSITION)_V1',
                str(m.get('content','')),re.M) for m in body.get('messages',[])):
            raise ValueError('conflicting typed evidence contracts')
        sha=next(iter(evidence));spec=body.get('response_format',{}).get('json_schema',{})
        schema=spec.get('schema',{});props=schema.get('properties',{})
        if (spec.get('name')!='delivery_deployment_evidence_v1' or spec.get('strict') is not True
                or props.get('evidence_sha256',{}).get('enum')!=[sha]
                or props.get('reason',{}).get('maxLength')!=1200
                or props.get('decision',{}).get('enum')!=['ACCEPT_EVIDENCE','REQUEST_CHANGES']
                or any(props.get(k,{}).get('enum')!=[False] for k in
                    ('release_homologated','product_admission_authorized','historical_tdd_red'))
                or schema.get('additionalProperties') is not False
                or set(schema.get('required',[]))!=set(props)):
            raise ValueError('exact non-authorizing deployment evidence schema required')
        result=copy.deepcopy(body);result.pop('response_format',None);result.pop('parallel_tool_calls',None)
        result['tools']=[{'type':'function','function':{'name':EVIDENCE_NAME,'strict':True,
            'description':'Submit evidence assessment data, never execute a worker tool or approve a release.',
            'parameters':schema}}]
        result['tool_choice']={'type':'function','function':{'name':EVIDENCE_NAME}}
        result['messages'].append({'role':'system','content':'Call '+EVIDENCE_NAME+' exactly once with schema-valid arguments. '
            'No prose, fences or tool-result simulation. reason target <=600 characters. '
            'This data submission does not execute a tool, independently run QA or approve a release.'})
        return result
    decomposition=any(m.get('role')=='user' and isinstance(m.get('content'),str)
        and re.search(r'^'+DECOMPOSITION_MARKER+r'$',m['content'],re.M) for m in body.get('messages',[]))
    marked=any(m.get('role')=='user' and isinstance(m.get('content'),str)
        and re.search(r'^'+MARKER+r'$',m['content'],re.M) for m in body.get('messages',[]))
    reviews={sha for m in body.get('messages',[]) if m.get('role')=='user' and isinstance(m.get('content'),str)
        for sha in re.findall(r'^'+REVIEW_MARKER+r':([a-f0-9]{64})$',m['content'],re.M)}
    if not marked and not reviews and not decomposition:return body
    if len(reviews)>1 or (marked and reviews) or (decomposition and (marked or reviews)):
        raise ValueError('conflicting typed contracts')
    review=next(iter(reviews)) if reviews else None
    if review:
        modes={sha for m in body.get('messages',[]) if m.get('role')=='user' and isinstance(m.get('content'),str)
            for sha in re.findall(r'^DELIVERY_STRUCTURED_DECISION_V1:test_review:([a-f0-9]{64})$',m['content'],re.M)}
        if modes!={review}:raise ValueError('same snapshot review contract required')
    fmt=body.get('response_format',{})
    if not fmt and body.get('tool_choice')=={'type':'function','function':{'name':'read_file'}}:
        return body  # mandatory inspection is never replaced by a verdict tool
    spec=fmt.get('json_schema',{})
    if fmt.get('type')!='json_schema' or spec.get('name')!='delivery_decision_v1':
        raise ValueError('typed decision requires completed technical decision schema')
    schema=spec['schema']
    if review:
        props=schema.get('properties',{})
        if (set(props) not in ({'action','reason','optional_files','manifest_sha256'},
                {'action','reason','optional_files','manifest_sha256','findings'})
                or props['action'].get('enum')!=['approve_test_revision','reject_test_revision']
                or props['manifest_sha256'].get('enum')!=[review]
                or props['optional_files'].get('maxItems')!=0):
            raise ValueError('immutable test review schema required')
    elif decomposition:
        props=schema.get('properties',{})
        if (set(props)!={'action','reason','optional_files','units'}
                or props['action'].get('enum')!=['propose_test_decomposition','escalate_cto']
                or props['optional_files'].get('maxItems')!=0
                or set(props['units'].get('items',{}).get('properties',{}))!=
                    {'id','depends_on','criteria','objective'}):
            raise ValueError('non-executing decomposition schema required')
    elif (set(schema.get('properties',{}))!={'action','reason','optional_files'}
            or not set(schema['properties']['action'].get('enum',[]))<=
                {'request_correction','request_test_revision','escalate_cto'}):
        raise ValueError('typed submission cannot grant review or execution authority')
    name=REVIEW_NAME if review else NAME
    result=copy.deepcopy(body)
    result.pop('response_format',None);result.pop('parallel_tool_calls',None)
    result['tools']=[{'type':'function','function':{'name':name,'strict':True,
        'description':'Submit schema-valid decision data only; the controller independently validates identity, reads and snapshot before accepting any verdict.',
        'parameters':schema}}]
    result['tool_choice']={'type':'function','function':{'name':name}}
    execution_diagnosis = any(m.get('role') == 'user' and isinstance(m.get('content'), str)
        and re.search(r'^DELIVERY_EXECUTION_DIAGNOSIS_V1$', m['content'], re.M)
        for m in body.get('messages', []))
    if (execution_diagnosis and name == NAME
            and schema['properties']['action'].get('enum') == ['escalate_cto']
            and schema['properties']['reason'].get('maxLength') == 1200):
        # At most one format-only response per execution, enforced by the
        # existing durable length-feedback ledger. No action/schema is broadened.
        result['messages'].append({'role':'user', 'content':LENGTH_MARKER + '\n'})
    result['messages'].append({'role':'system','content':
        'TYPED DECISION PHASE: call '+name+' exactly once with every required schema field. '
        'Use actual tool arguments, not prose or a Markdown code block. This is a non-executing data submission. '
        'No approval, file change, test execution, merge, budget exception or release completion is implied. '
        'reason must fit the schema limit. Prefer one concise concrete recommendation.'})
    return result


def selected(body):
    return body.get('tool_choice') in ({'type':'function','function':{'name':NAME}},
                                     {'type':'function','function':{'name':REVIEW_NAME}},
                                     {'type':'function','function':{'name':EVIDENCE_NAME}},
                                     {'type':'function','function':{'name':VALIDATION_NAME}},
                                     {'type':'function','function':{'name':RECOVERY_NAME}})


def normalize_technical_padding(body,data,media_type):
    """Normalize <=16 ASCII formatting chars; never prose, review or arguments."""
    if body.get('tool_choice') not in ({'type':'function','function':{'name':NAME}},
            {'type':'function','function':{'name':RECOVERY_NAME}}):return data,None
    return _normalize_ascii_padding(data,media_type,'technical_ascii_padding_normalization_v1')


def normalize_review_padding(body,data,media_type):
    """Opt-in transport formatting only; does not accept a review or alter args."""
    if body.get('tool_choice')!={'type':'function','function':{'name':REVIEW_NAME}}:return data,None
    try:
        props=body['tools'][0]['function']['parameters']['properties']
        snapshots=props['manifest_sha256']['enum']
        if (props['action']['enum']!=['approve_test_revision','reject_test_revision']
                or len(snapshots)!=1 or not re.fullmatch('[a-f0-9]{64}',snapshots[0])):
            return data,None
    except (KeyError,TypeError,IndexError):return data,None
    normalized,receipt=_normalize_ascii_padding(data,media_type,'review_ascii_padding_normalization_v1')
    if receipt:receipt.update(manifest_sha256=snapshots[0],review_acceptance_by_proxy=False)
    return normalized,receipt


def normalize_evidence_padding(body,data,media_type):
    if body.get('tool_choice')!={'type':'function','function':{'name':EVIDENCE_NAME}}:return data,None
    try:
        props=body['tools'][0]['function']['parameters']['properties']
        if any(props[k].get('enum')!=[False] for k in
                ('release_homologated','product_admission_authorized','historical_tdd_red')):return data,None
    except (KeyError,TypeError,IndexError):return data,None
    return _normalize_ascii_padding(data,media_type,'deployment_evidence_ascii_padding_v1')


def normalize_validation_padding(body,data,media_type):
    if body.get('tool_choice')!={'type':'function','function':{'name':VALIDATION_NAME}}:return data,None
    try:
        props=body['tools'][0]['function']['parameters']['properties']
        if props['operation'].get('enum')!=['run_fixed_deployment_qa']:return data,None
        if any(props[k].get('enum')!=[False] for k in
                ('release_homologated','product_admission_authorized')):return data,None
    except (KeyError,TypeError,IndexError):return data,None
    return _normalize_ascii_padding(data,media_type,'deployment_validation_ascii_padding_v1')


def _normalize_ascii_padding(data,media_type,operation):
    original=data;count=0
    def clean(message,terminal_seen=False):
        nonlocal count
        content=message.get('content')
        if content in (None,''):return
        if (terminal_seen or not isinstance(content,str) or re.fullmatch(r'[ \t\r\n]+',content) is None
                or count+len(content)>16):raise ValueError()
        count+=len(content);message['content']=''
    try:
        if media_type.startswith('text/event-stream'):
            lines=data.decode().splitlines();finished=False;done=False
            for index,line in enumerate(lines):
                if not line.startswith('data:'):continue
                raw=line[5:].strip()
                if raw=='[DONE]':done=True;continue
                frame=json.loads(raw,object_pairs_hook=_unique)
                choices=frame.get('choices',[])
                if done:raise ValueError()
                if not choices:continue
                if len(choices)!=1:raise ValueError()
                entry=choices[0];delta=entry.get('delta',{})
                clean(delta,finished)
                if entry.get('finish_reason') is not None:finished=True
                lines[index]='data: '+json.dumps(frame,separators=(',',':'))
            normalized=('\n'.join(lines)+'\n').encode()
        else:
            frame=json.loads(data,object_pairs_hook=_unique)
            if len(frame.get('choices',[]))!=1:raise ValueError()
            clean(frame['choices'][0]['message'])
            normalized=json.dumps(frame,separators=(',',':')).encode()
        if not count:return original,None
        return normalized,dict(operation=operation,
            original_upstream_sha256=hashlib.sha256(original).hexdigest(),
            normalized_upstream_sha256=hashlib.sha256(normalized).hexdigest(),padding_chars=count,
            model_arguments_unchanged=True,worker_tool_executed=False,delivery_approval=False)
    except Exception:return original,None


def response_shape(body,data,media_type):
    """Diagnostic only: never accept a decision or export model-supplied text."""
    result=dict(version=1,parsed=False,terminal=False,submissions=0,
                content_shape='empty',content_chars=0,legacy_function_call=False,
                expected_tool=False,arguments_json_valid=None,arguments_schema_valid=None)
    try:
        contents=[];calls={};finished=False;done=False
        if media_type.startswith('text/event-stream'):
            for line in data.decode().splitlines():
                if not line.startswith('data:'):continue
                raw=line[5:].strip()
                if raw=='[DONE]':done=True;continue
                frame=json.loads(raw,object_pairs_hook=_unique)
                if frame.get('error') or done:raise ValueError()
                choices=frame.get('choices',[])
                if not choices:continue
                if len(choices)!=1:raise ValueError()
                entry=choices[0];delta=entry.get('delta',{})
                contents.append(delta.get('content'))
                result['legacy_function_call']|=bool(delta.get('function_call'))
                for call in delta.get('tool_calls',[]):
                    key=call.get('index',0);fn=call.get('function',{})
                    pair=calls.setdefault(key,['',''])
                    pair[0]+=fn.get('name') or '';pair[1]+=fn.get('arguments') or ''
                if entry.get('finish_reason') is not None:
                    finished=entry['finish_reason']=='tool_calls'
            result['terminal']=finished and done
        else:
            frame=json.loads(data,object_pairs_hook=_unique)
            if frame.get('error') or len(frame.get('choices',[]))!=1:raise ValueError()
            entry=frame['choices'][0];message=entry['message']
            result['terminal']=entry.get('finish_reason')=='tool_calls'
            contents.append(message.get('content'))
            result['legacy_function_call']=bool(message.get('function_call'))
            for index,call in enumerate(message.get('tool_calls',[])):
                fn=call.get('function',{});calls[index]=[fn.get('name'),fn.get('arguments')]
        result['parsed']=True;result['submissions']=len(calls)
        if any(c is not None and not isinstance(c,str) for c in contents):
            result['content_shape']='invalid_type'
        else:
            text=''.join(c or '' for c in contents);result['content_chars']=len(text)
            result['content_shape']='nonempty' if text.strip() else ('whitespace_only' if text else 'empty')
        if len(calls)==1:
            name,arguments=next(iter(calls.values()))
            result['expected_tool']=name==body['tool_choice']['function']['name']
            result['arguments_json_valid']=False
            if isinstance(arguments,str) and 1<=len(arguments)<=5000:
                try:
                    decision=json.loads(arguments,object_pairs_hook=_unique,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    result['arguments_json_valid']=True
                    result['arguments_schema_valid']=Draft202012Validator(
                        body['tools'][0]['function']['parameters']).is_valid(decision)
                except Exception:pass
        return result
    except Exception:return result


def translate(body,data,media_type):
    if not selected(body):return data,media_type,None
    phase='envelope'
    def reject(category):
        raise StructuredResponseRejected('typed_'+category)
    try:
        schema=body['tools'][0]['function']['parameters']
        if media_type.startswith('text/event-stream'):
            name='';arguments='';finished=False;done=False
            for line in data.decode().splitlines():
                if not line.startswith('data:'):continue
                raw=line[5:].strip()
                if raw=='[DONE]':
                    if done or not finished:reject('stream_incomplete')
                    done=True;continue
                if done:reject('data_after_terminal')
                frame=json.loads(raw,object_pairs_hook=_unique)
                if frame.get('error'):reject('provider_error')
                choices=frame.get('choices',[])
                if not choices:continue
                if len(choices)!=1 or choices[0].get('index',0)!=0:reject('multiple_choices')
                entry=choices[0];delta=entry.get('delta',{})
                if delta.get('content') or delta.get('function_call'):reject('mixed_content')
                calls=delta.get('tool_calls',[])
                if calls:
                    if finished or len(calls)!=1 or calls[0].get('index',0)!=0:reject('multiple_submissions')
                    call=calls[0]
                    if call.get('type','function')!='function':reject('unexpected_tool_type')
                    fn=call.get('function',{})
                    name+=fn.get('name') or '';arguments+=fn.get('arguments') or ''
                if entry.get('finish_reason') is not None:
                    if entry['finish_reason']!='tool_calls':reject('nonterminal')
                    # OpenRouter may repeat an empty terminal marker before
                    # DONE. Accept only that idempotent transport acknowledgement;
                    # never accept more arguments/content or a different finish.
                    if finished and (set(delta)-{'content','tool_calls','function_call','role'} or
                            delta.get('role') not in (None,'assistant') or
                            any(value not in (None,'',[]) for key,value in delta.items() if key!='role')):
                        reject('terminal_payload_repeated')
                    finished=True
            if not finished or not done:reject('stream_incomplete')
        else:
            envelope=json.loads(data,object_pairs_hook=_unique);choices=envelope.get('choices',[])
            if envelope.get('error'):reject('provider_error')
            if len(choices)!=1:reject('multiple_choices')
            if choices[0].get('finish_reason')!='tool_calls':reject('nonterminal')
            message=choices[0]['message'];calls=message.get('tool_calls',[])
            if message.get('content') or message.get('function_call'):reject('mixed_content')
            if len(calls)!=1:reject('multiple_submissions')
            call=calls[0]
            if call.get('type','function')!='function':reject('unexpected_tool_type')
            name=call['function']['name'];arguments=call['function']['arguments']
        if name!=body['tool_choice']['function']['name']:reject('wrong_tool_name')
        if not isinstance(arguments,str) or not 1<=len(arguments)<=5000:reject('argument_type_or_size')
        phase='arguments'
        decision=json.loads(arguments,object_pairs_hook=_unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        violations=list(Draft202012Validator(schema).iter_errors(decision))
        if violations:
            if (length_feedback_enabled(body) and len(violations)==1
                    and violations[0].validator=='maxLength' and list(violations[0].path)==['reason']
                    and schema['properties']['reason'].get('maxLength')==1200
                    and 1200<len(decision['reason'])<=4000
                    and set(decision)=={'action','reason','optional_files'}):
                error=StructuredResponseRejected('typed_schema_maxLength')
                identity='format_'+hashlib.sha256(data).hexdigest()[:24]
                error.length_feedback=[{'role':'assistant','content':None,'tool_calls':[{
                    'id':identity,'type':'function','function':{'name':name,'arguments':arguments}}]},
                    {'role':'tool','tool_call_id':identity,'content':json.dumps({
                        'validation_response':'rejected_schema','field':'reason','maxLength':1200,
                        'actualLength':len(decision['reason']),'worker_tool_executed':False,
                        'instruction':'Submit NEW valid arguments once. Condense reason to one actionable sentence, target420characters. No background or policy narration. Preserve factual classification and required fields. Nothing was executed or approved.'})}]
                raise error
            # Validator messages/values can contain secrets. Export only a
            # fixed keyword, never instance values, paths or exception text.
            allowed={'type','required','additionalProperties','enum','minLength','maxLength','maxItems'}
            keyword=next(iter(violations)).validator
            reject('schema_'+(keyword if keyword in allowed else 'violation'))
        phase='adapter'
        text=json.dumps(decision,sort_keys=True,separators=(',',':'),allow_nan=False)
        common={'id':'chatcmpl-typed-'+hashlib.sha256(data).hexdigest()[:24],
                'model':body.get('model',''),'created':0}
        # This is an explicit typed-protocol adapter, never a tool result or an
        # agent execution receipt. Model-supplied values are preserved exactly.
        if media_type.startswith('text/event-stream'):
            frames=[{'choices':[{'index':0,'delta':{'role':'assistant','content':text},'finish_reason':None}]},
                    {'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}]
            output=(''.join('data: '+json.dumps({**common,'object':'chat.completion.chunk',**f})+'\n\n' for f in frames)+'data: [DONE]\n\n').encode()
        else:output=json.dumps({**common,'object':'chat.completion','choices':[{'index':0,'message':{'role':'assistant','content':text},'finish_reason':'stop'}]}).encode()
        receipt=dict(operation='validated_typed_decision_adapter_v1',
            schema_sha256=hashlib.sha256(json.dumps(schema,sort_keys=True).encode()).hexdigest(),
            upstream_sha256=hashlib.sha256(data).hexdigest(),arguments_sha256=hashlib.sha256(arguments.encode()).hexdigest(),
            output_sha256=hashlib.sha256(output).hexdigest(),model_values_preserved=True,
            worker_tool_executed=False,delivery_approval=False)
        if name==REVIEW_NAME:
            receipt.update(mode='test_review',manifest_sha256=decision['manifest_sha256'],
                           review_acceptance_by_proxy=False)
        if name==EVIDENCE_NAME:
            receipt.update(mode='deployment_evidence',evidence_sha256=decision['evidence_sha256'],
                release_homologated=False,independent_agent_qa_approval=False)
        if name==VALIDATION_NAME:
            receipt.update(mode='deployment_validation_request',evidence_sha256=decision['evidence_sha256'],
                validation_executed=False,release_homologated=False)
        if name==RECOVERY_NAME:
            digests={v for m in body['messages'] if m.get('role')=='user' and isinstance(m.get('content'),str)
                for v in re.findall(r'^'+RECOVERY_MARKER+r':([a-f0-9]{64})$',m['content'],re.M)}
            if len(digests)!=1:reject('recovery_binding')
            receipt.update(mode='worker_recovery_request',recovery_evidence_sha256=next(iter(digests)),
                           author_retry_authorized=False,validation_executed=False)
        return output,media_type,receipt
    except Exception as error:
        if not isinstance(error,StructuredResponseRejected):
            error=StructuredResponseRejected('typed_'+phase+'_invalid')
        error.receipt=dict(operation='rejected_typed_decision_adapter_v1',
            category=error.category,upstream_sha256=hashlib.sha256(data).hexdigest(),
            delivery_approval=False,worker_tool_executed=False,
            response_shape=response_shape(body,data,media_type))
        raise error from None


def record(counter_path,execution_id,receipt):
    from deterministic_read_dispatch import ledger
    if not isinstance(execution_id,str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',execution_id):
        raise ValueError('correlated typed execution required')
    table=('typed_decision_rejections' if receipt.get('operation')=='rejected_typed_decision_adapter_v1'
           else 'typed_decisions')
    with ledger(counter_path) as con:
        con.execute('CREATE TABLE IF NOT EXISTS '+table+'('
            'execution_id TEXT,upstream_sha256 TEXT,receipt TEXT,PRIMARY KEY(execution_id,upstream_sha256))')
        encoded=json.dumps(receipt,sort_keys=True)
        key=(execution_id,receipt['upstream_sha256'])
        prior=con.execute('SELECT receipt FROM '+table+' WHERE execution_id=? AND upstream_sha256=?',key).fetchone()
        if prior:
            if prior[0]!=encoded:raise ValueError('typed decision receipt drift')
        else:con.execute('INSERT INTO '+table+' VALUES(?,?,?)',(*key,encoded))
