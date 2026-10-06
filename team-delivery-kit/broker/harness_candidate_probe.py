"""Fixed sandbox probe of submitted harness bytes, never the diagnostic adapter.

Caller must isolate this executable without network, secrets or Docker socket.
Both candidate Red and historical positive fixture are mounted read-only.
"""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re

try:
    from harness_selector_spike import TEST, TEST_SHA, SELECTOR
except ImportError:
    from broker.harness_selector_spike import TEST, TEST_SHA, SELECTOR


def _assertions(source):
    tree = ast.parse(source)
    methods = {}
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == 'FeedbackSearchClientTests':
            for method in cls.body:
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name.startswith('test_'):
                    if method.name in methods:
                        raise ValueError('duplicate test method')
                    methods[method.name] = [ast.dump(node, include_attributes=False)
                        for node in ast.walk(method) if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == 'self'
                        and node.func.attr.startswith('assert')]
    if not methods or any(not values for values in methods.values()):
        raise ValueError('asserted test methods required')
    return methods


def preserve_assertions(original, candidate, *, require_new_method=True):
    """Necessary structural guard; independent semantic review remains required."""
    old, new = _assertions(original), _assertions(candidate)
    for name, calls in old.items():
        remaining = list(new.get(name, []))
        for call in calls:
            if call not in remaining:
                raise ValueError('historical assertion changed or removed')
            remaining.remove(call)
    if require_new_method and len(new) <= len(old):
        raise ValueError('new negative-control test method required')


def validate_reports(reports):
    expected = {'quoted', 'unquoted', 'wrong_type', 'nonexistent_type', 'inside_form', 'wrong_label'}
    keys = {'executed', 'error', 'total_search', 'outside_form', 'inside_form', 'type', 'name'}
    if set(reports) != expected or any(set(r) != keys or r['executed'] is not True
            or r['error'] is not None or any(type(r[k]) is not int or r[k] < 0
                for k in ('total_search', 'outside_form', 'inside_form')) for r in reports.values()):
        raise ValueError('complete actual candidate controls required')
    positive = dict(executed=True, error=None, total_search=1, outside_form=1,
                    inside_form=0, type='search', name='Search feedback')
    if reports['quoted'] != positive or reports['unquoted'] != positive:
        raise ValueError('candidate positive selector control failed')
    empty = dict(executed=True, error=None, total_search=0, outside_form=0,
                 inside_form=0, type=None, name=None)
    if reports['wrong_type'] != empty or reports['nonexistent_type'] != empty:
        raise ValueError('candidate type selector false positive')
    inside = dict(empty, total_search=1, inside_form=1)
    if reports['inside_form'] != inside:
        raise ValueError('candidate position control failed')
    if reports['wrong_label'] != empty:
        raise ValueError('candidate accessible name control failed')


def validate_internal_negatives(cases):
    expected={'wrong_type_text':False,'wrong_type_number':False,
              'wrong_label':True,'blank_label':True,'inside_form':True}
    if not isinstance(cases,list) or len(cases)!=len(expected):
        raise ValueError('complete internal negative controls required')
    found={}
    for case in cases:
        if not isinstance(case,dict) or case.get('name') in found:
            raise ValueError('unique actual negative controls required')
        found[case.get('name')]=case
    if set(found)!=set(expected):raise ValueError('internal negative control identity drift')
    for name,canonical in expected.items():
        c=found[name]
        if (c.get('canonical_match') is not canonical or c.get('accepted') is not False
                or c.get('rejected_by_predicate') is not True):
            raise ValueError('internal negative control behavior failed: '+name)


def _verify(root, paths):
    root = Path(root)
    raw = (root/'manifest.json').read_bytes()
    manifest = json.loads(raw)['files']
    hashes = {}
    for name in paths:
        path = root/name
        if path.is_symlink() or not path.is_file():
            raise ValueError('regular immutable probe input required')
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != manifest[name]['sha256']:
            raise ValueError('candidate probe input drift')
        hashes[name] = sha
    return hashlib.sha256(raw).hexdigest(), hashes


def selector_template(template, selector):
    """Exercise the submitted harness; literal multiplicity is not correctness.

    Added negative tests may repeat the canonical selector. All six runtime
    controls still have to pass; a string occurrence count cannot replace them.
    """
    if not isinstance(template,str) or SELECTOR not in template:
        raise ValueError('canonical selector required')
    return template.replace(SELECTOR,selector)


def run(candidate_root, fixture_root):
    candidate_root, fixture_root = Path(candidate_root), Path(fixture_root)
    paths = (TEST, 'app/static/app.js', 'app/static/index.html')
    candidate_manifest, candidate_hashes = _verify(candidate_root, paths)
    fixture_manifest, fixture_hashes = _verify(fixture_root, paths)
    original = (fixture_root/TEST).read_bytes()
    candidate = (candidate_root/TEST).read_bytes()
    if fixture_hashes[TEST] != TEST_SHA or candidate_hashes[TEST] == TEST_SHA:
        raise ValueError('historical fixture and genuinely new harness required')
    preserve_assertions(original, candidate, require_new_method=False)
    html = (fixture_root/'app/static/index.html').read_text()
    inputs = re.findall(r'<input\b[^>]*\btype="search"[^>]*>', html)
    if len(inputs) != 1 or html.count('</form>') != 1 or 'Search feedback' not in html:
        raise ValueError('fixed native search fixture required')
    spec = importlib.util.spec_from_file_location('candidate_harness', candidate_root/TEST)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.FeedbackSearchClientTests.setUpClass()
    template = module.NODE_HARNESS_TEMPLATE
    selector_template(template,SELECTOR)
    # No adapter is injected: these are the author's real submitted DOM methods.
    cases = [('quoted', SELECTOR, html), ('unquoted', 'input[type=search]', html),
        ('wrong_type', SELECTOR, html.replace(inputs[0], inputs[0].replace('type="search"', 'type="text"'))),
        ('nonexistent_type', 'input[type=not-real]', html),
        ('inside_form', SELECTOR, html.replace(inputs[0], '').replace('</form>', inputs[0]+'</form>')),
        ('wrong_label', SELECTOR, html.replace('Search feedback', 'Wrong label'))]
    original_run = module.subprocess.run
    reports = {}
    try:
        for name, selector, fixture in cases:
            module.NODE_HARNESS_TEMPLATE = selector_template(template,selector)
            prefix = ('const _probeFs=require("fs"),_probeRead=_probeFs.readFileSync;'
                '_probeFs.readFileSync=function(path,...args){const value=_probeRead.call(this,path,...args);'
                'if(String(path).endsWith("/app/static/index.html")){const fixture='+json.dumps(fixture)+';'
                'return Buffer.isBuffer(value)?Buffer.from(fixture):fixture;}return value;};\n')
            def observed(*args, **kwargs):
                program = kwargs.get('input')
                if not isinstance(program, bytes):
                    raise ValueError('actual Node stdin required')
                kwargs['input'] = prefix.encode()+program
                kwargs['timeout'] = 8
                return original_run(*args, **kwargs)
            module.subprocess.run = observed
            test = module.FeedbackSearchClientTests()
            test.setUp()
            if name=='quoted':
                validate_internal_negatives(test.report.get('negatives'))
                internal_negatives=test.report['negatives']
            reports[name] = {k:test.report[k] for k in
                ('executed', 'error', 'total_search', 'outside_form', 'inside_form', 'type', 'name')}
    finally:
        module.subprocess.run = original_run
        module.NODE_HARNESS_TEMPLATE = template
    validate_reports(reports)
    if _verify(candidate_root, paths) != (candidate_manifest, candidate_hashes) or _verify(fixture_root, paths) != (fixture_manifest, fixture_hashes):
        raise ValueError('candidate probe changed immutable input')
    return dict(operation='actual_candidate_selector_controls_v2', candidate_manifest_sha256=candidate_manifest,
        fixture_manifest_sha256=fixture_manifest, candidate_sha256=candidate_hashes,
        fixture_sha256=fixture_hashes, reports=reports, internal_negatives=internal_negatives,
        repository_modified=False, delivery_approval=False)
