"""Remove only retired owned image tags; preserve external projects and inputs."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT=Path(__file__).resolve().parent


def docker(*args,check=True):
    return subprocess.run(['docker',*args],check=check,text=True,capture_output=True)


def owned(repository):
    return repository.rsplit('/',1)[-1].startswith(('delivery-kit-','estudo-hermes','truco-'))


def protected_tag(tag):return tag.split(':')[0].rsplit('/',1)[-1].startswith('toso-')


def containers():
    ids=docker('ps','-aq').stdout.split()
    return json.loads(docker('inspect',*ids).stdout) if ids else []


def references():
    refs=set()
    paths=list(ROOT.glob('*.py'))+list(ROOT.glob('*.yaml'))+list(ROOT.glob('Dockerfile*'))
    paths+=list((ROOT/'broker').rglob('*.py'))
    paths+=list((ROOT.parent/'bootstrap/infra').rglob('*.yaml'))
    paths+=list((ROOT.parent/'bootstrap/infra').rglob('Dockerfile*'))
    pattern=r'(?:sha256:[a-f0-9]{64}|[a-zA-Z0-9][a-zA-Z0-9./_-]*(?:@sha256:[a-f0-9]{64}|:[a-zA-Z0-9_.-]+))'
    for path in paths:
        if path.is_file() and not path.is_symlink():refs.update(re.findall(pattern,path.read_text(errors='replace')))
    return refs


def select(rows,used,refs):
    groups={};repositories={}
    for row in rows:
        key=row['ID'];tag=row['Repository']+':'+row['Tag']
        groups.setdefault(key,[]).append(row)
        repositories.setdefault(row['Repository'],[]).append(key)
    # Preserve two newest immutable versions per owned family for rollback.
    recent={i for repo,ids in repositories.items() if owned(repo) for i in list(dict.fromkeys(ids))[:2]}
    selected=[]
    for key,aliases in groups.items():
        if key in used or key in refs or key in recent:continue
        if any(not owned(r['Repository']) or r['Tag']=='<none>' for r in aliases):continue
        tags=[r['Repository']+':'+r['Tag'] for r in aliases]
        if any(protected_tag(t) or t in refs for t in tags):continue
        selected.append({'id':key,'tags':tags})
    return selected


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    rows=[json.loads(line) for line in docker('image','ls','--no-trunc','--format','{{json .}}').stdout.splitlines()]
    before=containers();used={c['Image'] for c in before};refs=references()
    # Resolve Docker content/config digests independently of local image IDs.
    ids=list(dict.fromkeys(r['ID'] for r in rows));metadata=[]
    for start in range(0,len(ids),50):metadata.extend(json.loads(docker('image','inspect',*ids[start:start+50]).stdout))
    for image in metadata:
        aliases=set(image.get('RepoTags') or [])|set(image.get('RepoDigests') or [])
        if aliases&refs or image['Id'] in refs:used.add(image['Id'])
    selected=select(rows,used,refs)
    print(json.dumps({'image_ids':len(selected),'tags':sum(len(s['tags']) for s in selected),
        'toso_preserved':True,'dangling_and_external_preserved':True,'first_tags':[s['tags'][0] for s in selected[:8]]}),flush=True)
    if not args.apply:return
    archive=ROOT/'.local-port2/backups'/('image-cleanup-'+time.strftime('%Y%m%d-%H%M%S'));archive.mkdir(mode=0o700)
    def save(name,value):
        with os.fdopen(os.open(archive/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as f:json.dump(value,f)
    save('plan.json',selected);save('image-metadata.json',metadata)
    original_protected={i['Id']:sorted(i.get('RepoTags') or []) for i in metadata
        if any(protected_tag(t) for t in i.get('RepoTags') or [])}
    removed=[];conflicts=[]
    for start in range(0,len(selected),12):
        current_used={c['Image'] for c in containers()};batch=[]
        targets=selected[start:start+12]
        probe=docker('image','inspect',*(t['id'] for t in targets),check=False)
        observed={image['Id']:image for image in json.loads(probe.stdout or '[]')}
        for target in targets:
            image=observed.get(target['id'])
            if image is None:continue
            tags=image.get('RepoTags') or []
            if (image['Id'] in current_used or set(tags)!=set(target['tags']) or
                    any(protected_tag(t) or not owned(t.split(':')[0]) for t in tags)):
                conflicts.append(target['id']);continue
            batch.append(target['tags'])
        if batch:
            def retire(tags):return tags,docker('image','rm','--no-prune',*tags,check=False)
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                for tags,result in pool.map(retire,batch):
                    removed.extend(line[len('Untagged: '):] for line in result.stdout.splitlines() if line.startswith('Untagged: '))
                    if result.returncode:conflicts.append({'tags':tags,'error':'removal conflict; preserved, no force'})
        print(json.dumps({'processed':min(start+12,len(selected)),'tags_removed':len(removed)}),flush=True)
    for key,tags in original_protected.items():
        actual=json.loads(docker('image','inspect',key).stdout)[0]
        if sorted(actual.get('RepoTags') or [])!=tags:raise ValueError('protected toso image changed')
    after=containers();actual={c['Id']:(c['Image'],c['State']['Status']) for c in after}
    if any(actual.get(c['Id'])!=(c['Image'],c['State']['Status']) for c in before):
        raise ValueError('container changed during image cleanup')
    remaining=set(docker('image','ls','-q','--no-trunc').stdout.split())
    result=dict(tags_removed=len(removed),image_ids_removed=sum(s['id'] not in remaining for s in selected),
        conflicts=conflicts,toso_unchanged=True,
        containers_unchanged=True,volumes_deleted=0,archive=str(archive))
    save('result.json',result);print(json.dumps(result),flush=True)


if __name__=='__main__':main()
