"""Real read-only publication preflight and evidence-based permission recovery."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time


def container_command(controller,task,preflight=False):
    if not re.fullmatch(r't_[a-z0-9]+',task): raise ValueError('invalid task identity')
    return ['docker','run','--rm','--read-only','--cap-drop=ALL','--cap-add=DAC_READ_SEARCH',
        '--security-opt=no-new-privileges','--pids-limit=64','--memory=256m','--cpus=0.5',
        '--tmpfs','/tmp:rw,nosuid,size=32m','--network=none' if preflight else '--network=bridge',
        '--name','truco-online-ci-'+('access-' if preflight else 'publication-')+task,
        '--label','com.codifydeep.project=truco-online','--label','com.codifydeep.environment=ci',
        '--label','com.codifydeep.kanban='+task,
        '-v','truco-online-hermes-data:/opt/data:ro','-v',controller.volume+':/deliveries:ro',
        '--entrypoint','/opt/hermes/.venv/bin/python',controller.image,
        '/opt/hermes/publication_merge.py','--task',task]


def check_access(task):
    import publication_merge as publication
    from immutable_delivery import DeliveryStore
    from pr_review_packet import load, packet_path
    files=[]; permissions=[]
    def read(path):
        raw=path.read_bytes(); files.append(str(path))
        stat=path.stat(); permissions.append([str(path),stat.st_uid,stat.st_gid,stat.st_mode & 0o777])
        return raw
    state=json.loads(read(publication.EXECUTION))
    config=json.loads(read(publication.ROOT/'planning-config.json'))
    assert state['attempt']==config['attempt']==publication.ATTEMPT
    assert config==json.loads(read(publication.BOARD/'planning.json'))
    card=config['cards'][task]
    publication.authority(card)
    for path in [publication.BOARD/'kanban.db',publication.ROOT/'controller.db']:
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
            db.execute('SELECT count(*) FROM sqlite_master').fetchone()
        files.append(str(path))
    load(publication.ROOT,card); read(packet_path(publication.ROOT,card))
    with sqlite3.connect((publication.ROOT/'controller.db').as_uri()+'?mode=ro',uri=True) as db:
        publication.planning_provenance(load(publication.ROOT,card),card,db)
        row=db.execute('SELECT revision FROM deliveries WHERE task=? ORDER BY run DESC LIMIT 1',(task,)).fetchone()
    assert row, 'delivery required'
    store=DeliveryStore(publication.ROOT); store.load(state['attempt'],task,row[0])
    directory=store.path(state['attempt'],task,row[0])
    for path in [directory/'manifest.json',directory/'files/PLAN.md',directory/'files/PR-PACKET.json']:
        read(path)
    # Prove credentials can be read; never return bytes or credential digests.
    read(Path('/opt/data/home/.config/gh/hosts.yml'))
    optional=Path('/opt/data/home/.config/gh/config.yml')
    if optional.exists(): read(optional)
    return dict(passed=True,task=task,revision=row[0],policy='read-only-dac-search-v1',
                files=files,permissions=permissions,scope='local_access_only_no_merge')


def preflight(controller,task):
    from review_controller import bounded_run
    command=container_command(controller,task,True)+['--preflight']
    result=bounded_run(command,timeout=45,limit=65536)
    if result.returncode:
        proof=dict(passed=False,error=result.stdout[-4000:],policy='read-only-dac-search-v1',files=[])
    else: proof=json.loads(result.stdout)
    if proof.get('passed'):
        remote=bounded_run(container_command(controller,task)+['--policy-preflight'],timeout=85,limit=65536)
        proof['remote_policy']=json.loads(remote.stdout) if not remote.returncode else dict(passed=False,error=remote.stdout[-4000:])
        proof['passed']=bool(proof['remote_policy'].get('passed'))
        if not proof['passed']: proof['error']=proof['remote_policy'].get('error','policy preflight failed')
    proof['image']=controller.image
    proof['fingerprint']=hashlib.sha256(json.dumps(proof,sort_keys=True).encode()).hexdigest()
    controller.db.execute('CREATE TABLE IF NOT EXISTS publication_preflights(task TEXT,fingerprint TEXT,proof TEXT,created REAL)')
    controller.db.execute('INSERT INTO publication_preflights VALUES(?,?,?,?)',(task,proof['fingerprint'],json.dumps(proof),time.time()))
    controller.db.commit()
    return proof


def record_failure(controller,task,run,revision,error,proof):
    controller.db.execute('CREATE TABLE IF NOT EXISTS publication_failures(task TEXT,run INTEGER,revision TEXT,error TEXT,preflight_fingerprint TEXT,created REAL)')
    controller.db.execute('INSERT INTO publication_failures VALUES(?,?,?,?,?,?)',
        (task,run,revision,str(error)[-4000:],proof.get('fingerprint'),time.time()))
    controller.db.commit()


def recovery_evidence(db,task,last_error,block,proof):
    previous=None
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='publication_failures'").fetchone():
        previous=db.execute('SELECT error,preflight_fingerprint FROM publication_failures WHERE task=? ORDER BY run DESC LIMIT 1',(task,)).fetchone()
    payload=json.loads(block['payload'] or '{}') if block else {}
    error=(previous['error'] if previous else None) or last_error or payload.get('reason') or payload.get('error')
    denied=bool(error and ('PermissionError' in error or 'Errno 13' in error))
    paths=re.findall(r'/(?:opt/data|deliveries)/[A-Za-z0-9_./-]+',error or '')
    covered=bool(paths and all(p in proof.get('files',[]) for p in paths))
    unchanged=bool(previous and previous['preflight_fingerprint']==proof.get('fingerprint'))
    policy=bool(error and ('Merge commits are not allowed' in error or 'publication_policy_conflict' in error))
    if policy:
        retry=bool(proof.get('passed') and proof.get('remote_policy',{}).get('passed') and not unchanged)
        return dict(last_error=error,category='publication_policy_conflict',can_retry=retry,
            preflight_passed=bool(proof.get('passed')),preflight_fingerprint=proof.get('fingerprint'),
            failed_paths=[],paths_tested=False,identical_evidence=unchanged,
            next_action='resume_after_verified_policy_repair' if retry else 'technical_operator_diagnosis_required')
    return dict(last_error=error,category='publication_access_denied' if denied else 'publication_execution_failure',
        can_retry=bool(denied and proof.get('passed') and covered and not unchanged),
        preflight_passed=bool(proof.get('passed')),preflight_fingerprint=proof.get('fingerprint'),
        failed_paths=paths,paths_tested=covered,identical_evidence=unchanged,
        next_action='resume_after_verified_access_repair' if denied and proof.get('passed') and covered and not unchanged
                    else 'technical_operator_diagnosis_required')
