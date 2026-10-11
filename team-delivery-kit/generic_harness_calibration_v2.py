"""Multi-Path unittest calibration in a restricted sandbox; no delivery authority.

Separate policy/receipt version. V1 evidence is never upgraded implicitly.
Only declared existing Path globals are redirected; frozen tests are not edited.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import unittest
import uuid
from generic_harness_calibration import digest,require,relative,identifier,names,observed
from r3_snapshot_probe import probe


def validate_policy(p,expected):
    fields={'version','engine','source_task','execution_sha256','plan_sha256',
        'candidate_manifest_sha256','controls_manifest_sha256','criteria','test_sha256',
        'previous_methods','modules','negatives'}
    require(isinstance(p,dict) and set(p)==fields and digest(p)==expected)
    require(p['version']=='generic_harness_calibration_v2' and p['engine']=='unittest_path_fixtures_v2')
    require(str(uuid.UUID(p['source_task']))==p['source_task'])
    for key in ('execution_sha256','plan_sha256','candidate_manifest_sha256','controls_manifest_sha256'):
        require(isinstance(p[key],str) and re.fullmatch('[a-f0-9]{64}',p[key]))
    criteria=p['criteria'];require(isinstance(criteria,list) and 1<=len(criteria)<=32
        and len(criteria)==len(set(criteria)))
    for c in criteria:identifier(c,r'A[0-9]{2}')
    require(isinstance(p['modules'],list) and 1<=len(p['modules'])<=32)
    require(isinstance(p['test_sha256'],dict) and isinstance(p['previous_methods'],dict))
    modules={};positives=set()
    for m in p['modules']:
        require(isinstance(m,dict) and set(m)=={'path','fixtures','classes'})
        path=relative(m['path']);require(path.endswith('.py') and path not in modules)
        names(m['classes']);modules[path]=m
        require(path in p['test_sha256'] and re.fullmatch('[a-f0-9]{64}',str(p['test_sha256'][path])))
        old=names(p['previous_methods'].get(path))
        for cls,methods in old.items():require(cls in m['classes'] and set(methods)<=set(m['classes'][cls]))
        require(isinstance(m['fixtures'],list) and 1<=len(m['fixtures'])<=16)
        attributes=set();products=set()
        for f in m['fixtures']:
            require(isinstance(f,dict) and set(f)=={'attribute','product_path','positive_fixture'})
            identifier(f['attribute'],r'[A-Z][A-Z0-9_]{0,119}')
            product=relative(f['product_path']);fixture=relative(f['positive_fixture'])
            require(f['attribute'] not in attributes and product not in products and product not in p['test_sha256'])
            attributes.add(f['attribute']);products.add(product);positives.add(fixture)
    require(set(modules)==set(p['test_sha256'])==set(p['previous_methods']))
    require(isinstance(p['negatives'],list) and 1<=len(p['negatives'])<=256)
    ids=set();covered=set()
    for n in p['negatives']:
        require(isinstance(n,dict) and set(n)=={'id','module','class_name','method','replacements','criteria'})
        identifier(n['id']);require(n['id'] not in ids);ids.add(n['id'])
        require(n['module'] in modules);m=modules[n['module']]
        require(n['class_name'] in m['classes'] and n['method'] in m['classes'][n['class_name']])
        require(isinstance(n['replacements'],list) and 1<=len(n['replacements'])<=len(m['fixtures']))
        targets={f['attribute'] for f in m['fixtures']};changed=set()
        for replacement in n['replacements']:
            require(isinstance(replacement,dict) and set(replacement)=={'attribute','fixture'})
            attribute=replacement['attribute'];require(attribute in targets and attribute not in changed)
            changed.add(attribute);require(relative(replacement['fixture']) not in positives)
        require(isinstance(n['criteria'],list) and n['criteria'] and len(n['criteria'])==len(set(n['criteria']))
            and set(n['criteria'])<=set(criteria));covered.update(n['criteria'])
    require(covered==set(criteria))
    return p


def validate_receipt(r,p,expected):
    validate_policy(p,expected)
    require(isinstance(r,dict) and set(r)=={'operation','status','policy_sha256',
        'candidate_manifest_sha256','controls_manifest_sha256','test_sha256','positive',
        'negative_controls','product_green','red_approved','delivery_approval'})
    require(r['operation']=='generic_harness_calibration_v2' and r['status']=='passed'
        and r['policy_sha256']==expected and r['test_sha256']==p['test_sha256']
        and all(r[k]==p[k] for k in ('candidate_manifest_sha256','controls_manifest_sha256'))
        and all(r[k] is False for k in ('product_green','red_approved','delivery_approval')))
    def counts(facts,tests,failures):
        require(isinstance(facts,dict) and set(facts)=={'tests','failures','errors','skipped',
            'expected_failures','unexpected_successes','output_sha256'})
        for key in ('tests','failures','errors','skipped','expected_failures','unexpected_successes'):
            require(type(facts[key]) is int and facts[key]==(tests if key=='tests' else failures if key=='failures' else 0))
        require(re.fullmatch('[a-f0-9]{64}',str(facts['output_sha256'])))
    counts(r['positive'],sum(len(v) for m in p['modules'] for v in m['classes'].values()),0)
    require(isinstance(r['negative_controls'],dict) and set(r['negative_controls'])=={n['id'] for n in p['negatives']})
    for result in r['negative_controls'].values():counts(result,1,1)
    return r


def run(candidate,controls,policy,expected):
    p=validate_policy(policy,expected);candidate=Path(candidate);controls=Path(controls)
    probe(candidate,p['candidate_manifest_sha256']);probe(controls,p['controls_manifest_sha256'])
    files=json.loads((candidate/'manifest.json').read_text())['files']
    fixtures=json.loads((controls/'manifest.json').read_text())['files']
    for path,sha in p['test_sha256'].items():require(files.get(path,{}).get('sha256')==sha)
    required={f['positive_fixture'] for m in p['modules'] for f in m['fixtures']}
    required|={r['fixture'] for n in p['negatives'] for r in n['replacements']}
    require(set(fixtures)==required)
    for m in p['modules']:
        for f in m['fixtures']:require(f['product_path'] in files)
    loaded={};saved={};bytecode=sys.dont_write_bytecode;sys.dont_write_bytecode=True
    def positive_paths(module,m):
        for f in m['fixtures']:setattr(module,f['attribute'],controls/f['positive_fixture'])
    try:
        for i,m in enumerate(p['modules']):
            name='_calibration_v2_'+expected+'_'+str(i);require(name not in sys.modules)
            spec=importlib.util.spec_from_file_location(name,candidate/m['path'])
            module=importlib.util.module_from_spec(spec);sys.modules[name]=module;saved[name]=module
            spec.loader.exec_module(module)
            classes={k:v for k,v in vars(module).items() if isinstance(v,type)
                and issubclass(v,unittest.TestCase) and v is not unittest.TestCase and v.__module__==name}
            require(set(classes)==set(m['classes']))
            for k,cls in classes.items():require(set(unittest.defaultTestLoader.getTestCaseNames(cls))==set(m['classes'][k]))
            for f in m['fixtures']:
                value=getattr(module,f['attribute'],None)
                require(isinstance(value,Path) and value.resolve()==(candidate/f['product_path']).resolve())
            positive_paths(module,m);loaded[m['path']]=(module,classes,m)
        positive=observed(unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls)
            for module,classes,m in loaded.values() for cls in classes.values()))
        negatives={}
        for n in p['negatives']:
            module,classes,m=loaded[n['module']];positive_paths(module,m)
            for replacement in n['replacements']:
                setattr(module,replacement['attribute'],controls/replacement['fixture'])
            try:negatives[n['id']]=observed(unittest.TestSuite([classes[n['class_name']](n['method'])]))
            finally:positive_paths(module,m)
        receipt=dict(operation='generic_harness_calibration_v2',status='passed',policy_sha256=expected,
            candidate_manifest_sha256=p['candidate_manifest_sha256'],controls_manifest_sha256=p['controls_manifest_sha256'],
            test_sha256=p['test_sha256'],positive=positive,negative_controls=negatives,
            product_green=False,red_approved=False,delivery_approval=False)
        return validate_receipt(receipt,p,expected)
    finally:
        sys.dont_write_bytecode=bytecode
        for name,module in saved.items():
            if sys.modules.get(name) is module:del sys.modules[name]
        probe(candidate,p['candidate_manifest_sha256']);probe(controls,p['controls_manifest_sha256'])


if __name__=='__main__':
    try:
        require(len(sys.argv)==5);path=Path(sys.argv[3])
        require(not path.is_symlink() and path.stat().st_size<=524288)
        print(json.dumps(run(sys.argv[1],sys.argv[2],json.loads(path.read_text()),sys.argv[4]),sort_keys=True))
    except Exception as error:
        print(json.dumps(dict(status='rejected',category=type(error).__name__,
            product_green=False,red_approved=False,delivery_approval=False)))
        sys.exit(1)
