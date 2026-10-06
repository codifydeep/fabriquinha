"""Fixed local unittest runner for the score rehearsal; never elevated.

Not a general arbitrary-command executor. Run inside the assigned scratch as
the ordinary worker, with its existing tool permission checks intact.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_tests(root):
    names=sorted(p.name for p in root.glob('test*.py'))
    if names!=['test_new_score.py','test_score.py']:
        raise ValueError('Use exactly test_score.py and test_new_score.py; no alternate test runners')
    tree=ast.parse((root/'test_new_score.py').read_text())
    imports=[n for n in tree.body if isinstance(n,ast.ImportFrom) and n.module=='score']
    if not any(any(a.name=='winner' and a.asname is None for a in n.names) for n in imports):
        raise ValueError('Tests must use from score import winner')
    for node in ast.walk(tree):
        if isinstance(node,(ast.FunctionDef,ast.ClassDef)) and node.name=='winner':
            raise ValueError('Do not define a fake winner in tests')
        if isinstance(node,ast.Name) and node.id=='winner' and isinstance(node.ctx,ast.Store):
            raise ValueError('Do not replace imported winner')
    return {name:digest(root/name) for name in names}


def run(root,stage,contract,execute=None):
    root=Path(root).resolve()
    if any(p.is_symlink() for p in root.iterdir()):
        raise ValueError('Symlinks are not allowed in this rehearsal')
    hashes=check_tests(root)
    if hashes['test_score.py']!=contract['regression_sha256']:
        raise ValueError('Original regression hash changed')
    receipt=root/('runner-'+stage+'.json')
    if stage=='red':
        if digest(root/'score.py')!=contract['fixture_sha256']:
            raise ValueError('Red must precede implementation: restore the original fixture in a fresh cycle')
        if (root/'runner-red.json').exists() and json.loads((root/'runner-red.json').read_text()).get('accepted'):
            raise ValueError('Red already recorded; do not overwrite its evidence')
    elif stage in ('green','qa'):
        red=json.loads((root/'runner-red.json').read_text())
        if not red['accepted'] or red['tests_sha256']!=hashes:
            raise ValueError('Green requires an accepted Red with identical test files')
        if digest(root/'red.log')!=red['log_sha256']:
            raise ValueError('Red evidence was modified')
    command=[sys.executable,'-m','unittest','discover','-v']
    execute=execute or subprocess.run
    result=execute(command,cwd=root,capture_output=True,text=True,timeout=60)
    output=result.stdout+result.stderr
    log=root/(stage+'.log')
    log.write_text(output)
    import re
    counts=re.findall(r'^Ran (\d+) tests? in ',output,re.M)
    failures=re.findall(r'^FAILED \(failures=(\d+)\)',output,re.M)
    count=int(counts[0]) if len(counts)==1 else 0
    failed=int(failures[0]) if len(failures)==1 else 0
    stable=hashes==check_tests(root)
    accepted=stable and count==6 and ((stage=='red' and result.returncode==1 and failed==4)
        or (stage!='red' and result.returncode==0 and '\nOK' in output))
    record=dict(stage=stage,accepted=accepted,tests_run=count,red_failures=failed,
        returncode=result.returncode,tests_sha256=hashes,score_sha256=digest(root/'score.py'),
        log_sha256=digest(log),created_at=time.time(),command=command)
    receipt.write_text(json.dumps(record,indent=2))
    if not accepted:
        raise ValueError('Suite rejected: inspect '+str(log)+'; Red requires 4 assertion failures, Green requires 6 passing tests')
    if stage in ('green','qa'):
        (root/'validation-result.json').write_text(json.dumps(dict(task=root.name,
            stage='scratch-validation',deployment_performed=False,
            regression_sha256=hashes['test_score.py'],tests_run=count,red_failures=red['red_failures'])))
    return record


def record_failure(root,error):
    path=root/'runner-failures.json'
    state=json.loads(path.read_text()) if path.exists() else {}
    key=str(error)
    # Same error with unchanged source is a repeated action, not new evidence.
    fingerprint=hashlib.sha256((key+''.join(digest(p) for p in sorted(root.glob('*.py')))).encode()).hexdigest()
    count=state.get('count',0)+1 if state.get('fingerprint')==fingerprint else 1
    state=dict(error=key,fingerprint=fingerprint,count=count)
    path.write_text(json.dumps(state,indent=2))
    return count


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('stage',choices=['red','green','qa'])
    args=parser.parse_args()
    root=Path.cwd().resolve()
    board=Path('/opt/data/kanban/boards')/os.environ['HERMES_ALLOWED_KANBAN_BOARD']
    if root.parent!=board/'workspaces':
        raise ValueError('Run only from the assigned rehearsal scratch workspace')
    contract=json.loads((board/'validation-contracts.json').read_text())[root.name]
    try:
        print(json.dumps(run(root,args.stage,contract)))
    except (ValueError,FileNotFoundError,subprocess.TimeoutExpired) as exc:
        count=record_failure(root,exc)
        if count>=2:
            # Normal Kanban operation under the worker's identity/permissions.
            # A refusal remains a refusal; no alternate route or escalation.
            result=subprocess.run(['/opt/hermes/.venv/bin/hermes','kanban',
                '--board',board.name,'block',root.name,
                'Diagnóstico técnico obrigatório: duas falhas iguais sem alteração do código. '+str(exc)],
                capture_output=True,text=True,timeout=30)
            print(json.dumps(dict(diagnosis_requested=result.returncode==0,
                detail=(result.stdout+result.stderr)[-1500:])))
        raise

if __name__=='__main__':
    main()
