"""Controller-owned enrollment; the installed supervisor only observes cleanup."""
import hashlib
import json
from pathlib import Path
import deploy_u3_coverage as deploy
import recover_u3_qa_cleanup as recovery


def enroll():
    root = deploy.RECEIPT.parent
    state_path = root/'U3-COVERAGE-EXECUTED-QA.json'
    folder = deploy.pub.ROOT/'.local-port2/browser-acceptance/U3-INDEPENDENT-QA'
    paths = list(folder.glob('*.json'))
    if len(paths) != 1: raise ValueError('unique preserved fixed QA receipt required')
    path = paths[0]
    for item in (state_path, path, deploy.RECEIPT):
        if item.is_symlink() or not item.is_file() or item.stat().st_size > 65536:
            raise ValueError('bounded regular receipt required')
    state = json.loads(state_path.read_text()); proof = json.loads(path.read_text())
    deployment = json.loads(deploy.RECEIPT.read_text())
    recovery.validate(state, proof, deployment, path)  # includes actual screenshot hash
    packet = dict(failed_execution=state, failed_browser=proof,
                  failed_execution_sha256=hashlib.sha256(state_path.read_bytes()).hexdigest(),
                  failed_browser_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    script = 'import broker,qa_cleanup_observer,json;print(json.dumps({"enrolled_task":qa_cleanup_observer.register(broker,'+repr(packet)+')}))'
    return json.loads(deploy.pub.run('docker', 'exec', '-i', '-e', 'PYTHONPATH=/',
        deploy.pub.PROJECT+'-execution-broker-1', 'python', '-', data=script.encode()))


if __name__ == '__main__': print(json.dumps(enroll()))
