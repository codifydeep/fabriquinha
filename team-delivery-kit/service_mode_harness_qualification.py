"""Calibrate a submitted harness against fixed controls, not product Green.

Run only in an offline disposable sandbox: snapshot read-only, no secrets or
Docker socket, writable /tmp only. Controls are controller-owned JS fixtures;
they never replace repository files. Genuine Red and independent reviews are
separate, mandatory gates.
"""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

from inherited_harness_probe import run as compile_snapshot
from r3_snapshot_probe import probe as verify_snapshot

TEST = 'tests/test_service_mode_indicator.py'
PRODUCT = 'app/static/app.js'
TEMPLATE = 'NODE_HARNESS_TEMPLATE'
CLASS = 'ServiceModeClientTests'
CASES = {
    'extra_key_accepted': 'test_extra_key_yields_unavailable',
    'other_mode_accepted': 'test_other_mode_value_yields_unavailable',
    'missing_key_accepted': 'test_missing_mode_key_yields_unavailable',
    'http_error_accepted': 'test_non_200_yields_unavailable',
    'malformed_json_accepted': 'test_malformed_json_yields_unavailable',
    'network_error_accepted': 'test_network_failure_yields_unavailable',
    'duplicate_request': 'test_client_requests_service_mode_once_at_load',
    'pending_premature': 'test_pending_probe_shows_checking_then_terminal_demo',
    'probe_interval': 'test_no_timers_are_armed_for_the_probe',
    'probe_timeout': 'test_no_timers_are_armed_for_the_probe',
    'form_interference': 'test_probe_never_blocks_or_mutates_form_search_filter_or_sort',
    'health_indicator_removed': 'test_preexisting_service_status_indicator_is_preserved',
}


def fixture(case):
    if case not in {'positive', *CASES}:raise ValueError('fixed calibration case required')
    # This is a control, not the implementation. All substitutions below are
    # fixed controller literals, never commands or code supplied by the agent.
    valid = "x && typeof x==='object' && !Array.isArray(x) && Object.keys(x).length===1 && x.mode==='demo'"
    if case=='extra_key_accepted':valid="x && x.mode==='demo'"
    if case=='other_mode_accepted':valid="x && typeof x.mode==='string'"
    if case=='missing_key_accepted':valid="x && typeof x==='object'"
    status = 'true' if case=='http_error_accepted' else 'r.status===200'
    catch = 'Demo environment' if case=='network_error_accepted' else 'Environment unavailable'
    parse = "r.json().catch(function(){return {mode:'demo'};})" if case=='malformed_json_accepted' else 'r.json()'
    prefix="document.getElementById('service-status').textContent='Service available';\n"
    if case=='health_indicator_removed':prefix="document.getElementById('service-status').textContent='Broken';\n"
    prefix+="const m=document.getElementById('service-mode');\n"
    if case=='pending_premature':prefix+="m.textContent='Demo environment';\n"
    if case=='form_interference':prefix+="document.getElementById('title').value='Changed by probe';\n"
    if case=='duplicate_request':prefix+="fetch('/service-mode');\n"
    if case=='probe_interval':prefix+="setInterval(function(){fetch('/service-mode');},1000);\n"
    if case=='probe_timeout':prefix+="setTimeout(function(){fetch('/service-mode');},1000);\n"
    return prefix+("fetch('/service-mode').then(function(r){if(!("+status+")){throw new Error('http');}"
        "return "+parse+";}).then(function(x){m.textContent=("+valid+")?'Demo environment':'Environment unavailable';})"
        ".catch(function(){m.textContent="+json.dumps(catch)+";});\n")


def observed(cls, method=None):
    suite = (unittest.defaultTestLoader.loadTestsFromTestCase(cls) if method is None
             else unittest.TestSuite([cls(method)]))
    # Full tracebacks may contain submitted source. Persist counts and hashes,
    # never interpret an exception or swallowed failure as a negative success.
    output=io.StringIO();result=unittest.TextTestRunner(stream=output,verbosity=0).run(suite)
    return dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
                skipped=len(result.skipped),unexpected_successes=len(result.unexpectedSuccesses),
                expected_failures=len(result.expectedFailures),
                output_sha256=hashlib.sha256(output.getvalue().encode()).hexdigest())


def validate_controls(positive, negatives):
    if (positive.get('tests',0)<15 or any(positive.get(k)!=0 for k in
        ('failures','errors','skipped','unexpected_successes','expected_failures'))):
        raise ValueError('candidate harness rejects correct reference or does not fully execute')
    if set(negatives)!=set(CASES):raise ValueError('complete controller negative controls required')
    for case,facts in negatives.items():
        if (facts.get('tests')!=1 or facts.get('failures')!=1 or any(facts.get(k)!=0 for k in
                ('errors','skipped','unexpected_successes','expected_failures'))):
            raise ValueError('candidate did not reject defect by assertion: '+case)


def run(root,manifest):
    root=Path(root)
    compiled=compile_snapshot(root,manifest,TEST,PRODUCT,TEMPLATE)
    if any(compiled[k]['exit_code']!=0 for k in ('control','harness','product')):
        raise ValueError('embedded harness/product must compile before behavioral calibration')
    spec=importlib.util.spec_from_file_location('submitted_service_mode_harness',root/TEST)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    cls=getattr(module,CLASS)
    module.NODE_TIMEOUT_SECONDS=3  # Controller wall-clock bound, not semantic filtering.
    methods=set(unittest.defaultTestLoader.getTestCaseNames(cls))
    if not set(CASES.values())<=methods:raise ValueError('declared behavioral methods missing')
    original=module.APP_JS_PATH
    negatives={}
    try:
        with tempfile.TemporaryDirectory(prefix='harness-controls-') as directory:
            path=Path(directory)/'control.js';module.APP_JS_PATH=path
            path.write_text(fixture('positive'));positive=observed(cls)
            if positive['failures'] or positive['errors']:
                raise ValueError('candidate harness rejects correct reference')
            for case,method in CASES.items():
                path.write_text(fixture(case));negatives[case]=observed(cls,method)
    finally:module.APP_JS_PATH=original
    validate_controls(positive,negatives)
    verify_snapshot(root,manifest)
    return dict(operation='service_mode_harness_calibration_v1',manifest_sha256=manifest,
        test_sha256=compiled['test_sha256'],compile=compiled,positive=positive,negative_controls=negatives,
        control_fixture_sha256={case:hashlib.sha256(fixture(case).encode()).hexdigest() for case in ['positive',*CASES]},
        status='passed',product_green=False,red_approved=False,delivery_approval=False)


if __name__=='__main__':
    import sys
    try:print(json.dumps(run(*sys.argv[1:]),sort_keys=True))
    except Exception as error:
        print(json.dumps(dict(status='rejected',category=type(error).__name__,delivery_approval=False)))
        sys.exit(1)
