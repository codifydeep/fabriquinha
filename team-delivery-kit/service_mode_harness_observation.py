"""Fixed read-only observation of a frozen harness, never a test amendment.

Run offline with the snapshot read-only and temporary storage isolated. Original
assertions execute unchanged. Instrumentation adds timer provenance to a separate
in-memory template; it must preserve every original report field byte-for-byte.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from r3_snapshot_probe import probe as verify_snapshot
from service_mode_harness_qualification import TEST, PRODUCT, CLASS, observed


def instrument(template):
    replacements = {
        'const intervals = [];': 'const intervals = [];\nconst controllerCaptures = [];',
        'function recordTimeout(fn, ms) { timeouts.push({ fn: fn, ms: ms, load_id: currentLid });':
            'function recordTimeout(fn, ms) { timeouts.push({ fn: fn, ms: ms, load_id: currentLid, controller_stack: new Error().stack });',
        'function recordInterval(fn, ms) { intervals.push({ fn: fn, ms: ms, load_id: currentLid });':
            'function recordInterval(fn, ms) { intervals.push({ fn: fn, ms: ms, load_id: currentLid, controller_stack: new Error().stack });',
        'function probeTimeoutCount() {':
            "function probeTimeoutCount() { controllerCaptures.push({kind:'timeout', load_id:currentLid, slice_start:sliceTimeoutStart, total:timeouts.length});",
        'function probeIntervalCount() {':
            "function probeIntervalCount() { controllerCaptures.push({kind:'interval', load_id:currentLid, slice_start:sliceIntervalStart, total:intervals.length});",
        'function report(payload) { process.stdout.write(JSON.stringify(payload)); }':
            "function report(payload) { payload.controller_observation={captures:controllerCaptures, timers:timeouts.concat(intervals).map(function(t){return {ms:t.ms, load_id:t.load_id, stack:String(t.controller_stack).split('\\n').filter(function(s){return s.indexOf(SOURCE_NAME+':')!==-1;}).slice(0,4)};})}; process.stdout.write(JSON.stringify(payload)); }",
    }
    for old, new in replacements.items():
        if template.count(old) != 1: raise ValueError('exact supported observation anchor required')
        template = template.replace(old,new,1)
    return template


def facts(original, measured):
    measured = dict(measured)
    extra = measured.pop('controller_observation',None)
    if measured != original or original.get('executed') is not True or original.get('error') is not None:
        raise ValueError('instrumentation changed original harness observations')
    if not isinstance(extra,dict) or set(extra) != {'captures','timers'}:
        raise ValueError('fixed timer observation required')
    if len(extra['captures']) > 128 or len(extra['timers']) > 512:
        raise ValueError('bounded timer observation required')
    for capture in extra['captures']:
        if (set(capture) != {'kind','load_id','slice_start','total'}
                or capture['kind'] not in ('timeout','interval')
                or any(type(capture[k]) is not int or capture[k] < 0 for k in ('load_id','slice_start','total'))):
            raise ValueError('fixed numeric timer capture required')
    for timer in extra['timers']:
        if (set(timer) != {'ms','load_id','stack'} or type(timer['ms']) not in (int,float)
                or type(timer['load_id']) is not int or timer['load_id'] < 0
                or not isinstance(timer['stack'],list) or len(timer['stack']) > 4
                or any(not isinstance(s,str) or len(s) > 256
                       or not re.fullmatch(r'\s*at [^\r\n]*\/delivery\/app\/static\/app\.js:\d+:\d+\)?',s)
                       for s in timer['stack'])):
            raise ValueError('bounded product timer provenance required')
    keys = ('after_ok','pending_observed','pending_issued','timer_count','interval_count',
            'pending_timer_count','pending_interval_count','mode_request_total')
    return dict(original_report={k:original[k] for k in keys},timer_observation=extra,
                instrumentation_preserved_report=True)


def run(root,manifest):
    root=Path(root);verify_snapshot(root,manifest)
    spec=importlib.util.spec_from_file_location('frozen_timer_observation',root/TEST)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    cls=getattr(module,CLASS);module.NODE_TIMEOUT_SECONDS=3
    original=module.NODE_HARNESS_TEMPLATE
    cls.setUpClass()
    first=cls('test_no_timers_are_armed_for_the_probe');first.setUp()
    baseline=observed(cls)
    try:
        module.NODE_HARNESS_TEMPLATE=instrument(original)
        second=cls('test_no_timers_are_armed_for_the_probe');second.setUp()
        observations=facts(first.report,second.report)
    finally:
        module.NODE_HARNESS_TEMPLATE=original
        verify_snapshot(root,manifest)
    return dict(operation='immutable_harness_timer_observation_v1',manifest_sha256=manifest,
        test_sha256=hashlib.sha256((root/TEST).read_bytes()).hexdigest(),
        product_sha256=hashlib.sha256((root/PRODUCT).read_bytes()).hexdigest(),
        original_suite=baseline,**observations,snapshot_modified=False,assertions_modified=False,
        test_edits_authorized=False,product_green=False,delivery_approval=False)


if __name__=='__main__':
    import sys
    print(json.dumps(run(sys.argv[1],sys.argv[2]),sort_keys=True))
