"""Offline harness calibration engine, not a controller authorization API.

Execute ONLY in a disposable restricted sandbox: candidate and control bundles
read-only, no network, credentials or Docker socket, bounded CPU/memory/time.
The controller must independently approve the exact policy and control snapshot
before invoking this engine. A passed receipt grants no Red, Green or delivery
authority. The first adapter is Python unittest with a path-based fixture seam;
unsupported frameworks require a separate qualified adapter, never shell input.
"""
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import re
import sys
import unittest
import uuid

from r3_snapshot_probe import probe


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
        ensure_ascii=False).encode()).hexdigest()


def require(condition):
    if not condition:raise ValueError('exact bounded generic calibration contract required')


def relative(value):
    require(isinstance(value,str) and bool(re.fullmatch(r'[A-Za-z0-9_./-]{1,240}',value)))
    path=PurePosixPath(value)
    require(not path.is_absolute() and str(path)==value and all(p not in ('','.','..') for p in value.split('/')))
    return value


def identifier(value,pattern=r'[A-Za-z][A-Za-z0-9_]{0,119}'):
    require(isinstance(value,str) and bool(re.fullmatch(pattern,value)))
    return value


def names(value):
    require(isinstance(value,dict) and 1<=len(value)<=32)
    total=0
    for name,methods in value.items():
        identifier(name)
        require(isinstance(methods,list) and 1<=len(methods)<=512 and len(set(methods))==len(methods))
        for method in methods:identifier(method,r'test_[A-Za-z0-9_]{1,120}')
        total+=len(methods)
    require(total<=2048)
    return value


def validate_policy(p,expected):
    fields={'version','engine','source_task','execution_sha256','plan_sha256',
        'candidate_manifest_sha256','controls_manifest_sha256','criteria','test_sha256',
        'previous_methods','modules','negatives'}
    require(isinstance(p,dict) and set(p)==fields and digest(p)==expected)
    require(p['version']=='generic_harness_calibration_v1' and p['engine']=='unittest_path_fixture_v1')
    require(str(uuid.UUID(p['source_task']))==p['source_task'])
    for key in ('execution_sha256','plan_sha256','candidate_manifest_sha256','controls_manifest_sha256'):
        require(isinstance(p[key],str) and bool(re.fullmatch('[a-f0-9]{64}',p[key])))
    criteria=p['criteria']
    require(isinstance(criteria,list) and 1<=len(criteria)<=32 and len(set(criteria))==len(criteria))
    for c in criteria:identifier(c,r'A[0-9]{2}')
    require(isinstance(p['modules'],list) and 1<=len(p['modules'])<=32)
    require(isinstance(p['test_sha256'],dict) and isinstance(p['previous_methods'],dict))
    modules={}
    for m in p['modules']:
        require(isinstance(m,dict) and set(m)=={'path','fixture_attribute','product_path','positive_fixture','classes'})
        path=relative(m['path']);require(path not in modules and path.endswith('.py'))
        relative(m['product_path']);relative(m['positive_fixture'])
        require(m['product_path']!=path)
        identifier(m['fixture_attribute'],r'[A-Z][A-Z0-9_]{0,119}')
        names(m['classes']);modules[path]=m
        require(path in p['test_sha256'] and bool(re.fullmatch('[a-f0-9]{64}',str(p['test_sha256'][path]))))
        old=names(p['previous_methods'].get(path))
        for cls,methods in old.items():
            require(cls in m['classes'] and set(methods)<=set(m['classes'][cls]))
    require(set(modules)==set(p['test_sha256'])==set(p['previous_methods']))
    require(isinstance(p['negatives'],list) and 1<=len(p['negatives'])<=256)
    ids=set();covered=set()
    for n in p['negatives']:
        require(isinstance(n,dict) and set(n)=={'id','module','class_name','method','fixture','criteria'})
        identifier(n['id']);require(n['id'] not in ids);ids.add(n['id'])
        require(n['module'] in modules);m=modules[n['module']]
        require(n['class_name'] in m['classes'] and n['method'] in m['classes'][n['class_name']])
        relative(n['fixture']);require(n['fixture']!=m['positive_fixture'])
        require(isinstance(n['criteria'],list) and n['criteria'] and len(set(n['criteria']))==len(n['criteria'])
            and set(n['criteria'])<=set(criteria))
        covered.update(n['criteria'])
    require(covered==set(criteria))
    return p


def observed(suite):
    output=io.StringIO();result=unittest.TextTestRunner(stream=output,verbosity=0).run(suite)
    return dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        skipped=len(result.skipped),expected_failures=len(result.expectedFailures),
        unexpected_successes=len(result.unexpectedSuccesses),
        output_sha256=hashlib.sha256(output.getvalue().encode()).hexdigest())


def validate_receipt(r,p,expected):
    validate_policy(p,expected)
    require(isinstance(r,dict) and set(r)=={'operation','status','policy_sha256',
        'candidate_manifest_sha256','controls_manifest_sha256','test_sha256','positive',
        'negative_controls','product_green','red_approved','delivery_approval'})
    require(r['operation']=='generic_harness_calibration_v1' and r['status']=='passed'
        and r['policy_sha256']==expected and r['test_sha256']==p['test_sha256']
        and all(r[k]==p[k] for k in ('candidate_manifest_sha256','controls_manifest_sha256'))
        and all(r[k] is False for k in ('product_green','red_approved','delivery_approval')))
    count=sum(len(methods) for m in p['modules'] for methods in m['classes'].values())
    def counts(facts,tests,failures):
        require(isinstance(facts,dict) and set(facts)=={'tests','failures','errors','skipped',
            'expected_failures','unexpected_successes','output_sha256'})
        for key in ('tests','failures','errors','skipped','expected_failures','unexpected_successes'):
            require(type(facts[key]) is int and facts[key]==(tests if key=='tests' else failures if key=='failures' else 0))
        require(bool(re.fullmatch('[a-f0-9]{64}',str(facts['output_sha256']))))
    counts(r['positive'],count,0)
    require(isinstance(r['negative_controls'],dict) and set(r['negative_controls'])=={n['id'] for n in p['negatives']})
    for facts in r['negative_controls'].values():counts(facts,1,1)
    return r


def run(candidate,controls,policy,expected):
    p=validate_policy(policy,expected);candidate=Path(candidate);controls=Path(controls)
    probe(candidate,p['candidate_manifest_sha256']);probe(controls,p['controls_manifest_sha256'])
    files=json.loads((candidate/'manifest.json').read_text())['files']
    fixtures=json.loads((controls/'manifest.json').read_text())['files']
    for path,sha in p['test_sha256'].items():require(files.get(path,{}).get('sha256')==sha)
    for m in p['modules']:require(m['product_path'] in files and m['positive_fixture'] in fixtures)
    for n in p['negatives']:require(n['fixture'] in fixtures)
    loaded={};saved={}
    try:
        for i,m in enumerate(p['modules']):
            name='_calibration_'+expected+'_'+str(i)
            require(name not in sys.modules)
            spec=importlib.util.spec_from_file_location(name,candidate/m['path'])
            module=importlib.util.module_from_spec(spec);sys.modules[name]=module;saved[name]=module
            spec.loader.exec_module(module)
            discovered={key:cls for key,cls in vars(module).items() if isinstance(cls,type)
                and issubclass(cls,unittest.TestCase) and cls is not unittest.TestCase and cls.__module__==name}
            require(set(discovered)==set(m['classes']))
            for key,cls in discovered.items():
                require(set(unittest.defaultTestLoader.getTestCaseNames(cls))==set(m['classes'][key]))
            value=getattr(module,m['fixture_attribute'],None)
            require(isinstance(value,Path) and value.resolve()==(candidate/m['product_path']).resolve())
            setattr(module,m['fixture_attribute'],controls/m['positive_fixture'])
            loaded[m['path']]=(module,discovered,m)
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls)
            for module,classes,m in loaded.values() for cls in classes.values())
        positive=observed(suite);negatives={}
        for n in p['negatives']:
            module,classes,m=loaded[n['module']]
            setattr(module,m['fixture_attribute'],controls/n['fixture'])
            try:negatives[n['id']]=observed(unittest.TestSuite([classes[n['class_name']](n['method'])]))
            finally:setattr(module,m['fixture_attribute'],controls/m['positive_fixture'])
        receipt=dict(operation='generic_harness_calibration_v1',status='passed',policy_sha256=expected,
            candidate_manifest_sha256=p['candidate_manifest_sha256'],controls_manifest_sha256=p['controls_manifest_sha256'],
            test_sha256=p['test_sha256'],positive=positive,negative_controls=negatives,
            product_green=False,red_approved=False,delivery_approval=False)
        return validate_receipt(receipt,p,expected)
    finally:
        for name,module in saved.items():
            if sys.modules.get(name) is module:del sys.modules[name]
        probe(candidate,p['candidate_manifest_sha256']);probe(controls,p['controls_manifest_sha256'])


if __name__=='__main__':
    try:
        require(len(sys.argv)==5)
        policy_file=Path(sys.argv[3]);require(not policy_file.is_symlink() and policy_file.stat().st_size<=524288)
        print(json.dumps(run(sys.argv[1],sys.argv[2],json.loads(policy_file.read_text()),sys.argv[4]),sort_keys=True))
    except Exception as error:
        print(json.dumps(dict(status='rejected',category=type(error).__name__,
            product_green=False,red_approved=False,delivery_approval=False)))
        sys.exit(1)
