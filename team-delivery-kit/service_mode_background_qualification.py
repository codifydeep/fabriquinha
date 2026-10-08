"""Mandatory background-traffic calibration for new request-scope amendments.

Run offline with the frozen candidate read-only. Existing receipts are not
upgraded. Passing controls never constitutes Red, product Green or approval.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import service_mode_harness_qualification as calibration
from r3_snapshot_probe import probe as verify_snapshot

BACKGROUND="fetch('/service-status');fetch('/feedback');fetch('/feedback/summary');\n"


def validate(facts,positive):
    if (facts.get('tests')!=positive.get('tests') or facts.get('tests',0)<15
            or any(facts.get(k)!=0 for k in
                ('failures','errors','skipped','unexpected_successes','expected_failures'))):
        raise ValueError('all positive assertions with legitimate background traffic required')


def run(root,manifest):
    root=Path(root);result=calibration.run(root,manifest)
    spec=importlib.util.spec_from_file_location('background_calibration',root/calibration.TEST)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    cls=getattr(module,calibration.CLASS);module.NODE_TIMEOUT_SECONDS=3
    original=module.APP_JS_PATH;fixture=BACKGROUND+calibration.fixture('positive')
    try:
        with tempfile.TemporaryDirectory(prefix='background-calibration-') as directory:
            path=Path(directory)/'control.js';path.write_text(fixture);module.APP_JS_PATH=path
            facts=calibration.observed(cls)
    finally:
        module.APP_JS_PATH=original;verify_snapshot(root,manifest)
    try:validate(facts,result['positive'])
    except ValueError:
        raise calibration.CalibrationRejected('background_control',dict(manifest_sha256=manifest,
            test_sha256=result['test_sha256'],positive=result['positive'],background=facts)) from None
    return {**result,'background_control':facts,'background_fixture_sha256':hashlib.sha256(fixture.encode()).hexdigest()}


def rejection(error):
    """Preserve controller calibration facts, never arbitrary exception text."""
    result=dict(status='rejected',category=type(error).__name__,delivery_approval=False)
    if isinstance(error,calibration.CalibrationRejected):
        result.update(phase=error.phase,facts=error.facts)
    return result


if __name__=='__main__':
    import sys
    try:print(json.dumps(run(*sys.argv[1:]),sort_keys=True))
    except Exception as error:
        print(json.dumps(rejection(error),sort_keys=True))
        sys.exit(1)
