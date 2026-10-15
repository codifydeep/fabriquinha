"""Technical experiment planning is not execution, calibration or delivery approval."""
import json
import re
from structured_response_contract import _unique

MARKER='DELIVERY_CALIBRATION_EXPERIMENT_V1'


def require(ok):
    if not ok:raise ValueError('exact source-bound experiment contract required')


def context(phase,source_sha256,hold_sha256,proposal_sha256):
    require(phase in ('design','review'))
    value=dict(phase=phase,source_sha256=source_sha256,hold_sha256=hold_sha256,proposal_sha256=proposal_sha256)
    require(all(isinstance(value[k],str) and re.fullmatch('[a-f0-9]{64}',value[k]) for k in value if k!='phase'))
    return value


def capsule(value):return MARKER+':'+json.dumps(value,sort_keys=True,separators=(',',':'))+'\n'


def request(body):
    lines=[line[len(MARKER)+1:] for m in body.get('messages',[]) if m.get('role')=='user'
        and isinstance(m.get('content'),str) for line in m['content'].splitlines() if line.startswith(MARKER+':')]
    if not lines:return None
    require(len(lines)==1);value=json.loads(lines[0],object_pairs_hook=_unique)
    require(set(value)=={'phase','source_sha256','hold_sha256','proposal_sha256'})
    return context(**value)


def schema(value):
    props={k:dict(type='string',enum=[v]) for k,v in value.items()}
    design=value['phase']=='design'
    props.update(action=dict(type='string',enum=['propose_fixture_experiment','needs_engineering_capability'] if design else ['permit_fixture_draft','retain_technical_hold']),
        reason=dict(type='string',minLength=1,maxLength=400),
        **{k:dict(type='boolean',enum=[False]) for k in ('author_retry_authorized','execution_authorized','delivery_approval')})
    if design:
        props.update(hypothesis=dict(type='string',minLength=1,maxLength=200),
            method=dict(type='string',minLength=1,maxLength=220),
            expected_evidence=dict(type='string',minLength=1,maxLength=300))
    return dict(type='object',properties=props,required=list(props),additionalProperties=False)


def apply(body):
    value=request(body)
    if value is None:return None
    from calibration_objection_contract import request as objection
    from calibration_response_contract import request as submission
    from calibration_incident_contract import request as incident
    require(objection(body) is None and submission(body) is None and incident(body) is None)
    body.update(tools=[],tool_choice='none',response_format=dict(type='json_schema',json_schema=dict(
        name='calibration_experiment_'+value['phase']+'_v1',strict=True,schema=schema(value))))
    body['provider']={**body.get('provider',{}),'require_parameters':True};return body
