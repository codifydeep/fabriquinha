"""One new CTO diagnosis after installing controller capture constraints."""
import subprocess
import sys
import resume_sort_capture_diagnosis as recovery

recovery.PRIOR_CTO = '01a0fa7c-3bed-74ef-ad73-79c551610983'
recovery.EXPECTED_STAGE = 'technical_decision_required'
recovery.BACKUP_NAME = 'pre-grounded-capture-20261002.sqlite'
recovery.REVISION = '991ade4c3010493e3c88a39bfa46f901302cbb961aca381e5ae1cde0b4ab4fe9:controller-capture-v3'

if __name__ == '__main__':
    if sys.argv[1:] not in ([], ['--reconcile']):
        raise SystemExit('only --reconcile is supported')
    result = subprocess.run(['docker', 'exec', '-e', 'PYTHONPATH=/',
        'delivery-kit-port2-execution-broker-1', 'python', '-c',
        recovery.command(bool(sys.argv[1:]))], text=True, capture_output=True)
    if result.returncode:
        raise SystemExit(result.stderr.strip())
    print(result.stdout.strip())
