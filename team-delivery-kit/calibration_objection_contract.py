"""Independent evidence referral, never a calibration or delivery approval."""
import json
import re
from structured_response_contract import _unique

MARKER='DELIVERY_CALIBRATION_OBJECTION_V1'


def require(condition):
    if not condition:raise ValueError('exact bounded calibration objection contract required')


def context(source,objection,probe):
    value=dict(source_sha256=source,objection_sha256=objection,probe_sha256=probe)
    require(all(isinstance(v,str) and re.fullmatch('[a-f0-9]{64}',v) for v in value.values()));return value


def capsule(value):return MARKER+':'+json.dumps(value,sort_keys=True,separators=(',',':'))+'\n'


def request(body):
    lines=[line[len(MARKER)+1:] for m in body.get('messages',[]) if m.get('role')=='user'
        and isinstance(m.get('content'),str) for line in m['content'].splitlines() if line.startswith(MARKER+':')]
    if not lines:return None
    require(len(lines)==1);value=json.loads(lines[0],object_pairs_hook=_unique)
    require(set(value)=={'source_sha256','objection_sha256','probe_sha256'});return context(**{k.removesuffix('_sha256'):v for k,v in value.items()})


def schema(value):
    properties={k:dict(type='string',enum=[v]) for k,v in value.items()}
    properties.update(action=dict(type='string',enum=['refer_to_cto','retain_technical_hold']),
        reason=dict(type='string',minLength=1,maxLength=900),
        author_retry_authorized=dict(type='boolean',enum=[False]),
        execution_authorized=dict(type='boolean',enum=[False]),delivery_approval=dict(type='boolean',enum=[False]))
    return dict(type='object',properties=properties,required=list(properties),additionalProperties=False)


def apply(body):
    value=request(body)
    if value is None:return None
    from calibration_response_contract import request as submission
    from calibration_incident_contract import request as incident
    require(submission(body) is None and incident(body) is None)
    body.update(tools=[],tool_choice='none',response_format=dict(type='json_schema',json_schema=dict(
        name='calibration_objection_review_v1',strict=True,schema=schema(value))))
    body['provider']={**body.get('provider',{}),'require_parameters':True};return body
