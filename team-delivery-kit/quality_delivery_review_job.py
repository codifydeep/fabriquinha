"""Fixed full-suite reexecution for delivery review, never a review decision.

Inputs must come from a controller-authenticated reviewer admission. This job
checks facts and runs tests; it cannot authenticate native tasks, prove Docker
mount/network policy, create a job receipt, accept a verdict or authorize merge.
Those boundaries remain the responsibility of the controller adapter.
"""
import json
import os
import signal
import sys
import uuid
import quality_red_observation as observer

quality=observer.quality


def require(value):
    if not value:raise ValueError('exact independent delivery-review full-suite job required')


def request(raw):
    require(isinstance(raw,str) and len(raw.encode())<=65536)
    value=json.loads(raw)
    require(isinstance(value,dict) and set(value)=={'operation','plan','evidence','task_id','request_id',
        'reviewer','base_manifest_sha256','snapshot_manifest_sha256'}
        and value['operation']=='validate_delivery_review_v2')
    quality.qualify_sensitivity(value['plan'],value['evidence'])
    for key in ('task_id','request_id'):
        require(isinstance(value[key],str) and len(value[key])==36 and str(uuid.UUID(value[key]))==value[key])
    require(value['reviewer']==value['plan']['reviewer'] and value['reviewer']!=value['plan']['author']
        and value['task_id'] not in {value['evidence'][k]['task_id'] for k in ('red','test_review','green')}
        and value['snapshot_manifest_sha256']==value['evidence']['green']['manifest_sha256'])
    quality.sha(value['base_manifest_sha256'])
    return value


def run(base,snapshot,value):
    value=request(json.dumps(value));plan=value['plan'];evidence=value['evidence'];passing=evidence['green']
    # A fresh execution under the review task, not a copied implementer Green.
    report=observer.run(base,snapshot,plan,value['task_id'],value['base_manifest_sha256'],
        value['snapshot_manifest_sha256'],green_context=dict(red=evidence['red'],review=evidence['test_review'],
            commit_sha=passing['commit_sha']))
    require(isinstance(report,dict) and set(report)=={'operation','green','base_manifest_sha256',
        'captured_output_sha256','captured_output_bytes','snapshot_unchanged','commit_binding_verified',
        'execution_authorized','delivery_approval'} and report['operation']=='full_suite_green_observation_v2'
        and report['base_manifest_sha256']==value['base_manifest_sha256'] and report['snapshot_unchanged'] is True
        and report['commit_binding_verified'] is False and report['execution_authorized'] is False
        and report['delivery_approval'] is False and type(report['captured_output_bytes']) is int
        and 0<=report['captured_output_bytes']<=1048576)
    quality.sha(report['captured_output_sha256']);fresh=report['green']
    quality.green(plan,evidence['red'],evidence['test_review'],fresh)
    require(fresh['task_id']==value['task_id'] and fresh['manifest_sha256']==passing['manifest_sha256']
        and fresh['commit_sha']==passing['commit_sha'] and fresh['tests_run']==passing['tests_run'])
    quality.suite(plan,fresh,passing=True,minimum=passing['tests_run'],frozen=passing['tests'],
        node_manifest=passing['manifest_sha256'],frozen_node=passing.get('node_baseline'))
    return dict(operation='full_suite_delivery_review_observation_v2',run_id=plan['run_id'],issue_id=plan['issue_id'],
        contract_sha256=plan['contract_sha256'],plan_sha256=quality.digest(plan),
        task_id=value['task_id'],request_id=value['request_id'],reviewer=value['reviewer'],
        quality_evidence_sha256=quality.digest(evidence),base_manifest_sha256=value['base_manifest_sha256'],
        manifest_sha256=passing['manifest_sha256'],commit_sha=passing['commit_sha'],
        suite={k:fresh[k] for k in quality.suite_fields(plan)},snapshot_unchanged=True,
        captured_output_sha256=report['captured_output_sha256'],captured_output_bytes=report['captured_output_bytes'],
        native_identity_verified=False,job_receipt_verified=False,
        tests_approved=False,merge_authorized=False,delivery_approval=False)


if __name__=='__main__':
    try:
        require(len(sys.argv)==1);signal.alarm(180)
        result=run('/base','/snapshot',request(os.environ['QUALITY_DELIVERY_REVIEW_JOB_JSON']))
        print(json.dumps(result,sort_keys=True),flush=True)
    except Exception as error:
        print(json.dumps(dict(operation='rejected_delivery_review_job_v2',
            category=getattr(error,'category',type(error).__name__),
            tests_approved=False,merge_authorized=False,delivery_approval=False)),flush=True)
        sys.exit(2)
