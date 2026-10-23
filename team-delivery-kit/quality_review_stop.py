"""Advisory pre-stop feedback inside ONE Hermes turn; no gate or capability.

The controller must still attest native identity, byte-bound ACP reads, exact
verdict and closed lease independently. This worker cannot approve tests.
"""
import hashlib
import json
import os
import re
from artifact_read_evidence import coverage
from quality_review_verdict import parse,required_reads
try:import quality_review_reads as reads
except ImportError:from broker import quality_review_reads as reads

ITERATION_LIMIT=40
MAX_FEEDBACK=ITERATION_LIMIT  # No smaller handoff cap; real progress may continue within the original budget.


def require(value):
    if not value:raise ValueError('exact advisory review-stop context required')


def validate_context(context,paths):
    require(isinstance(context,dict) and set(context)=={'packet','files'})
    packet=context['packet']
    require(isinstance(packet,dict) and set(packet)=={'manifest_sha256','plan_sha256','red_sha256','plan'}
        and all(re.fullmatch('[a-f0-9]{64}',str(packet[k])) for k in ('manifest_sha256','plan_sha256','red_sha256'))
        and isinstance(packet['plan'],dict) and set(packet['plan'])=={'criteria','new_tests'})
    criteria=packet['plan']['criteria'];new=packet['plan']['new_tests']
    require(isinstance(criteria,list) and 1<=len(criteria)<=64
        and all(isinstance(c,str) and 1<=len(c)<=100 for c in criteria) and len(criteria)==len(set(criteria))
        and isinstance(new,list) and bool(new) and all(isinstance(p,str) and '/delivery/'+p in paths for p in new)
        and len(new)==len(set(new)))
    reads.inventory(context['files'],packet['manifest_sha256'],paths)
    return context


def enabled(environment=None):
    environment=os.environ if environment is None else environment
    from quality_phase_tools import validate,KEY
    if KEY not in environment:return False
    config=validate(json.loads(environment[KEY]),environment.get('DELIVERY_MODEL_EXECUTION_ID'))
    return config['phase']=='test_review_v2' and 'review_context' in config and environment.get('DELIVERY_EXECUTION_MODE')=='review'


def iteration_limit(environment=None):
    """Explicit v2 ACP budget; legacy factories remain unchanged."""
    environment=os.environ if environment is None else environment
    from quality_phase_tools import validate,KEY
    if KEY not in environment:return None
    validate(json.loads(environment[KEY]),environment.get('DELIVERY_MODEL_EXECUTION_ID'))
    return ITERATION_LIMIT


def pairs(messages):
    """Use actual OpenAI tool-result history, never prose claiming a read."""
    require(isinstance(messages,list))
    calls={};result=[];done=set()
    for message in messages:
        if not isinstance(message,dict):continue
        if message.get('role')=='assistant':
            for call in message.get('tool_calls') or []:
                function=call.get('function') or {}
                if function.get('name')!='read_file':continue
                key=call.get('id');require(isinstance(key,str) and key not in calls)
                args=function.get('arguments')
                args=json.loads(args) if isinstance(args,str) else args
                require(isinstance(args,dict));calls[key]=args
        elif message.get('role')=='tool' and message.get('tool_call_id') in calls:
            key=message['tool_call_id'];require(key not in done);done.add(key)
            output=message.get('content')
            if not isinstance(output,str):continue
            pair=[dict(type='tool_use',tool='read_file',call_id=key,input=calls[key]),
                dict(type='tool_result',tool='read_file',call_id=key,output=output)]
            # Denied or clipped reads cannot prevent the next real page. The
            # controller independently retains and checks its actual ACP stream.
            if reads.accept_page(pair):result.extend(pair)
    return result


def inspect(config,messages,output):
    context=validate_context(config['review_context'],config['read_paths'])
    packet=context['packet'];required=config['read_paths'];valid=True
    try:required=required_reads(parse(output,packet),packet,required)
    except (ValueError,KeyError,TypeError,UnicodeError):valid=False
    observed=pairs(messages)
    assessment=reads.assessment(context['files'],packet['manifest_sha256'],config['read_paths'],observed,required_paths=required)
    normalized=[]
    for i in range(0,len(observed),2):normalized.extend(reads.page(observed[i:i+2])[2])
    pages=coverage(normalized,include_content=True)
    next_reads=[]
    for rejected in assessment['rejected_files'][:16]:
        path='/delivery/'+rejected['path'];page=pages.get(path,{})
        lines=page.get('line_content',{});total=page.get('total_lines',0)
        offset=next((n for n in range(1,total+1) if n not in lines),1)
        next_reads.append(dict(path=path,offset=offset,limit=100))
    result=dict(operation='advisory_review_completion_v1',verdict_format='valid' if valid else 'invalid',
        manifest_sha256=packet['manifest_sha256'],required_files=assessment['required_files'],
        complete_files=assessment['complete_files'],remaining_files=len(assessment['rejected_files']),
        next_reads=next_reads,tests_approved=False,execution_authorized=False,delivery_approval=False)
    # A changed prose answer is not new evidence; only verified reads/format can
    # change this fingerprint. Bound to the same snapshot and execution below.
    fingerprint=dict(verdict_format=result['verdict_format'],reads=assessment)
    result['progress_sha256']=hashlib.sha256(json.dumps(fingerprint,sort_keys=True).encode()).hexdigest()
    return result


def guard(agent,messages,output,remaining,environment=None):
    environment=os.environ if environment is None else environment
    if not enabled(environment):return None
    require(type(remaining) is int and 0<=remaining<=ITERATION_LIMIT)
    config=json.loads(environment['DELIVERY_QUALITY_PHASE_JSON'])
    result=inspect(config,messages,output)
    if result['verdict_format']=='valid' and not result['remaining_files']:return None
    identity=(config['request_id'],result['manifest_sha256'])
    old=getattr(agent,'_quality_review_completion',None)
    require(old is None or old['identity']==identity)
    attempts=1+(old['attempts'] if old else 0)
    repeated=1+(old['repeated'] if old and old['progress_sha256']==result['progress_sha256'] else 0)
    state=dict(identity=identity,attempts=attempts,repeated=repeated,progress_sha256=result['progress_sha256'])
    agent._quality_review_completion=state
    result.update(attempt=attempts,repeated_without_progress=repeated,
        remaining_iterations=remaining,
        blocked=repeated>=2 or attempts>MAX_FEEDBACK or remaining<=0)
    result['next_action']=('CTO diagnose preserved review; no identical retry or approval' if result['blocked'] else
        'Continue in this SAME turn. Batch the next read_file calls; then page each file to its end. '
        'Do not reread unchanged complete files. All required files are mandatory for approval. '
        'Return ONLY the exact JSON verdict, without prose or Markdown; no claimed execution or approval booleans.')
    return result
