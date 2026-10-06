"""Pinned non-executing work proposal for an existing-behavior lifecycle hold."""
import re
MARKER = 'DELIVERY_WORK_PROPOSAL_V1'


def schema(sha):
    props = dict(evidence_sha256={'type':'string','enum':[sha]},
        kind={'type':'string','enum':['lifecycle_reconciliation','retain_hold']},
        title={'type':'string','minLength':1,'maxLength':160},
        reason={'type':'string','minLength':1,'maxLength':800},
        criteria={'type':'array','minItems':3,'maxItems':3,'uniqueItems':True,
                  'items':{'type':'string','enum':['C08','C09','C10']}},
        historical_disposition={'type':'string','enum':['preserve_blocked_history']},
        dependency_policy={'type':'string','enum':['do_not_release_dependents']},
        product_edit_paths={'type':'array','maxItems':0,'items':{'type':'string'}},
        **{k:{'type':'boolean','enum':[False]} for k in
           ('historical_tdd_red','release_homologated','execution_authorized')})
    return dict(type='object',properties=props,required=list(props),additionalProperties=False)


def apply(body):
    values={v for m in body.get('messages',[]) if m.get('role')=='user' and isinstance(m.get('content'),str)
            for v in re.findall(r'^'+MARKER+r':([a-f0-9]{64})$',m['content'],re.M)}
    if not values:return None
    if len(values)!=1 or any(re.search(r'^DELIVERY_(?:STRUCTURED_DECISION|DEPLOYMENT_EVIDENCE|DEPLOYMENT_VALIDATION)_V1',
                            str(m.get('content','')),re.M) for m in body['messages']):
        raise ValueError('conflicting work proposal contracts')
    sha=values.pop()
    body['tools']=[];body['tool_choice']='none'
    body['response_format']={'type':'json_schema','json_schema':{'name':'delivery_work_proposal_v1',
        'strict':True,'schema':schema(sha)}}
    body['provider']={**(body.get('provider') or {}),'require_parameters':True}
    return body
