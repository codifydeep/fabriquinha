"""Operator opt-in: arm the audited one-shot injector before assignment."""
import json
from pathlib import Path
import subprocess
import time
import uuid


def arm(private,instance,issue,run=subprocess.run,read=subprocess.check_output):
    from release_eval import save_receipt
    from docker_grouping import labels
    labels(namespace=instance)
    if str(uuid.UUID(issue))!=issue:raise ValueError('canonical fault issue required')
    path=Path(private)/'fault-injection'/(issue+'.dispatch.json')
    if path.is_symlink() or path.parent.is_symlink():raise ValueError('unsafe fault dispatch storage')
    if path.exists():raise ValueError('fault dispatch already attempted; observe without repeating')
    source=(Path(__file__).parent/'inject_pretool_worker_loss.py').read_text()
    # Controller script only; no worker or prompt can supply code/identity.
    script=source.split("if __name__ == '__main__':")[0]+'\ninject('+repr(issue)+',timeout=900)\n'
    save_receipt(path,dict(issue_id=issue,instance=instance,stage='intent',
                          author_retry_authorized=False,delivery_approval=False))
    run(['docker','exec','-d','-e','PYTHONPATH=/',instance+'-execution-broker-1',
         'python','-c',script],check=True,timeout=15)
    query=('import json,sys,broker as b;p=b.STATE/"fault-injection"/(sys.argv[1]+".armed.json");'
           'print(json.dumps(json.loads(p.read_text()) if p.exists() and not p.is_symlink() else None))')
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        proof=json.loads(read(['docker','exec','-e','PYTHONPATH=/',instance+'-execution-broker-1',
                            'python','-c',query,issue],text=True,timeout=5))
        if proof and proof.get('issue_id')==issue and proof.get('operation')=='controlled_pretool_sigkill':
            save_receipt(path,dict(issue_id=issue,instance=instance,stage='armed',proof=proof,
                                  author_retry_authorized=False,delivery_approval=False))
            return
        time.sleep(.1)
    raise TimeoutError('fault arm not observed; do not assign or repeat dispatch')
