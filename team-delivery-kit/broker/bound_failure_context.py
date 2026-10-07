"""Lossless controller-owned failure references; markers never confer authority."""
import hashlib
import json
import re


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def project(summary,source,failure):
    marker='DELIVERY_BOUND_FAILURE_CONTEXT_V1:'+source+':'+digest(failure)
    return {**summary,'validation_failure':dict(reference=marker,
        failure_count=len(failure.get('failures',[])),output_sha256=failure.get('output_sha256'),
        category=failure['category'],full_evidence_preserved=True)},marker


def expand(note,issue,task,lookup):
    markers=re.findall(r'DELIVERY_BOUND_FAILURE_CONTEXT_V1:([A-Za-z0-9-]+):([a-f0-9]{64})',note)
    if not markers:return note
    # One reference in JSON plus one explicit line is unnecessary; callers put
    # only the JSON reference in the instruction. Duplicate markers are invalid.
    if len(markers)!=1:raise ValueError('single bound failure reference required')
    source,sha=markers[0];row=lookup(source)
    if not row or row['issue_id']!=issue:raise ValueError('failure source missing')
    data=json.loads(row['data']);failure=data.get('validation_failure')
    if (not failure or digest(failure)!=sha or not data.get('artifact_diagnosis')
            or task.get('agent_id')!=data.get('target')
            or not data.get('wakeup_id') or task.get('wakeup_id')!=data['wakeup_id']):
        raise ValueError('actual diagnostic wakeup and exact failure required')
    full='\nCONTROLLER VERIFIED FULL FROZEN-SUITE FAILURE DATA: '+json.dumps(failure,sort_keys=True,separators=(',',':'))
    if len(note+full)>16000:raise ValueError('bound failure context exceeds qualified note limit')
    return note+full


def verified_red(effects,task):
    return effects.test_first_red(task) if hasattr(effects,'test_first_red') else None
