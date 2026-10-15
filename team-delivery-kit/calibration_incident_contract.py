"""Closed incident decisions; context/JSON are never execution authority."""
import hashlib
import json
import re

MARKER='DELIVERY_CALIBRATION_INCIDENT_V1'
CONTEXT='DELIVERY_CALIBRATION_INCIDENT_CONTEXT_V1'


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def context(phase,incident,source,proposal=None,probe=None):
    value=dict(phase=phase,incident_sha256=incident,source_sha256=source,proposal_sha256=proposal,probe_sha256=probe)
    validate_context(value);return value


def validate_context(v):
    if not isinstance(v,dict) or set(v)!={'phase','incident_sha256','source_sha256','proposal_sha256','probe_sha256'}:
        raise ValueError('exact incident context required')
    if v['phase'] not in ('diagnosis','evidence_diagnosis','review'):raise ValueError('fixed incident role required')
    for k in ('incident_sha256','source_sha256','proposal_sha256','probe_sha256'):
        if v['phase']=='diagnosis' and k in ('proposal_sha256','probe_sha256'):
            if v[k] is not None:raise ValueError('diagnosis cannot claim experiment evidence')
        elif not isinstance(v[k],str) or not re.fullmatch('[a-f0-9]{64}',v[k]):raise ValueError('exact incident hash required')


def capsule(v):
    validate_context(v)
    return MARKER+':'+digest(v)+'\n'+CONTEXT+':'+json.dumps(v,sort_keys=True,separators=(',',':'))+'\n'


def request(body):
    lines=[]
    for m in body.get('messages',[]):
        if m.get('role')!='user':continue
        content=m.get('content','')
        if isinstance(content,list):content='\n'.join(p.get('text','') for p in content if isinstance(p,dict) and p.get('type')=='text')
        if isinstance(content,str):lines.extend(content.splitlines())
    markers=[x[len(MARKER)+1:] for x in lines if x.startswith(MARKER+':')]
    if not markers:return None
    contexts=[x[len(CONTEXT)+1:] for x in lines if x.startswith(CONTEXT+':')]
    if len(markers)!=1 or len(contexts)!=1:raise ValueError('one current incident context required')
    from structured_response_contract import _unique
    value=json.loads(contexts[0],object_pairs_hook=_unique);validate_context(value)
    if digest(value)!=markers[0]:raise ValueError('incident context hash drift')
    from calibration_response_contract import request as calibration
    if calibration(body) is not None:raise ValueError('conflicting current incident and submission contexts')
    return value


def schema(v):
    validate_context(v)
    def fixed(value):return dict(type='string',enum=[value])
    actions=[{'diagnosis':'request_transport_probe','evidence_diagnosis':'submit_probe_for_review',
        'review':'sponsor_data_submission'}[v['phase']],'retain_technical_hold']
    props=dict(action=dict(type='string',enum=actions),incident_sha256=fixed(v['incident_sha256']),
        reason=dict(type='string',minLength=1,maxLength=900),experiment=fixed('fixed_transport_probe_v1'),
        historical_cause_proven=dict(type='boolean',enum=[False]),
        author_retry_authorized=dict(type='boolean',enum=[False]),execution_authorized=dict(type='boolean',enum=[False]),
        delivery_approval=dict(type='boolean',enum=[False]))
    if v['phase']!='diagnosis':props.update(proposal_sha256=fixed(v['proposal_sha256']),probe_sha256=fixed(v['probe_sha256']))
    return dict(type='object',properties=props,required=list(props),additionalProperties=False)


def apply(body):
    v=request(body)
    if v is None:return None
    body['tools']=[];body['tool_choice']='none'
    body['response_format']=dict(type='json_schema',json_schema=dict(name='delivery_calibration_incident_v1',strict=True,schema=schema(v)))
    body['provider']={**(body.get('provider') or {}),'require_parameters':True}
    return body
