"""Publish exact already-reviewed U1/U2 checkpoint, separately from U3 coverage.

No merge, deployment, release completion or historical receipt rewrite.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import publish_u3_coverage as common
from broker.maintenance_snapshot_validate import manifest
from broker.incremental_checkpoints import digest as checkpoint_digest
from release_eval import save_receipt

BRANCH = 'codex/u3-reviewed-predecessors'
CODE = {'app/static/app.js', 'app/static/index.html'}
TESTS = {'tests/test_feedback_search_client.py', 'tests/test_incremental_u2.py'}
RECEIPT = common.ROOT / '.local-port2/release-receipts/U3-PREDECESSORS.json'


def load_bundle():
    script = '''import broker as b,json,u3_coverage_integration as i,incremental_evidence as e,incremental_checkpoints as l,native
with b.LOCK,b.db() as con:
 c,s=i.saved(b)
 if s['stage']!='integration_review_approved':raise ValueError('current U3 preintegration required')
 cfg,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(c['contract']['root'],)).fetchone())
 settings=json.loads((b.STATE/'native.json').read_text());proofs=[]
 for name in ('U1','U2'):
  u=state['units'][name]
  if u['stage']!='checkpointed':raise ValueError('approved predecessor required')
  issue=u['binding']['issue_id'];source=u['delivery_source_task'];review=u['delivery_review_task']
  g=e.green(con,cfg,u,issue,source,review);r=e.delivery_review(con,cfg,u,issue,source,review)
  if l.digest(g)!=u['green'] or l.digest(r)!=u['delivery_review'] or r['decision']!='approve':raise ValueError('current checkpoint evidence drift')
  for task,agent in ((source,cfg['policy']['author']),(review,cfg['policy']['delivery_reviewer'])):
   record=native.task_record(settings,task,agent)
   if record.get('status')!='completed' or record.get('issue_id')!=issue:raise ValueError('exact native checkpoint executions required')
  proofs.append(dict(unit=name,green=g,review=r,red_receipt_sha256=u['red'],test_review_receipt_sha256=u['test_review']))
 if proofs[1]['green']['base_manifest_sha256']!=proofs[0]['green']['manifest_sha256']:raise ValueError('ordered checkpoint chain required')
 source=state['units']['U2']['delivery_source_task'];volume=con.execute('SELECT volume FROM snapshots WHERE task_id=? AND status="complete"',(source,)).fetchone()[0]
 i.controls.owned(b,dict(volume=volume),source)
 print(json.dumps(dict(schema='u3-predecessor-publication-input-v1',root=c['contract']['root'],base_sha=c['contract']['base_sha'],
  source_task=source,volume=volume,manifest_sha256=proofs[-1]['green']['manifest_sha256'],proofs=proofs,
  author=cfg['policy']['author'],reviewer=cfg['policy']['delivery_reviewer'])))
'''
    return json.loads(common.run('docker', 'exec', '-e', 'PYTHONPATH=/', common.PROJECT + '-execution-broker-1', 'python', '-c', script))


def preflight(repo, bundle, snapshot):
    if (bundle.get('schema') != 'u3-predecessor-publication-input-v1'
            or bundle.get('author') == bundle.get('reviewer')
            or [p['unit'] for p in bundle.get('proofs', [])] != ['U1', 'U2']):
        raise ValueError('ordered independent checkpoint publication required')
    raw, metadata = manifest(snapshot)
    if hashlib.sha256(raw).hexdigest() != bundle['manifest_sha256']:
        raise ValueError('exact U2 immutable snapshot required')
    old = common.tracked(repo, bundle['base_sha'])
    if set(metadata)-set(old) != TESTS or TESTS & set(old):
        raise ValueError('only U1/U2 new tests permitted')
    content = {name: (Path(snapshot)/name).read_bytes() for name in metadata}
    for name in old.keys() & content.keys():
        if name not in CODE and common.git(repo, 'cat-file', 'blob', old[name][1]) != content[name]:
            raise ValueError('protected predecessor Git file changed: ' + name)
    for index, proof in enumerate(bundle['proofs']):
        green, review = proof['green'], proof['review']
        if (green.get('exit_code') != 0 or green.get('full_suite') is not True
                or green.get('author') != bundle['author'] or green.get('test_count') != (249,255)[index]
                or review.get('reviewer') != bundle['reviewer'] or review.get('decision') != 'approve'
                or review.get('manifest_sha256') != green.get('manifest_sha256')
                or review.get('green_receipt_sha256') != checkpoint_digest(green)):
            raise ValueError('qualified independent full-suite checkpoint required')
        for name, digest in green['test_sha256'].items():
            if name not in metadata or metadata[name]['sha256'] != digest:
                raise ValueError('approved predecessor test hash drift')
    if (bundle['proofs'][-1]['green']['manifest_sha256'] != bundle['manifest_sha256']
            or bundle['proofs'][1]['green']['base_manifest_sha256'] != bundle['proofs'][0]['green']['manifest_sha256']):
        raise ValueError('exact predecessor manifest chain required')
    return content


def verify_commit(repo, head, base, content):
    before = common.tracked(repo,base);after = common.tracked(repo,head)
    if common.git(repo,'rev-parse',head+'^').decode().strip()!=base or set(after)!=set(before)|TESTS:
        raise ValueError('exact predecessor Git parent and tree required')
    changes = common.git(repo,'diff','--name-status',base,head).decode().splitlines()
    if (set('A\t'+p for p in TESTS)-set(changes)
            or not set(changes)<={*( 'A\t'+p for p in TESTS),*( 'M\t'+p for p in CODE)}):
        raise ValueError('undeclared predecessor Git delta')
    for name,(mode,blob) in after.items():
        if mode != (before[name][0] if name in before else '100644'):
            raise ValueError('predecessor mode drift')
        if name not in CODE|TESTS and blob != before[name][1]:
            raise ValueError('previous test or protected file changed')
        if name in content and common.git(repo,'cat-file','blob',blob)!=content[name]:
            raise ValueError('predecessor commit differs from approved snapshot')


def ensure_commit(repo,base,content):
    ref='refs/heads/'+BRANCH
    existing=subprocess.run(['git','-C',str(repo),'rev-parse','--verify',ref],capture_output=True,text=True)
    if existing.returncode==0:
        head=existing.stdout.strip()
    else:
        remote=common.git(repo,'ls-remote','origin',ref).decode().strip()
        if remote:
            head=remote.split()[0];common.git(repo,'fetch','origin',head)
        else:
            with tempfile.TemporaryDirectory(prefix='u3-predecessor-index-') as tmp:
                env={**os.environ,'GIT_INDEX_FILE':str(Path(tmp)/'index')};common.git(repo,'read-tree',base,env=env)
                for name in sorted(CODE|TESTS):
                    blob=common.git(repo,'hash-object','-w','--stdin',data=content[name]).decode().strip()
                    mode=common.tracked(repo,base).get(name,('100644',None))[0]
                    common.git(repo,'update-index','--add','--cacheinfo',mode+','+blob+','+name,env=env)
                tree=common.git(repo,'write-tree',env=env).decode().strip()
            head=common.git(repo,'commit-tree',tree,'-p',base,'-m','U1/U2: integrate reviewed immutable search checkpoints').decode().strip()
        verify_commit(repo,head,base,content);common.git(repo,'update-ref',ref,head,'0'*40)
    verify_commit(repo,head,base,content)
    return head


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--publish',action='store_true');args=parser.parse_args()
    bundle=load_bundle();base=bundle['base_sha']
    if common.remote_base(common.REPO)!=base:raise ValueError('original main moved')
    with tempfile.TemporaryDirectory(prefix='u3-predecessor-snapshot-') as tmp:
        snapshot=Path(tmp);common.export_snapshot(bundle,snapshot);content=preflight(common.REPO,bundle,snapshot)
        if not args.publish:
            print(json.dumps(dict(stage='preflight_passed',manifest_sha256=bundle['manifest_sha256'])));return
        head=ensure_commit(common.REPO,base,content)
        receipt=dict(schema='u3-predecessor-pr-v1',stage='committed',repository=common.REPOSITORY,
            branch=BRANCH,base_sha=base,head_sha=head,manifest_sha256=bundle['manifest_sha256'],
            source_task=bundle['source_task'],proof_sha256=common.digest(bundle['proofs']),
            merge_authorized=False,deploy_authorized=False,delivery_approval=False)
        save_receipt(RECEIPT,receipt)
        if common.remote_base(common.REPO)!=base or load_bundle()!=bundle:raise ValueError('checkpoint drift before push')
        common.git(common.REPO,'push','origin',head+':refs/heads/'+BRANCH)
        def prs():return json.loads(common.run('gh','pr','list','-R',common.REPOSITORY,'--state','all','--head',BRANCH,
            '--json','number,state,headRefOid,baseRefOid,url'))
        found=prs()
        if not found:
            body=('Separate integration of already independently reviewed U1/U2 checkpoints, before U3 coverage.\n'
                'Root: '+bundle['root']+'\nFrozen U2 manifest: '+bundle['manifest_sha256']+'\n'
                + '\n'.join(p['unit']+': source '+p['green']['task_id']+', review '+p['review']['task_id']+
                            ', full suite '+str(p['green']['test_count']) for p in bundle['proofs'])
                +'\nOnly app.js/index.html and two new tests. Every previous test and workflow preserved. '
                'No U3 completion, historical evidence rewrite, merge, deployment or homologation. Exact CI remains required.')
            common.run('gh','pr','create','-R',common.REPOSITORY,'--base','main','--head',BRANCH,
                '--title','U1/U2: integrate independently reviewed search checkpoints','--body',body);found=prs()
        if len(found)!=1 or found[0]['state']!='OPEN' or found[0]['headRefOid']!=head or found[0]['baseRefOid']!=base:
            raise ValueError('exact open predecessor PR required')
        receipt.update(stage='pr_open',pr_number=found[0]['number'],pr_url=found[0]['url']);save_receipt(RECEIPT,receipt)
        print(json.dumps(receipt))


if __name__=='__main__':main()
