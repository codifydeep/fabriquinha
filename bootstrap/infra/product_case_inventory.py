"""Structured Vitest evidence; plain log markers alone are not case coverage."""
import json

def diagnostics(result):
    suites=[];failed=[]
    for line in result.get('output','').splitlines():
        try:report=json.loads(line)
        except (ValueError,TypeError):continue
        if not isinstance(report,dict):continue
        for suite in report.get('testResults',[]):
            path=suite.get('name','').removeprefix('/tmp/work/').removeprefix('/workspace/')
            assertions=suite.get('assertionResults',[])
            if suite.get('status')=='failed' and not any(a.get('status')=='failed' for a in assertions):suites.append(dict(path=path,message=suite.get('message','')[:1200]))
            failed.extend(dict(path=path,name=a.get('fullName'),messages=a.get('failureMessages',[])[:2]) for a in assertions if a.get('status')=='failed')
    return dict(exit_code=result.get('exit_code'),classification='discovery_or_infrastructure' if suites or (result.get('exit_code') and not failed) else 'behavioral_failure' if failed else 'passed',suite_failures=suites,failed_cases=failed,log_tail=result.get('output','')[-1500:])

def inventory(result):
    reports=[]
    for line in result.get('output','').splitlines():
        try:value=json.loads(line)
        except (ValueError,TypeError):continue
        if isinstance(value,dict) and isinstance(value.get('testResults'),list):reports.append(value)
    if len(reports)!=1:
        error=ValueError('one structured test report required; exit_code='+str(result.get('exit_code'))+'; executed output: '+result.get('output','')[-1500:])
        error.diagnostic=diagnostics(result)
        raise error
    cases={}
    for suite in reports[0]['testResults']:
        path=suite.get('name','')
        for prefix in ('/tmp/work/','/workspace/'):
            if path.startswith(prefix):path=path[len(prefix):]
        if not path or path.startswith('/') or '..' in path.split('/'):raise ValueError('unknown test source')
        for test in suite.get('assertionResults',[]):
            name=test.get('fullName') or ' '.join(test.get('ancestorTitles',[])+[test.get('title','')])
            key=path+'::'+name
            if not name or key in cases:raise ValueError('unique test case identity required')
            cases[key]=dict(path=path,status=test.get('status'),assertion_failure=any('AssertionError' in s or 'expected ' in s for s in test.get('failureMessages',[])))
    if not cases or any(c['status'] not in ('passed','failed') for c in cases.values()):raise ValueError('empty or ignored test inventory')
    return cases

def compare(before,after,mapping,renames):
    if not isinstance(mapping,dict) or any(not isinstance(k,str) or not isinstance(v,str) or k not in before or v not in after for k,v in mapping.items()):
        error=ValueError('case mapping references unknown evidence; use full path::fullName identities, never prose or bare titles')
        error.diagnostic=dict(phase='case_mapping',before_case_ids=list(before),after_case_ids=list(after),
            unknown_keys=[k for k in mapping if k not in before] if isinstance(mapping,dict) else [],
            unknown_values=[v for v in mapping.values() if not isinstance(v,str) or v not in after] if isinstance(mapping,dict) else [],
            contract='case_mapping is {exact_before_id: exact_after_id}. Omit unchanged identities: they are preserved automatically. No unchanged/changed tokens, rationale strings, synthesized codes, or title-only identifiers.')
        raise error
    if len(set(mapping.values()))!=len(mapping):raise ValueError('case mapping must not collapse coverage')
    mapped=[]
    for key,case in before.items():
        path,name=key.split('::',1);target=mapping.get(key,renames.get(path,path)+'::'+name)
        if target not in after:
            error=PermissionError('existing case disappeared: '+key)
            error.diagnostic=dict(phase='case_mapping',missing_before_case=key,before_case_ids=list(before),after_case_ids=list(after),contract='Map this complete prior identity to the exact successor identity only if semantic behavior is preserved; never delete coverage.')
            raise error
        mapped.append(target)
    if len(set(mapped))!=len(mapped):raise PermissionError('multiple baseline cases collapsed')
    return dict(preserved=len(mapped),new_cases=sorted(set(after)-set(mapped)))
