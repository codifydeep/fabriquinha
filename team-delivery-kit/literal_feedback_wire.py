"""Non-authorizing diagnostic wire checks shared by controller and worker."""
import re
import uuid
from pathlib import PurePosixPath

FALSE_FLAGS=('calibration_approved','red_approved','product_green','full_regression_suite_executed',
    'delivery_approval','author_retry_authorized','execution_authorized','python_assertions_executed',
    'python_test_module_imported','positive_reference_submitted')


def require(condition):
    if not condition:raise ValueError('author_feedback_contract_rejected')


def worker_config(cfg,execution=None):
    require(set(cfg)=={'request_id','task_id','capability','test_path','previous_manifest_sha256','feedback_sha256','expected'})
    for key in ('request_id','task_id'):require(str(uuid.UUID(cfg[key]))==cfg[key])
    for key in ('capability','previous_manifest_sha256','feedback_sha256'):require(bool(re.fullmatch('[a-f0-9]{64}',cfg[key])))
    path=PurePosixPath(cfg['test_path'])
    require(not path.is_absolute() and path.as_posix()==cfg['test_path'] and '..' not in path.parts
        and len(cfg['test_path'])<=240 and cfg['test_path'].endswith('.py'))
    require(execution is None or cfg['request_id']==execution)
    return cfg


def validate(value,cfg,sha,bound=False):
    require(isinstance(value,dict) and value['operation']=='literal_author_feedback_v1'
        and value['candidate_sha256']==sha and value['feedback_sha256']==cfg['feedback_sha256']
        and value['previous_manifest_sha256']==cfg['previous_manifest_sha256']
        and value['test_path']==cfg['test_path'] and value['expected']==cfg['expected']
        and value['outside_literal_bytes_preserved'] is True and value['candidate_bytes_stable_during_measurement'] is True
        and value['non_target_verification']=='not_performed_in_feedback'
        and value['evidence_scope']=='current_file_fixed_diagnostic_only'
        and type(value['model_calls']) is int and value['model_calls']==0 and all(value[k] is False for k in FALSE_FLAGS))
    reports=value['reports'];expected=cfg['expected']
    require(set(reports)=={'guarded','unguarded'} and set(expected)=={'initial_expected','poll_minimum','stale_expected'}
        and all(type(expected[k]) is int and 0<=expected[k]<=100 for k in ('initial_expected','poll_minimum'))
        and isinstance(expected['stale_expected'],str) and 1<=len(expected['stale_expected'])<=256)
    for report in reports.values():
        require(set(report)=={'initial_requests','poll_requests','stale_guard_text'}
            and all(type(report[k]) is int and 0<=report[k]<=10000 for k in ('initial_requests','poll_requests'))
            and isinstance(report['stale_guard_text'],str) and len(report['stale_guard_text'])<=256)
    outcomes=dict(initial_requests=all(r['initial_requests']==expected['initial_expected'] for r in reports.values()),
        poll_requests=all(r['poll_requests']>=expected['poll_minimum'] for r in reports.values()),
        stale_guard_text=reports['guarded']['stale_guard_text']==expected['stale_expected']
            and reports['unguarded']['stale_guard_text']!=expected['stale_expected'])
    require(type(value['checks_passed']) is bool and value['checks_passed'] is all(outcomes.values())
        and value['failed_fields']==[k for k,v in outcomes.items() if not v])
    capture=value['capture'];require(set(capture)=={'field','literal','literal_line','assignment'}
        and capture['field']=='poll_requests' and capture['literal']=='NODE_HARNESS'
        and type(capture['literal_line']) is int and 0<capture['literal_line']<=32768
        and capture['assignment']=='snap.poll_requests = latestCount();')
    if bound:
        require(value['request_id']==cfg['request_id'] and value['task_id']==cfg['task_id']
            and all(bool(re.fullmatch('[a-f0-9]{64}',value[k])) for k in ('validation_job_key','validation_contract_sha256')))


def presentation(value):
    # Never forward extra fields or arbitrary remote recommendations as policy.
    result={k:value[k] for k in ('operation','candidate_sha256','checks_passed','failed_fields','capture','reports','expected')}
    result.update({k:False for k in FALSE_FLAGS})
    result['evidence_scope']='current_file_fixed_diagnostic_only'
    result['instruction']=('Fixed diagnostics pass only for these bytes. Finish for controller freeze and independent review; '
        'this is not Red, product Green, regression, approval or delivery.' if value['checks_passed'] else
        'Do not finish with failed diagnostics. Inspect the exact failed field and capture location; '
        'edit only the declared literal and request fresh feedback. A saved patch is not a qualified submission.')
    if value['failed_fields']==['poll_requests']:
        result['instruction']+=' Drive the polling cycle BEFORE snap.poll_requests = latestCount();, not in the later stale-response block.'
    return result
