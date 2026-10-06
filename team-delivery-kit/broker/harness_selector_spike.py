"""Fixed offline experiment, not a submitted test repair or delivery evidence.

Executed only in a credential-free container over an owned read-only snapshot.
Mutations affect in-memory harness/HTML inputs; repository bytes never change.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re

TEST = 'tests/test_feedback_search_client.py'
TEST_SHA = '34d79233fec5c23bfa2d5c28be4e22d2e1c6eb5cea5d5d246be2032877665e70'
SELECTOR = 'input[type="search"]'


class HypothesisRejected(ValueError):
    def __init__(self, reports):
        self.reports = reports
        super().__init__('controlled selector hypothesis not confirmed')


def validate_reports(reports):
    required = {'original_quoted','equivalent_unquoted','all_inputs_diagnostic',
        'wrong_type_control','inside_form_control','wrong_label_control','nonexistent_type_control'}
    required |= {'adapted_'+n for n in required if n!='all_inputs_diagnostic'}
    if set(reports)!=required or any(r.get('executed') is not True or r.get('error') is not None for r in reports.values()):
        raise HypothesisRejected(reports)
    positive = reports['adapted_original_quoted']
    if (positive != dict(executed=True, error=None, total_search=1, outside_form=1,
                         inside_form=0, type='search', name='Search feedback')
            or reports['original_quoted']['total_search'] != 0
            or reports['equivalent_unquoted']['total_search'] != 0
            or reports['all_inputs_diagnostic'] != positive
            or reports['adapted_equivalent_unquoted'] != positive
            or reports['adapted_wrong_type_control']['total_search'] != 0
            or reports['adapted_nonexistent_type_control']['total_search'] != 0
            or reports['adapted_inside_form_control']['inside_form'] != 1
            or reports['adapted_inside_form_control']['outside_form'] != 0
            or reports['adapted_wrong_label_control']['name'] == 'Search feedback'):
        raise HypothesisRejected(reports)


def run(root):
    root = Path(root)
    raw = (root/TEST).read_bytes()
    if hashlib.sha256(raw).hexdigest() != TEST_SHA:
        raise ValueError('exact disputed test required')
    manifest_raw = (root/'manifest.json').read_bytes()
    manifest = json.loads(manifest_raw)['files']
    hashes = {}
    for name in (TEST, 'app/static/app.js', 'app/static/index.html'):
        path = root/name
        if path.is_symlink(): raise ValueError('regular snapshot input required')
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != manifest[name]['sha256']: raise ValueError('snapshot input drift')
        hashes[name] = sha
    html = (root/'app/static/index.html').read_text()
    inputs = re.findall(r'<input\b[^>]*\btype="search"[^>]*>', html)
    if len(inputs) != 1 or html.count('</form>') != 1:
        raise ValueError('single native search and form fixture required')
    spec = importlib.util.spec_from_file_location('disputed_harness', root/TEST)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.FeedbackSearchClientTests.setUpClass()
    template = module.NODE_HARNESS_TEMPLATE
    if template.count(SELECTOR) != 1: raise ValueError('single disputed selector required')
    methods = list(re.finditer(r'querySelectorAll\s*[:=]\s*function\s*\(([A-Za-z_$][A-Za-z0-9_$]*)\)\s*\{', template))
    if not 1<=len(methods)<=3:raise ValueError('fixed querySelectorAll signature required')
    adapted = template
    for method in reversed(methods):
        adapter = ('\nconst _selectorProbe=/^([a-zA-Z][a-zA-Z0-9_-]*)\\[([a-zA-Z][a-zA-Z0-9_-]*)='
            '(?:"([^"]*)"|\'([^\']*)\'|([^\\]]+))\\]$/.exec('+method[1]+');'
            'if(_selectorProbe){const _selectorValue=_selectorProbe[3]??_selectorProbe[4]??_selectorProbe[5];'
            'return this.querySelectorAll(_selectorProbe[1]).filter(el=>el.getAttribute(_selectorProbe[2])===_selectorValue);}\n')
        adapted = adapted[:method.end()]+adapter+adapted[method.end():]
    original_run = module.subprocess.run
    cases = [
        ('original_quoted', SELECTOR, html),
        ('equivalent_unquoted', 'input[type=search]', html),
        ('all_inputs_diagnostic', 'input', html),
        ('wrong_type_control', 'input[type=search]', html.replace(inputs[0], inputs[0].replace('type="search"', 'type="text"'))),
        ('inside_form_control', 'input[type=search]', html.replace(inputs[0], '').replace('</form>', inputs[0]+'</form>')),
        ('wrong_label_control', 'input[type=search]', html.replace('Search feedback', 'Wrong label')),
        ('nonexistent_type_control', 'input[type=not-real]', html),
    ]
    cases += [('adapted_'+name, selector, fixture) for name, selector, fixture in cases
              if name!='all_inputs_diagnostic']
    reports = {}
    try:
        for name, selector, fixture in cases:
            module.NODE_HARNESS_TEMPLATE = (adapted if name.startswith('adapted_') else template).replace(SELECTOR, selector)
            # Intercept only the HTML read inside the disposable Node process.
            # Real application JS and original Python assertions stay intact.
            prefix = ('const _probeFs=require("fs"),_probeRead=_probeFs.readFileSync;'
                '_probeFs.readFileSync=function(path,...args){const value=_probeRead.call(this,path,...args);'
                'if(String(path).endsWith("/app/static/index.html")){const fixture='+json.dumps(fixture)+';'
                'return Buffer.isBuffer(value)?Buffer.from(fixture):fixture;}return value;};\n')
            def observed(*args, **kwargs):
                program = kwargs.get('input')
                if not isinstance(program, bytes): raise ValueError('actual Node stdin required')
                kwargs['input'] = prefix.encode()+program
                return original_run(*args, **kwargs)
            module.subprocess.run = observed
            test = module.FeedbackSearchClientTests()
            test.setUp()
            reports[name] = {k:test.report[k] for k in
                ('executed', 'error', 'total_search', 'outside_form', 'inside_form', 'type', 'name')}
    finally:
        module.subprocess.run = original_run
        module.NODE_HARNESS_TEMPLATE = template
    validate_reports(reports)
    for name, sha in hashes.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != sha:
            raise ValueError('experiment modified input')
    return dict(operation='actual_node_attribute_selector_spike_v1',
        manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(), input_sha256=hashes,
        reports=reports, conclusion='harness_lacks_attribute_selector_support_confirmed_by_controls',
        repository_modified=False, delivery_approval=False)
