"""Fixed mutation experiment on disposable copies; never delivery or TDD Red."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

TEST='tests/test_incremental_u3.py'
APP='app/static/app.js'
GUARD='if (requestedFilter !== currentFilter || requestedSearch !== currentSearchNeedle()) {'
NEEDLE='var needle = String(currentSearch).trim();'
MODES=('baseline','retain_query','allow_stale_query','allow_stale_status')


def mutate(source,mode):
    if mode not in MODES:raise ValueError('fixed negative-control mode required')
    if source.count(GUARD)!=1 or source.count(NEEDLE)!=1:
        raise ValueError('unique approved product anchors required')
    if mode=='retain_query':
        return source.replace(NEEDLE,NEEDLE+"\n  if (needle) { retainedQueryForNegativeControl = needle; }\n  if (!needle && typeof retainedQueryForNegativeControl !== 'undefined') { needle = retainedQueryForNegativeControl; }",1)
    if mode=='allow_stale_query':
        return source.replace(GUARD,'if (requestedFilter !== currentFilter) {',1)
    if mode=='allow_stale_status':
        return source.replace(GUARD,'if (requestedSearch !== currentSearchNeedle()) {',1)
    return source


def run(root,expected_test,expected_manifest):
    try:import maintenance_snapshot_validate as snapshots
    except ImportError:from broker import maintenance_snapshot_validate as snapshots
    root=Path(root);raw,files=snapshots.manifest(root)
    if (hashlib.sha256(raw).hexdigest()!=expected_manifest
            or files[TEST]['sha256']!=expected_test):
        raise ValueError('exact approved snapshot required')
    reports={};source=(root/APP).read_text()
    for mode in MODES:
        with tempfile.TemporaryDirectory(prefix='u3-control-') as directory:
            copy=Path(directory)/'candidate';shutil.copytree(root,copy)
            changed=mutate(source,mode);(copy/APP).chmod(0o600);(copy/APP).write_text(changed)
            if (copy/TEST).read_bytes()!=(root/TEST).read_bytes():
                raise ValueError('negative control changed the test')
            spec=importlib.util.spec_from_file_location('u3_control_'+mode,copy/TEST)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            result=unittest.TestResult();suite=unittest.defaultTestLoader.loadTestsFromModule(module)
            suite.run(result)
            details=[{'test':case.id().split('.',1)[1],'traceback':trace.replace(str(copy),'/disposable/candidate')[-3000:]}
                for case,trace in result.failures+result.errors]
            reports[mode]={'tests':result.testsRun,'failures':len(result.failures),
                'errors':len(result.errors),'skipped':len(result.skipped),
                'successful':result.wasSuccessful(),'details':details,
                'app_sha256':hashlib.sha256(changed.encode()).hexdigest(),
                'test_sha256':hashlib.sha256((copy/TEST).read_bytes()).hexdigest()}
    after,_=snapshots.manifest(root)
    if after!=raw:raise ValueError('approved snapshot changed')
    baseline=reports['baseline']
    if baseline['tests']!=4 or not baseline['successful'] or baseline['skipped']:
        raise ValueError('actual unchanged four-test baseline must pass')
    killed=[];survived=[];invalid=[]
    for mode in MODES[1:]:
        r=reports[mode]
        if r['tests']!=4 or r['errors'] or r['skipped']:invalid.append(mode)
        elif r['failures']:killed.append(mode)
        else:survived.append(mode)
    return {'schema':'u3-negative-controls-v1','manifest_sha256':expected_manifest,
        'test_sha256':expected_test,'reports':reports,'killed':killed,'survived':survived,
        'invalid':invalid,'inputs_unchanged':True,'network':'none','model_calls':0,
        'controls_complete':not survived and not invalid,'delivery_approval':False,
        'valid_red_green_receipt':False}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('root');parser.add_argument('test');parser.add_argument('manifest')
    args=parser.parse_args();print(json.dumps(run(args.root,args.test,args.manifest),sort_keys=True))
