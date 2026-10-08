"""Calibrate attribution with legitimate polling AND actual probe timers.

Historical traffic-only receipts never satisfy this policy. No snapshot/test
edits, Red, Green or delivery approval are produced by these controls.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import service_mode_harness_qualification as calibration
from service_mode_background_qualification import BACKGROUND
from r3_snapshot_probe import probe as verify_snapshot

POLL=("\nsetTimeout(function(){fetch('/feedback');},200);\n"
      "setInterval(function(){fetch('/feedback/summary');fetch('/feedback');},2000);\n")
INDICATOR_TIMERS={
    'indicator_timeout':"setTimeout(function(){document.getElementById('service-mode').textContent='Demo environment';},1000);\n",
    'indicator_interval':"setInterval(function(){document.getElementById('service-mode').textContent='Demo environment';},1000);\n",
    # A delay whitelist must not confuse an invalid probe timer with polling.
    'probe_timeout_board_delay':"setTimeout(function(){fetch('/service-mode');},2000);\n",
    'probe_interval_board_delay':"setInterval(function(){fetch('/service-mode');},2000);\n",
}


def validate(positive,negatives):
    required=set(calibration.CASES)|set(INDICATOR_TIMERS)
    if (positive.get('tests',0)<15 or any(positive.get(k)!=0 for k in
            ('failures','errors','skipped','unexpected_successes','expected_failures'))
            or set(negatives)!=required):
        raise ValueError('complete assertions with legitimate background timer required')
    for value in negatives.values():
        if (value.get('tests')!=1 or value.get('failures')!=1
                or any(value.get(k)!=0 for k in ('errors','skipped','unexpected_successes','expected_failures'))):
            raise ValueError('actual probe timer and behavioral defects must fail by assertion')


def run(root,manifest):
    root=Path(root);result=calibration.run(root,manifest)
    spec=importlib.util.spec_from_file_location('timer_background_controls',root/calibration.TEST)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    cls=getattr(module,calibration.CLASS);module.NODE_TIMEOUT_SECONDS=3
    original=module.APP_JS_PATH;positive_fixture=BACKGROUND+calibration.fixture('positive')+POLL
    try:
        with tempfile.TemporaryDirectory(prefix='timer-background-controls-') as directory:
            path=Path(directory)/'control.js';module.APP_JS_PATH=path
            path.write_text(positive_fixture);positive=calibration.observed(cls)
            negatives={};hashes={}
            for case in sorted(set(calibration.CASES)|set(INDICATOR_TIMERS)):
                prefix=INDICATOR_TIMERS.get(case,'')
                code=BACKGROUND+prefix+calibration.fixture(case if case in calibration.CASES else 'positive')+POLL
                path.write_text(code);hashes[case]=hashlib.sha256(code.encode()).hexdigest()
                method=calibration.CASES.get(case,'test_no_timers_are_armed_for_the_probe')
                negatives[case]=calibration.observed(cls,method)
    finally:
        module.APP_JS_PATH=original;verify_snapshot(root,manifest)
    try:validate(positive,negatives)
    except ValueError:
        raise calibration.CalibrationRejected('background_timer_control',dict(
            manifest_sha256=manifest,test_sha256=result['test_sha256'],positive=positive,negative_controls=negatives)) from None
    return {**result,'timer_background_policy':'behavioral_timer_attribution_v1',
        'timer_background_control':positive,'timer_negative_controls':negatives,
        'timer_positive_fixture_sha256':hashlib.sha256(positive_fixture.encode()).hexdigest(),
        'timer_negative_fixture_sha256':hashes}


if __name__=='__main__':
    import sys
    from service_mode_background_qualification import rejection
    try:print(json.dumps(run(*sys.argv[1:]),sort_keys=True))
    except Exception as error:
        print(json.dumps(rejection(error),sort_keys=True));sys.exit(1)
