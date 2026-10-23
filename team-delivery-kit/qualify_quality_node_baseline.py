"""Zero-model full Python/Node diagnostic on the real registered Git baseline.

No checkout changes, native enrollment, policy/gate bypass or delivery approval.
Only tracked regular Git blobs enter a new private snapshot and isolated image.
An unfinished operation fences another probe; unknown Docker results are observed
through the exact recorded helper, never replaced just because a client timed out.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid
from portable_contract import safe_path
from quality_delivery_candidate import repository
from quality_git_binding import git
from docker_grouping import args as grouped
from qualify_quality_red_observer import require_idle,save,await_retirement

ROOT=Path(__file__).resolve().parent


def require(value):
    if not value:raise ValueError('baseline probe evidence incomplete; preserve original operation')


def command(args):return subprocess.run(args,capture_output=True,text=True,timeout=180)


def qualify(namespace,repo,expected_repository,image):
    maintenance,idle=require_idle(namespace);repo=repository(Path(repo),expected_repository)
    require(re.fullmatch(r'delivery-kit-quality-node-baseline:[A-Za-z0-9_.-]{1,64}',image))
    info=json.loads(subprocess.check_output(['docker','image','inspect',image],text=True))[0]
    cfg=info['Config'];require(cfg.get('User')=='10000:10000' and not cfg.get('Volumes')
        and cfg.get('Labels',{}).get('delivery-kit.component')=='quality-node-baseline'
        and cfg.get('Entrypoint')==['python','/opt/quality/quality_node_baseline.py'])
    backups=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'
    for prior in backups.glob('quality-node-baseline-*'):
        require(not (prior/'operation.json').exists() or (prior/'result.json').exists())
    sha=git(repo,'rev-parse','HEAD').decode().strip();require(re.fullmatch('[a-f0-9]{40}',sha))
    before=git(repo,'status','--porcelain','--untracked-files=no');require(not before)
    operation=str(uuid.uuid4());archive=backups/('quality-node-baseline-'+operation);archive.mkdir(mode=0o700)
    name=namespace+'-node-baseline-'+operation;tag='delivery-kit-quality-node-probe:'+operation[:8]
    save(archive/'operation.json',dict(operation=operation,namespace=namespace,source_sha=sha,repository=expected_repository,
        source_image=info['Id'],helper=name,fixture_image=tag,maintenance=maintenance,idle=idle,
        model_calls=0,native_qualification=False,delivery_approval=False))
    snapshot=archive/'snapshot';snapshot.mkdir(mode=0o700);facts={}
    rows=git(repo,'ls-tree','-r',sha).decode().splitlines();require(1<=len(rows)<=128)
    for row in rows:
        metadata,path=row.split('\t',1);mode,kind,oid=metadata.split();safe_path(path)
        require(mode in ('100644','100755') and kind=='blob' and path not in ('manifest.json','contract.json'))
        data=git(repo,'cat-file','blob',oid);require(len(data)<=2097152)
        target=snapshot/path;target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        with target.open('xb') as out:out.write(data)
        target.chmod(0o600)
        facts[path]=dict(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
    require(sum(v['bytes'] for v in facts.values())<=16777216)
    tests={p:v['sha256'] for p,v in facts.items() if p.endswith(('.test.js','.spec.js','.test.mjs','.test.cjs'))}
    require(bool(tests))
    manifest=json.dumps(dict(files=facts),sort_keys=True,separators=(',',':')).encode()
    (snapshot/'manifest.json').write_bytes(manifest);(snapshot/'manifest.json').chmod(0o600)
    request=dict(manifest_sha256=hashlib.sha256(manifest).hexdigest(),tests=tests)
    save(archive/'request.json',request)
    (archive/'Dockerfile').write_text('FROM '+image+'\nCOPY --chown=10000:10000 snapshot /snapshot\n')
    argv=['docker','build','--network=none','--pull=false','-t',tag,str(archive)]
    save(archive/'build-intent.json',dict(argv=argv));built=command(argv)
    save(archive/'build-result.json',dict(exit_code=built.returncode,stdout=built.stdout,stderr=built.stderr));require(built.returncode==0)
    actual=json.loads(subprocess.check_output(['docker','image','inspect',image],text=True))[0];require(actual['Id']==info['Id'])
    fixture=json.loads(subprocess.check_output(['docker','image','inspect',tag],text=True))[0]['Id']
    argv=['docker','run','--rm','--name',name,*grouped('quality-node-baseline-probe',namespace),
        '--label','delivery-kit.owner='+namespace+'-quality-node-baseline-probe','--network','none','--read-only',
        '--cap-drop','ALL','--security-opt','no-new-privileges','--user','10000:10000',
        '--pids-limit','128','--memory','256m','--cpus','1','--tmpfs','/tmp:rw,nosuid,nodev,size=32m,mode=1777',
        '--env','QUALITY_NODE_BASELINE_JSON='+json.dumps(request,sort_keys=True),'--entrypoint','python',
        fixture,'/opt/quality/quality_baseline_probe.py']
    save(archive/'run-intent.json',dict(argv=argv));result=command(argv)
    save(archive/'run-result.json',dict(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr))
    await_retirement(name);require(result.returncode==0)
    report=json.loads(result.stdout)
    require(report['operation']=='python_node_baseline_compatibility_v1' and report['manifest_sha256']==request['manifest_sha256']
        and report['node']['tests']==tests and report['snapshot_unchanged'] is True
        and all(report[k] is False for k in ('native_qualification','red_approved','green_approved','execution_authorized','delivery_approval'))
        and report['model_calls']==0)
    require(git(repo,'rev-parse','HEAD').decode().strip()==sha and git(repo,'status','--porcelain','--untracked-files=no')==before)
    final=dict(status=report['status'],source_sha=sha,report=report,archive=str(archive),helper_retired=True,
        product_checkout_unchanged=True,model_calls=0,native_qualification=False,delivery_approval=False)
    save(archive/'result.json',final);return final


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('namespace','repository','expected-repository','image'):parser.add_argument('--'+key,required=True)
    args=parser.parse_args()
    print(json.dumps(qualify(args.namespace,args.repository,args.expected_repository,args.image),sort_keys=True))
