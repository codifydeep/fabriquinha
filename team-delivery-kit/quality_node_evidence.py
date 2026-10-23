"""Pure frozen Node baseline facts; authentication belongs to fixed-job receipts."""
import json
import re
from portable_contract import safe_path

FIELDS={'operation','status','inventory','manifest_sha256','tests','tests_run','counts','node_version','exit_code',
    'captured_output_sha256','captured_output_bytes','stderr_sha256','snapshot_unchanged',
    'execution_authorized','delivery_approval','native_qualification'}


def require(value):
    if not value:raise ValueError('exact frozen full Node evidence required')


def sha(value):require(isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value))


def paths(values):
    return {p for p in values if p.endswith(('.test.js','.spec.js','.test.mjs','.test.cjs'))}


def validate(value,tests,*,manifest=None,frozen=None):
    require(isinstance(value,dict) and set(value)==FIELDS
        and value['operation']=='full_node_baseline_observation_v2' and value['status']=='passed'
        and value['tests']==tests and bool(tests) and value['snapshot_unchanged'] is True
        and all(value[k] is False for k in ('execution_authorized','delivery_approval','native_qualification'))
        and type(value['exit_code']) is int and value['exit_code']==0
        and isinstance(value['node_version'],str) and re.fullmatch(r'(22|24)\.[0-9]+\.[0-9]+',value['node_version']))
    sha(value['manifest_sha256']);sha(value['captured_output_sha256']);sha(value['stderr_sha256'])
    if manifest is not None:require(value['manifest_sha256']==manifest)
    require(type(value['captured_output_bytes']) is int and 0<=value['captured_output_bytes']<2**63)
    counts=value['counts'];require(isinstance(counts,dict) and set(counts)=={'tests','pass','fail','skipped','todo','cancelled'}
        and all(type(v) is int and v>=0 for v in counts.values()) and type(value['tests_run']) is int
        and 0<value['tests_run']==counts['tests']==counts['pass']<=100000
        and all(counts[k]==0 for k in ('fail','skipped','todo','cancelled')))
    inventory=value['inventory'];require(isinstance(inventory,list) and len(inventory)==value['tests_run'])
    for row in inventory:
        require(isinstance(row,dict) and set(row)=={'path','line','column','nesting','name_sha256'}
            and row['path'] in tests and all(type(row[k]) is int and 0<=row[k]<=2**31 for k in ('line','column','nesting')))
        safe_path(row['path']);sha(row['name_sha256'])
    canonical=[json.dumps(row,sort_keys=True) for row in inventory]
    require(canonical==sorted(canonical) and len(set(canonical))==len(canonical)
        and {row['path'] for row in inventory}==set(tests))
    if frozen is not None:
        validate(frozen,tests)
        require(value['inventory']==frozen['inventory'] and value['node_version']==frozen['node_version']
            and value['tests_run']==frozen['tests_run'])
    return value
