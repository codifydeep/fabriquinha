"""Full baseline suite plus fixed mutations; approved files are byte-identical."""
import hashlib,json,subprocess,sys,tempfile,shutil
from pathlib import Path
from maintenance_snapshot_validate import manifest
from u3_negative_controls import mutate,MODES
from additive_test_policy import validate,METHODS

RUNNER="""import unittest,json,sys
sys.path.insert(0,'.')
r=unittest.TestResult()
s=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in sys.argv[1:])
s.run(r)
print(json.dumps({'tests':r.testsRun,'failures':[{'test':t.id(),'trace':e[-2000:]} for t,e in r.failures],'errors':[{'test':t.id(),'trace':e[-2000:]} for t,e in r.errors],'skipped':len(r.skipped),'successful':r.wasSuccessful()}))
"""

def run():
    import os,re
    seed,candidate=Path('/seed'),Path('/candidate');before,old=manifest(seed);raw,new=manifest(candidate)
    unit=os.environ['CRITERION'];path=os.environ['NEW_TEST'];step=int(os.environ['STEP'])
    if hashlib.sha256(before).hexdigest()!=os.environ['SEED_MANIFEST']:raise ValueError('seed drift')
    if set(new)!=set(old)|{path} or any(new[p]!=old[p] for p in old):raise ValueError('existing file changed')
    validate((candidate/path).read_text(),unit)
    existing='tests/test_u3_c01_controls.py'
    modules=['tests.test_incremental_u3']+(['tests.test_u3_c01_controls'] if step==2 else [])+[path[:-3].replace('/','.')]
    reports={}
    with tempfile.TemporaryDirectory(prefix='u3-validate-') as tmp:
        for mode in MODES:
            copy=Path(tmp)/mode;shutil.copytree(candidate,copy)
            app=copy/'app/static/app.js';app.chmod(0o600);app.write_text(mutate(app.read_text(),mode))
            p=subprocess.run([sys.executable,'-c',RUNNER,*modules],cwd=copy,capture_output=True,text=True,timeout=60)
            if p.returncode:raise ValueError('mutation runner infrastructure failure')
            reports[mode]=json.loads(p.stdout)
            if reports[mode]['tests']!=4+step or reports[mode]['errors'] or reports[mode]['skipped']:raise ValueError('mutation discovery/error/skip failure')
            reports[mode]['app_sha256']=hashlib.sha256(app.read_bytes()).hexdigest()
        if not reports['baseline']['successful']:raise ValueError('new control fails approved baseline')
        for mode,method in [('retain_query',METHODS['C01']),('allow_stale_query','test_c10_stale_query_and_status_responses_are_discarded')]+([('allow_stale_status',METHODS['C02'])] if step==2 else []):
            if not any(f['test'].endswith('.'+method) for f in reports[mode]['failures']):raise ValueError('required mutation survived:'+mode)
        p=subprocess.run([sys.executable,'-m','unittest','discover','-s','.','-q'],cwd=Path(tmp)/'baseline',capture_output=True,text=True,timeout=90)
        output=p.stdout+p.stderr;match=re.search(r'Ran (\d+) tests',output)
        if p.returncode!=0 or not match or int(match[1])!=259+step or 'skipped=' in output:raise ValueError('complete pinned suite must pass exact count')
    if manifest(seed)[0]!=before or manifest(candidate)[0]!=raw:raise ValueError('snapshot changed')
    return {'schema':'u3-additive-validation-v1','criterion':unit,'new_test':path,'step':step,
        'manifest_sha256':hashlib.sha256(raw).hexdigest(),'original_files_unchanged':True,
        'mutations':reports,'full_suite':{'tests':259+step,'exit_code':0,'output_sha256':hashlib.sha256(output.encode()).hexdigest()},
        'network':'none','snapshot_mount':'readonly','controls_complete':step==2,'delivery_approval':False,'valid_red_green_receipt':False}

if __name__=='__main__':print(json.dumps(run(),sort_keys=True))
