"""Pure v2 quality policy: real Red, independent test review, Green, sensitivity.

These functions validate *facts*, not their provenance. Only a controller adapter
which authenticates native runs, immutable snapshots and fixed-job receipts may
use their result. No worker endpoint, database enrollment, retry, merge grant or
historical-evidence conversion is provided by this module.
"""
import hashlib
import json
import re

from portable_contract import safe_path
import quality_node_evidence as node

POLICY='red_review_green_sensitivity'
COMMON={'operation','run_id','issue_id','contract_sha256','plan_sha256'}
SUITE={'tests','exit_code','suite_complete','tests_run','skipped','errors','failures'}
PLAN={'version','policy','run_id','issue_id','contract_sha256','base_sha',
      'author','reviewer','criteria','baseline_tests','new_tests','product_files','criterion_tests','protected_files'}


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def require(value):
    if not value:raise ValueError('exact v2 quality lifecycle evidence required')


def sha(value,length=64):require(isinstance(value,str) and re.fullmatch('[a-f0-9]{'+str(length)+'}',value))


def names(values):
    require(isinstance(values,list) and bool(values) and len(values)<=128
        and all(isinstance(v,str) and 1<=len(v)<=240 for v in values) and len(set(values))==len(values))


def validate(plan):
    require(isinstance(plan,dict))
    require(all(isinstance(plan.get(k),list) and all(isinstance(p,str) for p in plan[k])
        for k in ('protected_files','product_files','new_tests')))
    node_paths=node.paths(plan.get('protected_files',[])+plan.get('product_files',[])+plan.get('new_tests',[]))
    require(set(plan)==PLAN|({'node_baseline_tests'} if node_paths else set()) and type(plan['version']) is int
        and plan['version']==2 and plan['policy']==POLICY)
    for k in ('run_id','issue_id','author','reviewer'):
        require(isinstance(plan[k],str) and bool(re.fullmatch('[A-Za-z0-9_-]{1,80}',plan[k])))
    require(plan['author']!=plan['reviewer']);sha(plan['contract_sha256']);sha(plan['base_sha'],40)
    names(plan['criteria'])
    require(all(re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,63}',c) for c in plan['criteria']))
    for key in ('new_tests','product_files','protected_files'):
        names(plan[key])
        for path in plan[key]:safe_path(path)
    baseline=plan['baseline_tests'];require(isinstance(baseline,dict) and 1<=len(baseline)<=128)
    for path,value in baseline.items():safe_path(path);sha(value)
    require(not set(baseline)&set(plan['new_tests'])
        and set(baseline)|set(plan['new_tests'])<=set(plan['protected_files'])
        and not set(plan['product_files'])&set(plan['protected_files']))
    require(all(not p.startswith(('.github/','.gitlab/','.delivery-kit/')) for p in plan['product_files']))
    if node_paths:
        require(node_paths<=set(plan['protected_files']) and not node_paths&set(plan['new_tests'])
            and isinstance(plan['node_baseline_tests'],dict) and set(plan['node_baseline_tests'])==node_paths)
        for value in plan['node_baseline_tests'].values():sha(value)
    mapping=plan['criterion_tests'];require(isinstance(mapping,dict) and set(mapping)==set(plan['criteria']))
    for entries in mapping.values():
        require(isinstance(entries,list) and 1<=len(entries)<=128)
        for item in entries:
            require(isinstance(item,dict) and set(item)=={'path','method'} and item['path'] in plan['new_tests']
                and isinstance(item['method'],str) and re.fullmatch('test_[A-Za-z0-9_]+',item['method']))
        require(len({(x['path'],x['method']) for x in entries})==len(entries))
    return plan


def envelope(plan,evidence,operation,fields):
    require(isinstance(evidence,dict) and set(evidence)==COMMON|fields
        and evidence['operation']==operation
        and all(evidence[k]==plan[k] for k in ('run_id','issue_id','contract_sha256'))
        and evidence['plan_sha256']==digest(plan))


def suite_fields(plan):return SUITE|({'node_baseline'} if plan.get('node_baseline_tests') else set())


def suite(plan,value,*,passing,minimum=1,frozen=None,node_manifest=None,frozen_node=None):
    if plan.get('node_baseline_tests'):
        node.validate(value['node_baseline'],plan['node_baseline_tests'],manifest=node_manifest,frozen=frozen_node)
    tests=value['tests'];require(isinstance(tests,dict)
        and set(tests)==set(plan['baseline_tests'])|set(plan['new_tests']))
    for path,h in tests.items():sha(h)
    require(all(tests[p]==h for p,h in plan['baseline_tests'].items()))
    if frozen is not None:require(tests==frozen)
    require(value['suite_complete'] is True and type(value['exit_code']) is int
        and value['exit_code']==(0 if passing else 1)
        and type(value['tests_run']) is int and value['tests_run']>=minimum
        and type(value['skipped']) is int and value['skipped']==0
        and type(value['errors']) is int and value['errors']==0
        and isinstance(value['failures'],list))
    if passing:require(value['failures']==[]);return
    require(bool(value['failures']))
    for failure in value['failures']:
        require(isinstance(failure,dict) and set(failure)=={'path','method','phase','kind'}
            and failure['path'] in plan['new_tests'] and failure['phase']=='test_body'
            and failure['kind']=='assertion' and isinstance(failure['method'],str)
            and re.fullmatch('test_[A-Za-z0-9_]+',failure['method']))


def red(plan,evidence):
    envelope(plan,evidence,'observed_red_v2',suite_fields(plan)|{'task_id','manifest_sha256'})
    require(isinstance(evidence['task_id'],str) and bool(evidence['task_id']));sha(evidence['manifest_sha256'])
    suite(plan,evidence,passing=False,node_manifest=evidence['manifest_sha256'])


def review(plan,observed,decision):
    envelope(plan,decision,'independent_test_review_v2',{'task_id','author','reviewer','manifest_sha256',
        'red_sha256','decision','criteria','complete_reads','read_only'})
    require(isinstance(decision['task_id'],str) and bool(decision['task_id'])
        and decision['task_id']!=observed['task_id'] and decision['author']==plan['author']
        and decision['reviewer']==plan['reviewer'] and decision['manifest_sha256']==observed['manifest_sha256']
        and decision['red_sha256']==digest(observed) and decision['decision']=='approve_tests'
        and decision['complete_reads'] is True and decision['read_only'] is True)
    names(decision['criteria']);require(set(decision['criteria'])==set(plan['criteria']))


def green(plan,observed,decision,evidence):
    if plan.get('node_baseline_tests'):
        node.validate(observed.get('node_baseline'),plan['node_baseline_tests'],manifest=observed['manifest_sha256'])
    envelope(plan,evidence,'observed_green_v2',suite_fields(plan)|{'task_id','manifest_sha256','commit_sha',
        'red_sha256','test_review_sha256'})
    require(isinstance(evidence['task_id'],str) and bool(evidence['task_id'])
        and evidence['task_id'] not in (observed['task_id'],decision['task_id'])
        and evidence['red_sha256']==digest(observed) and evidence['test_review_sha256']==digest(decision))
    sha(evidence['manifest_sha256']);sha(evidence['commit_sha'],40)
    suite(plan,evidence,passing=True,minimum=observed['tests_run'],frozen=observed['tests'],
        node_manifest=evidence['manifest_sha256'],frozen_node=observed.get('node_baseline'))


def sensitivity(plan,passing,evidence):
    if plan.get('node_baseline_tests'):
        node.validate(passing.get('node_baseline'),plan['node_baseline_tests'],manifest=passing['manifest_sha256'])
    envelope(plan,evidence,'observed_sensitivity_v2',{'green_sha256','manifest_sha256','commit_sha','positive_sha256','controls'})
    require(evidence['green_sha256']==digest(passing) and evidence['positive_sha256']==digest(passing)
        and evidence['manifest_sha256']==passing['manifest_sha256'] and evidence['commit_sha']==passing['commit_sha']
        and isinstance(evidence['controls'],list) and 1<=len(evidence['controls'])<=128)
    covered=set();ids=set()
    for control in evidence['controls']:
        require(isinstance(control,dict) and set(control)==suite_fields(plan)|{'id','criteria','changed_files'}
            and isinstance(control['id'],str) and re.fullmatch('[A-Za-z0-9_-]{1,80}',control['id'])
            and control['id'] not in ids)
        ids.add(control['id']);names(control['criteria']);names(control['changed_files'])
        require(set(control['criteria'])<=set(plan['criteria']) and set(control['changed_files'])<=set(plan['product_files']))
        suite(plan,control,passing=False,minimum=passing['tests_run'],frozen=passing['tests'],
            frozen_node=passing.get('node_baseline'))
        witnesses={(f['path'],f['method']) for f in control['failures']}
        for criterion in control['criteria']:
            require(any((f['path'],f['method']) in witnesses for f in plan['criterion_tests'][criterion]))
        covered.update(control['criteria'])
    require(covered==set(plan['criteria']))


def next_stage(plan,evidence):
    validate(plan);require(isinstance(evidence,dict) and set(evidence)<={'red','test_review','green','sensitivity'})
    ordered=('red','test_review','green','sensitivity');n=len(evidence)
    require(set(evidence)==set(ordered[:n])) # No later evidence may jump an earlier gate.
    if n==0:return 'red'
    red(plan,evidence['red'])
    if n==1:return 'test_review'
    review(plan,evidence['red'],evidence['test_review'])
    if n==2:return 'implementation'
    green(plan,evidence['red'],evidence['test_review'],evidence['green'])
    if n==3:return 'sensitivity'
    sensitivity(plan,evidence['green'],evidence['sensitivity'])
    return 'independent_delivery_review'


def qualify_sensitivity(plan,evidence):
    require(next_stage(plan,evidence)=='independent_delivery_review')
    return dict(operation='quality_lifecycle_policy_facts_v2',plan_sha256=digest(plan),
        evidence_sha256=digest(evidence),commit_sha=evidence['green']['commit_sha'],
        manifest_sha256=evidence['green']['manifest_sha256'],
        merge_authorized=False,delivery_approval=False)
