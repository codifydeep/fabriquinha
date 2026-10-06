"""Fixed controller-owned probe; candidate code executes only in the sandbox."""
import os,subprocess,unittest,sys,json,hashlib
from pathlib import Path

def main():
    source=Path('/workspace/scripts/ci')
    contract=Path('/workspace/docs/governance/company-contract.md')
    if contract.exists() and contract.read_bytes()!=Path('/workspace/AGENTS.md').read_bytes():raise PermissionError('canonical company contract projection differs')
    generated=Path('/workspace/.hermes/team/generated-manifest.json')
    if generated.exists():
        for name,sha in json.loads(generated.read_text())['files'].items():
            path=Path('/workspace')/name
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise PermissionError('generated governance hash drift: '+name)
    subprocess.run(['openssl','pkey','-pubin','-in',str(source/'test-maintenance-public.pem'),'-noout'],check=True,capture_output=True)
    subprocess.run(['bash','-n',str(source/'test-integrity-guard.sh')],check=True)
    compile((source/'verify-test-maintenance.py').read_text(),'candidate-verifier','exec')
    os.environ['GOVERNANCE_CANDIDATE']=str(source)
    sys.path.insert(0,'/opt/hermes/governance-probes')
    suite=unittest.defaultTestLoader.loadTestsFromName('test_reviewed_integrity_guard')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if result.testsRun!=7 or not result.wasSuccessful():raise SystemExit(1)
if __name__=='__main__':main()
