"""Read-only experiment: proposed harness repairs are in-memory, not delivery.

This receipt cannot serve as Red, Green, a test revision or review approval.
"""
import hashlib
import importlib.util
from pathlib import Path

TEST='tests/test_feedback_search_client.py'
PARSER="const value = (a[3] !== undefined) ? a[3] : (a[4] !== undefined) ? a[4] : (a[5] !== undefined) ? a[5] : '';"
PARSER_FIX="const value = (a[2] !== undefined) ? a[2] : (a[3] !== undefined) ? a[3] : (a[4] !== undefined) ? a[4] : '';"
PREDICATE='&& accessibleName(el) === label;'
PREDICATE_FIX="&& accessibleName(el) === label && !byId['feedback-form'].contains(el);"


def proposed_template(template, parser=False, containment=False):
    for old,new,enabled in ((PARSER,PARSER_FIX,parser),(PREDICATE,PREDICATE_FIX,containment)):
        if template.count(old)!=1:
            raise ValueError('exact diagnostic seed required')
        if enabled:template=template.replace(old,new)
    return template


def run(red_root,candidate_root):
    roots={'red':Path(red_root),'candidate':Path(candidate_root)}
    paths=(TEST,'app/static/index.html','app/static/app.js')
    def hashes():
        return {name:{p:hashlib.sha256((root/p).read_bytes()).hexdigest()
            for p in paths} for name,root in roots.items()}
    before=hashes()
    if before['red'][TEST]!=before['candidate'][TEST]:
        raise ValueError('frozen test identity drift')
    reports={}
    for name,root in roots.items():
        spec=importlib.util.spec_from_file_location('diagnostic_'+name,root/TEST)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        template=module.NODE_HARNESS_TEMPLATE
        module.FeedbackSearchClientTests.setUpClass()
        reports[name]={}
        try:
            for mode,parser,containment in [('original',False,False),
                    ('parser_only',True,False),('containment_only',False,True),('both',True,True)]:
                module.NODE_HARNESS_TEMPLATE=proposed_template(template,parser,containment)
                case=module.FeedbackSearchClientTests();case.setUp()
                inside=case.negative('inside_form')
                results={}
                for method in sorted(m for m in dir(case) if m.startswith('test_')):
                    try:getattr(case,method)();results[method]=True
                    except AssertionError:results[method]=False
                reports[name][mode]={'executed':case.report['executed'],
                    'inside_control':{k:inside[k] for k in
                        ('canonical_match','accepted','rejected_by_predicate')},
                    'test_results':results}
        finally:module.NODE_HARNESS_TEMPLATE=template
    if hashes()!=before:raise ValueError('immutable experiment input changed')
    return {'operation':'frozen_negative_control_spike_v1','input_sha256':before,
        'reports':reports,'inputs_unchanged':True,'in_memory_hypotheses_only':True,
        'delivery_approval':False,'valid_red_green_receipt':False}
