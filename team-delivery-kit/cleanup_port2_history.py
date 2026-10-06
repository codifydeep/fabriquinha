"""Archive/remove exact retired port2 containers; never prune or delete volumes."""
import concurrent.futures
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time

ROOT=Path(__file__).resolve().parent
CURRENT='delivery-kit-port2-u3-coverage-qa'


def docker(*args,check=True,timeout=30):
    return subprocess.run(['docker',*args],capture_output=True,check=check,timeout=timeout)


def inventory():
    ids=docker('ps','-aq').stdout.decode().split()
    return json.loads(docker('inspect',*ids).stdout) if ids else []


def eligible(c):
    name=c['Name'].lstrip('/');labels=c['Config'].get('Labels') or {}
    if not name.startswith('delivery-kit-port2-') or name==CURRENT or not c['HostConfig']['ReadonlyRootfs']:
        return False
    if labels.get('com.docker.compose.project')=='delivery-kit-port2-tests':
        return c['State']['Status'] in ('created','exited')
    return (labels.get('com.docker.compose.project')=='delivery-kit-port2-homologation'
        and re.fullmatch(r'delivery-kit-port2-(?:testrev[a-f0-9]+-1|filterapi-1|autobrowser-3|browserfix-2)-qa',name) is not None
        and re.fullmatch('[a-f0-9]{40}',labels.get('delivery-kit.source-sha','')) is not None
        and all(m.get('Type')=='tmpfs' or
                (m.get('Type')=='volume' and m.get('Destination')=='/opt/data')
                for m in c.get('Mounts',[])))


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    before=inventory();selected=[c for c in before if eligible(c)]
    print(json.dumps({'selected':len(selected),'names':[c['Name'].lstrip('/') for c in selected],
        'volumes_deleted':0,'images_deleted':0}),flush=True)
    if not args.apply:return
    for broker in ('delivery-kit-port2-execution-broker-1','delivery-kit-eval-execution-broker-1'):
        code='import sqlite3;c=sqlite3.connect("/broker-state/leases.sqlite");print(c.execute("SELECT count(*) FROM leases WHERE status IN (?,?,?,?)",("creating","starting","running","closing")).fetchone()[0]);c.close()'
        if docker('exec',broker,'python','-c',code).stdout.strip()!=b'0':raise ValueError('active worker; cleanup deferred')
    archive=ROOT/'.local-port2/backups'/('retired-containers-'+time.strftime('%Y%m%d-%H%M%S'))
    archive.mkdir(mode=0o700)
    def save(name,data):
        with os.fdopen(os.open(archive/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as f:f.write(data)
    save('inventory.json',json.dumps(before).encode())  # Private; may contain environment credentials.
    def retire(original):
        c=json.loads(docker('inspect',original['Id']).stdout)[0];name=c['Name'].lstrip('/')
        if not eligible(c) or c['Id']!=original['Id']:raise ValueError('target drift')
        log=docker('logs','--timestamps',c['Id'],check=False);save(name+'.log',log.stdout+log.stderr)
        # Selected roots are readonly. Docker diff can hang mounting historical
        # overlay roots; persistent mounts are retained and live tmpfs DBs saved.
        save(name+'.readonly-root.json',json.dumps({'readonly':True,'image':c['Image'],
            'mounts_retained':True,'root_diff_not_required':True}).encode())
        if c['State']['Running']:
            if 'FEEDBACK_DB_PATH=/tmp/feedback.db' not in c['Config'].get('Env',[]):raise ValueError('unexpected historical database scope')
            code='import sqlite3,sys,pathlib;s=sqlite3.connect("file:/tmp/feedback.db?mode=ro",uri=True);d=sqlite3.connect("/tmp/retired-backup.sqlite");s.backup(d);d.close();s.close();sys.stdout.buffer.write(pathlib.Path("/tmp/retired-backup.sqlite").read_bytes())'
            save(name+'.sqlite',docker('exec',c['Id'],'python','-c',code).stdout)
            with sqlite3.connect(archive/(name+'.sqlite')) as db:
                if db.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('database archive invalid')
            try:docker('stop','--time','3',c['Id'])
            except subprocess.TimeoutExpired:pass
            current=json.loads(docker('inspect',c['Id']).stdout)[0]
            if current['State']['Running']:raise ValueError('stop still pending; no removal')
        try:docker('rm',c['Id'])
        except subprocess.TimeoutExpired:pass  # Observe only; never repeat uncertain removal.
        return c['Id']
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        attempted=list(pool.map(retire,selected))
    deadline=time.monotonic()+90
    while True:
        after=inventory();pending=[c['Id'] for c in after if c['Id'] in attempted]
        if not pending or time.monotonic()>deadline:break
        time.sleep(2)
    chosen=set(attempted)
    preserved={c['Id']:(c['Image'],c['State']['Status']) for c in before if c['Id'] not in chosen}
    actual={c['Id']:(c['Image'],c['State']['Status']) for c in after}
    if any(actual.get(k)!=v for k,v in preserved.items()):raise ValueError('unrelated container changed')
    result=dict(removed=len(attempted)-len(pending),pending=pending,archive=str(archive),
        other_containers_unchanged=True,volumes_deleted=0,images_deleted=0)
    save('result.json',json.dumps(result).encode());print(json.dumps(result),flush=True)
    if pending:raise ValueError('deletions pending; inspect instead of repeating')


if __name__=='__main__':main()
