"""Trusted Docker canary: real executors, synthetic source/review/commit identities.

Never install as a native job entrypoint. Approval is deliberately absent.
"""
import hashlib
import json
import os
from pathlib import Path
import quality_lifecycle_v2 as quality
import quality_red_observation as observer
import quality_green_job as green_job
import quality_reversion_job as reversion

raw=os.environ['QUALITY_MIXED_CANARY_JSON'];quality.require(len(raw.encode())<=65536)
p=json.loads(raw)
quality.require(set(p)=={'plan','task_id','green_task_id','base_manifest','red_manifest','green_manifest','sources'})
expected={'quality_red_observation.py','quality_green_job.py','quality_reversion_job.py',
    'quality_node_baseline.py','quality_node_reporter.mjs','quality_node_evidence.py','quality_lifecycle_v2.py'}
quality.require(set(p['sources'])==expected)
for name,sha in p['sources'].items():quality.require(hashlib.sha256((Path('/opt/quality')/name).read_bytes()).hexdigest()==sha)
plan=p['plan']
red=observer.run('/base','/reviewed',plan,p['task_id'],p['base_manifest'],p['red_manifest'])['red']
review=dict(operation='independent_test_review_v2',run_id=plan['run_id'],issue_id=plan['issue_id'],
    contract_sha256=plan['contract_sha256'],plan_sha256=quality.digest(plan),
    task_id='30000000-0000-4000-8000-000000000002',author=plan['author'],reviewer=plan['reviewer'],
    manifest_sha256=p['red_manifest'],red_sha256=quality.digest(red),decision='approve_tests',
    criteria=plan['criteria'],complete_reads=True,read_only=True)
green=green_job.run(dict(operation='observe_green_v2',plan=plan,task_id=p['green_task_id'],
    base_manifest_sha256=p['base_manifest'],snapshot_manifest_sha256=p['green_manifest'],
    green_context=dict(red=red,review=review,commit_sha='e'*40)))['green']
evidence=dict(red=red,test_review=review,green=green)
control=reversion.run('/base','/snapshot','/reviewed',plan,p['green_task_id'],p['base_manifest'],
    p['green_manifest'],p['red_manifest'],evidence)
quality.qualify_sensitivity(plan,{**evidence,'sensitivity':control['sensitivity']})
node=[red['node_baseline'],green['node_baseline'],control['sensitivity']['controls'][0]['node_baseline']]
quality.require(all(n['inventory']==node[0]['inventory'] for n in node))
print(json.dumps(dict(operation='mixed_executor_docker_canary_v1',status='passed',
    red_python_tests=red['tests_run'],green_python_tests=green['tests_run'],node_tests=[n['tests_run'] for n in node],
    node_version=node[0]['node_version'],node_inventory_frozen=True,post_green_node_reexecuted=True,
    green_fixed_job_dispatched=True,review='synthetic_fixture',commit='synthetic_fixture',
    source_hashes_verified=True,native_qualification=False,model_calls=0,delivery_approval=False),sort_keys=True))
