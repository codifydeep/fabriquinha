"""A technical recovery proposal/review is not permission to execute or deliver."""
import re


def schema(kind, sha, criteria):
    string = lambda limit: dict(type='string', minLength=1, maxLength=limit)
    properties = dict(evidence_sha256=dict(type='string', enum=[sha]), reason=string(600),
                      execution_authorized=dict(type='boolean', enum=[False]),
                      release_homologated=dict(type='boolean', enum=[False]))
    if kind == 'plan':
        properties.update(action=dict(type='string', enum=['propose_remediation_plan', 'retain_hold']),
            steps=dict(type='array', minItems=0, maxItems=3, items=dict(type='object', additionalProperties=False,
                properties=dict(id=dict(type='string', enum=['R1','R2','R3']),
                    depends_on=dict(type='array', maxItems=1, items=dict(type='string', enum=['R1','R2'])),
                    edit_scope=dict(type='string', enum=['new_tests_only','product_only','controller_only']),
                    objective=string(240),
                    criteria=dict(type='array', minItems=1, maxItems=len(criteria), uniqueItems=True,
                                  items=dict(type='string', enum=criteria))),
                required=['id','depends_on','edit_scope','objective','criteria'])))
    else:
        properties.update(decision=dict(type='string', enum=['approve_plan','request_changes']),
                          plan_sha256=dict(type='string', enum=[sha]))
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


def apply_properties(body, properties, mode):
    contracts = {(kind, digest) for m in body['messages'] if m.get('role')=='user' and isinstance(m.get('content'),str)
        for kind,digest in re.findall(r'^DELIVERY_REMEDIATION_(PLAN|REVIEW)_V1:([a-f0-9]{64})$',m['content'],re.M)}
    if not contracts:
        return properties
    if mode!='technical' or len(contracts)!=1:
        raise ValueError('one technical remediation contract required')
    kind, sha = next(iter(contracts))
    ids = sorted({c for m in body['messages'] if m.get('role')=='user' and isinstance(m.get('content'),str)
        for c in re.findall(r'^DELIVERY_REMEDIATION_CRITERION:(A[0-9]{2})$',m['content'],re.M)})
    if kind=='PLAN' and not 1<=len(ids)<=32:
        raise ValueError('complete criterion identities required')
    body['messages'].append(dict(role='system',content='This is a non-executing recovery plan or its independent review. '
        'No delivery approval, frozen-file edits, test waivers, new revision depth or executed-action claims. '
        'Preserve every criterion in every step. R1=new_tests_only, R2=product_only, R3=controller_only; '
        'dependencies [] then [R1] then [R2]. A retained hold has no steps.'))
    return schema(kind.lower(), sha, ids)['properties']
