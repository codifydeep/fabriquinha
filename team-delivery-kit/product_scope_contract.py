"""Nonexecuting product-scope submissions with mandatory dependency inspection.

Wire bindings are not authority: the controller must authenticate actor/task/read
receipts and validate the original contract before applying any amendment.
"""
import copy
import hashlib
import json
import re
import uuid
from artifact_read_evidence import observations, next_read

MARKER='DELIVERY_PRODUCT_SCOPE_V1'
CONTEXT='DELIVERY_PRODUCT_SCOPE_CONTEXT_V1'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def validate_context(context):
    keys={'issue_id','source_task','contract_sha256','snapshot_sha256','failure_output_sha256',
          'eligible_code_sha256','frozen_test_sha256'}
    if not isinstance(context,dict) or set(context)!=keys:
        raise ValueError('exact bounded scope context required')
    for key in ('issue_id','source_task'):
        if not isinstance(context[key],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',context[key]):
            raise ValueError('bounded scope identity required')
    for key in ('contract_sha256','snapshot_sha256','failure_output_sha256'):
        if not isinstance(context[key],str) or not re.fullmatch(r'[a-f0-9]{64}',context[key]):
            raise ValueError('exact scope evidence hashes required')
    for key,maximum in (('eligible_code_sha256',8),('frozen_test_sha256',32)):
        paths=context[key]
        if not isinstance(paths,dict) or not 1<=len(paths)<=maximum:
            raise ValueError('bounded observed scope inventory required')
        for path,sha in paths.items():
            if (not isinstance(path,str) or not re.fullmatch(r'[A-Za-z0-9_/-]+\.py',path)
                    or any(p in ('','..','.') for p in path.split('/'))
                    or not isinstance(sha,str) or not re.fullmatch(r'[a-f0-9]{64}',sha)):
                raise ValueError('exact safe inventory paths and hashes required')
            if key=='eligible_code_sha256' and (path.startswith(('tests/','broker/'))
                    or any(p in ('tests','test') or p.startswith('test_') for p in path.split('/'))
                    or path.rsplit('/',1)[-1] in ('conftest.py','setup.py')):
                raise ValueError('scope inventory cannot admit tests or governance')
    return context


def instruction(kind,context,proposal_sha256=None):
    validate_context(context)
    if kind not in ('proposal','review') or (kind=='review') != (proposal_sha256 is not None):
        raise ValueError('exact scope submission mode required')
    if proposal_sha256 is not None and not re.fullmatch(r'[a-f0-9]{64}',proposal_sha256):
        raise ValueError('exact scope proposal identity required')
    note=('Inspect the frozen dependencies. Submit only a scope proposal or independent review. '
          'No edits, execution authorization, test changes or delivery approval.\n'
          +MARKER+':'+kind+':'+digest(context)+'\n'
          +CONTEXT+':'+json.dumps(context,sort_keys=True,separators=(',',':')))
    if proposal_sha256 is not None:note+='\nDELIVERY_PRODUCT_SCOPE_PROPOSAL_V1:'+proposal_sha256
    return note


def request(body):
    lines=[]
    for message in body.get('messages',[]):
        if message.get('role')!='user':continue
        content=message.get('content','')
        if isinstance(content,list):
            content='\n'.join(p.get('text','') for p in content if isinstance(p,dict) and p.get('type')=='text')
        if isinstance(content,str):lines.extend(content.splitlines())
    markers=[line for line in lines if line.startswith(MARKER+':')]
    if not markers:return None
    if len(markers)!=1:raise ValueError('one isolated scope submission required')
    # Allow only the authenticated transport envelope's syntax, not another work protocol.
    envelopes=[i for i,line in enumerate(lines) if line.startswith('DELIVERY_PLANNING_START')]
    if envelopes:
        i=envelopes[0]
        if (len(envelopes)!=1 or not re.fullmatch(r'DELIVERY_PLANNING_START [a-f0-9]{64}',lines[i])
                or i+1>=len(lines) or not lines[i+1].startswith('Source: ')):
            raise ValueError('exact planning envelope required')
        source=lines[i+1].removeprefix('Source: ')
        if str(uuid.UUID(source))!=source:raise ValueError('canonical planning source required')
        lines=lines[:i]+lines[i+2:]
    allowed=(MARKER+':',CONTEXT+':','DELIVERY_PRODUCT_SCOPE_PROPOSAL_V1:')
    match=re.fullmatch(MARKER+r':(proposal|review):([a-f0-9]{64})',markers[0])
    contexts=[line.removeprefix(CONTEXT+':') for line in lines if line.startswith(CONTEXT+':')]
    proposals=[line.removeprefix('DELIVERY_PRODUCT_SCOPE_PROPOSAL_V1:') for line in lines
               if line.startswith('DELIVERY_PRODUCT_SCOPE_PROPOSAL_V1:')]
    if (not match or len(contexts)!=1
            or any(line.startswith('DELIVERY_') and not line.startswith(allowed) for line in lines)):
        raise ValueError('isolated scope context required')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate scope context key')
            result[key]=value
        return result
    context=validate_context(json.loads(contexts[0],object_pairs_hook=unique))
    if digest(context)!=match[2] or len(proposals)!=(1 if match[1]=='review' else 0):
        raise ValueError('scope context identity mismatch')
    if proposals and not re.fullmatch(r'[a-f0-9]{64}',proposals[0]):
        raise ValueError('exact reviewed scope proposal required')
    fixed=lambda value:dict(type='string',enum=[value])
    props={'reason':dict(type='string',minLength=1,maxLength=1200)}
    if match[1]=='proposal':
        props.update(operation=fixed('propose_product_scope_revision_v1'),
                     **{k:fixed(context[k]) for k in ('issue_id','source_task','contract_sha256',
                                                       'snapshot_sha256','failure_output_sha256')})
        props['write_files']=dict(type='array',minItems=1,maxItems=len(context['eligible_code_sha256']),
            uniqueItems=True,items=dict(type='string',enum=sorted(context['eligible_code_sha256'])))
    else:
        props.update(operation=fixed('review_product_scope_revision_v1'),proposal_sha256=fixed(proposals[0]),
                     decision=dict(type='string',enum=['approve','request_changes']))
    return context,dict(type='object',properties=props,required=list(props),additionalProperties=False)


def apply(body):
    parsed=request(body)
    if parsed is None:return None
    context,schema=parsed
    body=copy.deepcopy(body)
    paths={'/evidence/candidate/'+p for p in context['eligible_code_sha256']}
    missing=sorted(paths-observations(body['messages'],wire=True).keys())
    if missing:
        tools=[t for t in body.get('tools',[]) if t.get('function',{}).get('name')=='read_file']
        if len(tools)!=1:raise ValueError('one scope inspection tool required')
        offset=next_read(body['messages'],missing[0])
        tools[0]['function'].update(strict=True,parameters=dict(type='object',properties={
            'path':dict(type='string',enum=[missing[0]]),'offset':dict(type='integer',enum=[offset]),
            'limit':dict(type='integer',enum=[100])},required=['path','offset','limit'],additionalProperties=False))
        body['tools']=tools;body.pop('response_format',None)
        body['tool_choice']=dict(type='function',function=dict(name='read_file'))
    else:
        body['tools']=[];body['tool_choice']='none'
        body['response_format']=dict(type='json_schema',json_schema=dict(name='delivery_product_scope_v1',
            strict=True,schema=schema))
    body['provider']={**(body.get('provider') or {}),'require_parameters':True}
    return body
