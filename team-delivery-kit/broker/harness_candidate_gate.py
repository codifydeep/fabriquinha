"""Controller-owned, fixed offline admission gate for experiment repairs."""
import json
import time
try:
    import incremental_checkpoints as ledger
    from harness_candidate_probe import validate_reports, validate_internal_negatives, TEST
    from incremental_harness_replan import validate_experiment
except ImportError:
    from broker import incremental_checkpoints as ledger
    from broker.harness_candidate_probe import validate_reports, validate_internal_negatives, TEST
    from broker.incremental_harness_replan import validate_experiment


def qualify(receipt, red, experiment):
    validate_experiment(experiment, experiment['input_sha256'])
    if (receipt.get('operation') != 'actual_candidate_selector_controls_v2'
            or receipt.get('repository_modified') is not False or receipt.get('delivery_approval') is not False
            or receipt.get('candidate_manifest_sha256') != red['red']['manifest_sha256']
            or receipt.get('candidate_sha256', {}).get(TEST) != red['red']['test_sha256'][TEST]
            or receipt.get('fixture_manifest_sha256') != experiment['manifest_sha256']
            or receipt.get('fixture_sha256') != experiment['input_sha256']):
        raise ValueError('same immutable candidate and experiment required')
    validate_reports(receipt['reports'])
    validate_internal_negatives(receipt.get('internal_negatives'))


def enforce(b, trial, red):
    experiment = trial.get('harness_selector_experiment')
    if not experiment:
        return
    with b.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS harness_candidate_checks_v2('
                    'issue_id TEXT,manifest_sha256 TEXT,receipt TEXT,PRIMARY KEY(issue_id,manifest_sha256))')
        key = (trial['issue_id'], red['red']['manifest_sha256'])
        old = con.execute('SELECT receipt FROM harness_candidate_checks_v2 WHERE issue_id=? AND manifest_sha256=?', key).fetchone()
    if old:
        qualify(json.loads(old[0]), red, experiment)
        return
    fixture = trial['harness_fixture_volume']
    candidate = red['volume']
    for volume in (fixture, candidate):
        info = b.docker('GET', '/volumes/'+volume)
        if not info or info.get('Labels', {}).get('delivery-kit.owner') != b.OWNER:
            raise ValueError('owned immutable candidate volumes required')
    name = b.PREFIX+'-harness-check-'+red['task_id']
    labels = {'delivery-kit.owner': b.OWNER, 'delivery-kit.issue-id': trial['issue_id'],
              'com.docker.compose.project': b.PREFIX, 'com.docker.compose.service': 'harness-candidate-check'}
    if b.docker('GET', '/containers/'+name+'/json'):
        raise ValueError('interrupted candidate check requires diagnosis')
    try:
        b.docker('POST', '/containers/create?name='+name, dict(Image=b.OFFLINE_IMAGE,
            User='10000:10000', Entrypoint=['python3'],
            Cmd=['-c', 'import json;from harness_candidate_probe import run;print(json.dumps(run("/candidate","/fixture"),sort_keys=True))'],
            Env=['PYTHONPATH=/', 'PYTHONDONTWRITEBYTECODE=1'], Labels=labels, NetworkDisabled=True,
            HostConfig=dict(ReadonlyRootfs=True, NetworkMode='none', CapDrop=['ALL'],
                SecurityOpt=['no-new-privileges'], Memory=536870912, PidsLimit=128,
                Tmpfs={'/tmp':'rw,noexec,nosuid,size=64m'},
                Mounts=[dict(Type='volume',Source=candidate,Target='/candidate',ReadOnly=True),
                        dict(Type='volume',Source=fixture,Target='/fixture',ReadOnly=True)])))
        b.docker('POST', '/containers/'+name+'/start')
        deadline = time.time()+55
        while time.time()<deadline:
            info = b.docker('GET', '/containers/'+name+'/json')
            if not info['State']['Running']:
                if info['State']['ExitCode'] != 0:
                    raise ValueError('actual candidate harness controls failed')
                receipt = json.loads(b.docker_stdout(name))
                qualify(receipt, red, experiment)
                break
            time.sleep(.1)
        else:
            raise TimeoutError('candidate harness control deadline')
    finally:
        info = b.docker('GET', '/containers/'+name+'/json')
        if info and info['Config'].get('Labels', {}).get('delivery-kit.owner') == b.OWNER:
            b.docker('DELETE', '/containers/'+info['Id']+'?force=true')
    with b.db() as con:
        con.execute('INSERT INTO harness_candidate_checks_v2 VALUES(?,?,?)', (*key,json.dumps(receipt,sort_keys=True)))
