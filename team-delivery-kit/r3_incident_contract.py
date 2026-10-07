"""Bounded technical incident submissions; never execution authorization."""
import re

NAME = 'submit_r3_incident_request'


def schema(kind, sha, facts, proposal=None):
    if (kind not in ('diagnose', 'review') or not re.fullmatch(r'[a-f0-9]{64}', sha)
            or not 1 <= len(facts) <= 10 or len(set(facts)) != len(facts)
            or any(not re.fullmatch(r'F[0-9]{2}', fact) for fact in facts)
            or (kind == 'review' and not re.fullmatch(r'[a-f0-9]{64}', proposal or ''))
            or (kind == 'diagnose' and proposal is not None)):
        raise ValueError('bounded exact R3 incident bindings required')
    props = dict(evidence_sha256=dict(type='string', enum=[sha]),
        reason=dict(type='string', minLength=1, maxLength=600),
        fact_ids=dict(type='array', minItems=len(facts), maxItems=len(facts),
                      uniqueItems=True, items=dict(type='string', enum=sorted(facts))),
        execution_authorized=dict(type='boolean', enum=[False]),
        release_homologated=dict(type='boolean', enum=[False]))
    if kind == 'diagnose':
        props.update(action=dict(type='string', enum=['request_experiment', 'propose_resume',
            'escalate_cto', 'retain_hold', 'request_credentials']),
            experiment=dict(type='string', enum=['observe_existing_controller',
                'verify_frozen_delivery', 'verify_github_ci', 'verify_local_deployment', 'none']))
    else:
        props.update(decision=dict(type='string', enum=['approve_experiment', 'approve_resume',
            'request_changes', 'retain_hold']), proposal_sha256=dict(type='string', enum=[proposal]))
    return dict(type='object', properties=props, required=list(props), additionalProperties=False)


def request_contract(body):
    notes = []
    for message in body.get('messages', []):
        if message.get('role') != 'user':
            continue
        content = message.get('content', '')
        if isinstance(content, list):
            content = '\n'.join(p.get('text', '') for p in content
                                if isinstance(p, dict) and p.get('type') == 'text')
        if isinstance(content, str):
            notes.append(content)
    lines = '\n'.join(notes).splitlines()
    markers = [line for line in lines if line.startswith('DELIVERY_R3_INCIDENT_V1:')]
    if not markers:
        return None
    if len(markers) != 1:
        raise ValueError('one R3 incident contract required')
    match = re.fullmatch(r'DELIVERY_R3_INCIDENT_V1:(diagnose|review):([a-f0-9]{64})', markers[0])
    allowed = ('DELIVERY_R3_INCIDENT_V1:', 'DELIVERY_R3_FACT:', 'DELIVERY_R3_PROPOSAL_V1:')
    if not match or any(line.startswith('DELIVERY_') and not line.startswith(allowed) for line in lines):
        raise ValueError('isolated R3 incident contract required')
    facts = [line[len('DELIVERY_R3_FACT:'):] for line in lines if line.startswith('DELIVERY_R3_FACT:')]
    proposals = [line[len('DELIVERY_R3_PROPOSAL_V1:'):] for line in lines
                 if line.startswith('DELIVERY_R3_PROPOSAL_V1:')]
    if len(proposals) != (1 if match[1] == 'review' else 0):
        raise ValueError('exact R3 proposal binding required')
    return schema(match[1], match[2], facts, proposals[0] if proposals else None)
