"""Offline adoption evidence; never manufacture historical TDD or release approval."""
import hashlib,json,os,shutil,subprocess,sys,tempfile
from pathlib import Path
from portable_contract import safe_path
try:from maintenance_snapshot_validate import manifest
except ImportError:from broker.maintenance_snapshot_validate import manifest

TESTS=('tests/test_incremental_u3.py','tests/test_u3_c01_controls.py','tests/test_u3_c02_controls.py')

def sha(raw):return hashlib.sha256(raw).hexdigest()

def inventory(base,candidate,base_sha,candidate_sha):
    base,candidate=Path(base),Path(candidate)
    raw=(base/'manifest.json').read_bytes();meta=json.loads(raw);files=meta['files']
    if sha(raw)!=base_sha:raise ValueError('original base manifest mismatch')
    actual={str(p.relative_to(base)) for p in base.rglob('*') if p.is_file() or p.is_symlink()}
    if actual!=set(files)|{'manifest.json'}:raise ValueError('original base inventory mismatch')
    for name,digest in files.items():
        safe_path(name);p=base/name
        if p.is_symlink() or any(parent.is_symlink() for parent in list(p.parents)[:len(Path(name).parts)-1]):
            raise ValueError('base symlink rejected')
        if not isinstance(digest,str) or sha(p.read_bytes())!=digest:raise ValueError('original base file mismatch')
    raw_candidate,new=manifest(candidate)
    if sha(raw_candidate)!=candidate_sha:raise ValueError('approved controls manifest mismatch')
    if set(new)!=(set(files)-{'contract.json'})|set(TESTS):raise ValueError('three approved additive test files only')
    for name in set(files)-{'contract.json'}:
        if new[name]['sha256']!=files[name]:raise ValueError('product or previous test changed')
    return {'base_sha':meta['base_sha'],'base_manifest_sha256':base_sha,
        'controls_manifest_sha256':candidate_sha,'previous_files_unchanged':True,
        'new_test_sha256':{p:new[p]['sha256'] for p in TESTS}}

RUNNER='''import json,unittest
s=unittest.TestLoader().discover('.',pattern='test*.py')
r=unittest.TestResult();s.run(r)
print(json.dumps(dict(tests=r.testsRun,successful=r.wasSuccessful(),
 failures=[t.id() for t,_ in r.failures],errors=[t.id() for t,_ in r.errors],skipped=len(r.skipped))))
'''

def suite(root):
    p=subprocess.run([sys.executable,'-c',RUNNER],cwd=root,text=True,capture_output=True,timeout=90,
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    if p.returncode:raise ValueError('fixed suite runner infrastructure failed')
    return json.loads(p.stdout)

def classify(baseline,coverage,candidate):
    if baseline!={'tests':255,'successful':True,'failures':[],'errors':[],'skipped':0}:
        raise ValueError('unchanged predecessor baseline must pass 255 tests')
    if candidate!={'tests':261,'successful':True,'failures':[],'errors':[],'skipped':0}:
        raise ValueError('approved complete candidate must pass 261 tests')
    if coverage!=candidate:raise ValueError('identical original product with identical tests must agree')
    return 'existing_behavior_coverage_only'

def run(base,candidate,base_sha,candidate_sha):
    facts=inventory(base,candidate,base_sha,candidate_sha)
    with tempfile.TemporaryDirectory(prefix='u3-product-intake-') as tmp:
        root=Path(tmp);original=root/'original';covered=root/'covered';accepted=root/'accepted'
        shutil.copytree(base,original);shutil.copytree(base,covered);shutil.copytree(candidate,accepted)
        for name in TESTS:
            p=covered/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(Path(candidate)/name,p)
        before=suite(original);after=suite(covered);green=suite(accepted)
    if inventory(base,candidate,base_sha,candidate_sha)!=facts:raise ValueError('readonly inputs changed')
    return dict(schema='u3-product-coverage-probe-v1',classification=classify(before,after,green),
        baseline=before,original_with_approved_tests=after,candidate=green,**facts,
        network='none',inputs_mount='readonly',model_calls=0,new_code_required=False,
        historical_tdd_red=False,product_admission_authorized=False,delivery_approval=False)

if __name__=='__main__':print(json.dumps(run('/base','/candidate',os.environ['BASE_MANIFEST'],os.environ['CONTROLS_MANIFEST']),sort_keys=True))
