"""Pure final-review facts, not provenance, native admission or a merge grant.

The future controller adapter must authenticate every native identity, complete
read, readonly snapshot and execution-scoped fixed-job receipt independently.
Workers cannot use this function or its output as authority. Existing v2 and
legacy flows are unchanged; this module is not installed or dispatched yet.
"""
import uuid
try:import quality_lifecycle_v2 as quality
except ImportError:from broker import quality_lifecycle_v2 as quality


def require(value):
    if not value:raise ValueError('exact independent same-SHA delivery review facts required')


def qualify(plan,evidence,decision,validation):
    qualified=quality.qualify_sensitivity(plan,evidence)
    green=evidence['green']
    quality.envelope(plan,decision,'independent_delivery_review_v2',
        {'task_id','author','reviewer','manifest_sha256','commit_sha','red_sha256',
         'test_review_sha256','green_sha256','sensitivity_sha256','validation_sha256',
         'decision','criteria','complete_reads','read_only'})
    require(isinstance(decision['task_id'],str) and 1<=len(decision['task_id'])<=80
        and decision['task_id'] not in {evidence[k]['task_id'] for k in ('red','test_review','green')}
        and decision['author']==plan['author'] and decision['reviewer']==plan['reviewer']
        and decision['author']!=decision['reviewer'] and decision['read_only'] is True
        and decision['complete_reads'] is True and decision['decision']=='approve_delivery'
        and decision['manifest_sha256']==qualified['manifest_sha256']
        and decision['commit_sha']==qualified['commit_sha'])
    quality.names(decision['criteria']);require(set(decision['criteria'])==set(plan['criteria']))
    for key in ('red','test_review','green','sensitivity'):
        require(decision[key+'_sha256']==quality.digest(evidence[key]))
    quality.envelope(plan,validation,'observed_delivery_review_validation_v2',
        quality.suite_fields(plan)|{'task_id','request_id','reviewer','quality_evidence_sha256',
            'manifest_sha256','commit_sha','job_receipt_sha256','network','snapshot_mount'})
    require(validation['task_id']==decision['task_id'] and validation['reviewer']==plan['reviewer']
        and validation['quality_evidence_sha256']==quality.digest(evidence)
        and validation['manifest_sha256']==green['manifest_sha256']
        and validation['commit_sha']==green['commit_sha']
        and validation['network']=='none' and validation['snapshot_mount']=='readonly'
        and isinstance(validation['request_id'],str) and len(validation['request_id'])==36)
    try:request=str(uuid.UUID(validation['request_id']))
    except (ValueError,TypeError,AttributeError):raise ValueError('canonical validation request required') from None
    require(request==validation['request_id'])
    quality.sha(validation['job_receipt_sha256'])
    quality.suite(plan,validation,passing=True,minimum=green['tests_run'],frozen=green['tests'],
        node_manifest=green['manifest_sha256'],frozen_node=green.get('node_baseline'))
    require(validation['tests_run']==green['tests_run']
        and decision['validation_sha256']==quality.digest(validation))
    return dict(operation='quality_delivery_review_policy_facts_v2',plan_sha256=quality.digest(plan),
        quality_evidence_sha256=quality.digest(evidence),review_sha256=quality.digest(decision),
        validation_sha256=quality.digest(validation),manifest_sha256=green['manifest_sha256'],
        commit_sha=green['commit_sha'],merge_authorized=False,delivery_approval=False)
