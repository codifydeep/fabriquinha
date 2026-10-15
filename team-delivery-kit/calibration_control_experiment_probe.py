"""Fixed isolated reference-control experiment. No policy registration or authority."""
import json
import os
from pathlib import Path
import re
import signal
import sys
import tempfile
import contextlib
from generic_harness_calibration import digest,require
import generic_harness_calibration_v2 as engine
from generic_calibration_bundle_writer import write,decode_environment
from calibration_frozen_harness_probe import Results,OutputDigest

FLAGS=('calibration_approved','red_approved','product_green','author_retry_authorized','execution_authorized','delivery_approval')


def passes(measurements,policy):
    try:engine.validate_receipt({**measurements,'status':'passed'},policy,digest(policy));return True
    except (ValueError,KeyError,TypeError):return False


def validate(value,c,bundle):
    require(set(value)=={'operation','bundle_sha256','candidate_manifest_sha256','test_sha256','measurements',
        'functional_controls_passed','negative_failure_phases','snapshot_unchanged','controls_unchanged','model_calls','full_regression_suite_executed',*FLAGS})
    p=bundle['policy'];engine.validate_policy(p,bundle['policy_sha256']);r=value['measurements']
    require(value['operation']=='isolated_reference_control_experiment_v1' and value['bundle_sha256']==digest(bundle)
        and value['candidate_manifest_sha256']==c['prepared']['manifest_sha256']==p['candidate_manifest_sha256']
        and value['test_sha256']==c['prepared']['test_sha256']==p['test_sha256']
        and value['snapshot_unchanged'] is True and value['controls_unchanged'] is True
        and value['full_regression_suite_executed'] is False and type(value['model_calls']) is int and value['model_calls']==0
        and all(value[k] is False for k in FLAGS))
    require(set(r)=={'operation','status','policy_sha256','candidate_manifest_sha256','controls_manifest_sha256',
        'test_sha256','positive','negative_controls','product_green','red_approved','delivery_approval'}
        and r['status']=='observed' and r['operation']=='generic_harness_calibration_v2' and r['policy_sha256']==digest(p)
        and all(r[k]==p[k] for k in ('candidate_manifest_sha256','controls_manifest_sha256','test_sha256'))
        and all(r[k] is False for k in ('product_green','red_approved','delivery_approval')))
    def counts(facts,tests):
        require(set(facts)=={'tests','failures','errors','skipped','expected_failures','unexpected_successes','output_sha256'}
            and all(type(facts[k]) is int and facts[k]>=0 for k in facts if k!='output_sha256') and facts['tests']==tests
            and bool(re.fullmatch('[a-f0-9]{64}',str(facts['output_sha256']))))
    counts(r['positive'],sum(len(methods) for m in p['modules'] for methods in m['classes'].values()))
    require(set(r['negative_controls'])=={n['id'] for n in p['negatives']})
    for facts in r['negative_controls'].values():counts(facts,1)
    phases=value['negative_failure_phases']
    require(set(phases)==set(r['negative_controls']) and set(phases.values())<=
        {'test_body','set_up','tear_down','clean_up','not_an_assertion_failure'})
    require(type(value['functional_controls_passed']) is bool and value['functional_controls_passed']==
        (passes(r,p) and all(phase=='test_body' for phase in phases.values())))
    return value


def run(candidate,bundle,expected):
    require(digest(bundle)==expected and bundle['policy']['engine']=='unittest_path_fixtures_v2')
    outcomes=[];captured=OutputDigest()
    def observe_suite(suite):
        result=Results()
        with contextlib.redirect_stdout(captured),contextlib.redirect_stderr(captured):suite.run(result)
        outcomes.append(result.observations)
        return dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
            expected_failures=len(result.expectedFailures),unexpected_successes=len(result.unexpectedSuccesses),
            output_sha256=digest(dict(outcomes=result.observations,captured_output_sha256=captured.hash.hexdigest())))
    with tempfile.TemporaryDirectory(prefix='reference-controls-') as temporary:
        root=Path(temporary);controls=root/'controls';policy=root/'policy';controls.mkdir();policy.mkdir()
        write(controls,policy,bundle,expected)
        measurements=engine.observe(candidate,controls,bundle['policy'],bundle['policy_sha256'],_observe_suite=observe_suite)
    require(len(outcomes)==1+len(bundle['policy']['negatives']))
    phases={n['id']:rows[0].get('phase','not_an_assertion_failure') if len(rows)==1 and rows[0]['outcome']=='failure'
        else 'not_an_assertion_failure' for n,rows in zip(bundle['policy']['negatives'],outcomes[1:])}
    value=dict(operation='isolated_reference_control_experiment_v1',bundle_sha256=expected,
        candidate_manifest_sha256=bundle['policy']['candidate_manifest_sha256'],test_sha256=bundle['policy']['test_sha256'],
        measurements=measurements,negative_failure_phases=phases,
        functional_controls_passed=passes(measurements,bundle['policy']) and all(v=='test_body' for v in phases.values()),
        snapshot_unchanged=True,controls_unchanged=True,model_calls=0,full_regression_suite_executed=False,
        **{k:False for k in FLAGS})
    return validate(value,dict(prepared=dict(manifest_sha256=bundle['policy']['candidate_manifest_sha256'],
        test_sha256=bundle['policy']['test_sha256'])),bundle)


if __name__=='__main__':
    require(len(sys.argv)==3);signal.alarm(420)
    print(json.dumps(run(sys.argv[1],decode_environment(os.environ.get('CALIBRATION_BUNDLE_ZLIB')),sys.argv[2]),sort_keys=True))
