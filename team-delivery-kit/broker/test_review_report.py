"""Controller-only read-only comparison and durable report, bound to both Reds."""
import json
import time
import uuid


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS test_review_reports('
                'issue_id TEXT, manifest_sha256 TEXT, body TEXT, PRIMARY KEY(issue_id,manifest_sha256))')


def load(broker, issue, digest):
    with broker.db() as con:
        initialize(con)
        row = con.execute('SELECT body FROM test_review_reports WHERE issue_id=? AND manifest_sha256=?',
                          (issue, digest)).fetchone()
    if not row:
        raise ValueError('durable comparison missing')
    return json.loads(row[0])


def create(broker, issue, red, previous):
    digest = red['red']['manifest_sha256']
    with broker.db() as con:
        initialize(con)
        row = con.execute('SELECT body FROM test_review_reports WHERE issue_id=? AND manifest_sha256=?',
                          (issue, digest)).fetchone()
    if row:
        report = json.loads(row[0])
        if report['summary']['previous_manifest'] != (previous['red']['manifest_sha256'] if previous else None):
            raise ValueError('comparison previous identity drift')
        return report['summary']
    selection = {}; mounts = []
    for tree, receipt in (('candidate', red), ('previous', previous)):
        if receipt is None:
            continue
        actual = broker.docker('GET', '/volumes/' + receipt['volume'])
        labels = actual.get('Labels', {}) if actual else {}
        if (labels.get('delivery-kit.owner') != broker.OWNER
                or labels.get('delivery-kit.test-first-task') != receipt['task_id']):
            raise ValueError('comparison snapshot ownership drift')
        selection[tree] = {key: receipt['red'][key] for key in ('manifest_sha256', 'test_sha256')}
        mounts.append({'Type': 'volume', 'Source': receipt['volume'], 'Target': '/' + tree, 'ReadOnly': True})
    if previous and set(selection['candidate']['test_sha256']) != set(selection['previous']['test_sha256']):
        raise ValueError('comparison test scope drift')
    job = broker.PREFIX + '-test-facts-' + uuid.uuid4().hex[:12]
    own = {'delivery-kit.owner': broker.OWNER, 'delivery-kit.test-facts-task': red['task_id']}
    broker.docker('POST', '/containers/create?name=' + job, {
        'Image': broker.IMAGE, 'User': '10000:10000', 'Entrypoint': ['python'],
        'Cmd': ['/test_review_facts.py'], 'NetworkDisabled': True,
        'Env': ['COMPARISON_SELECTION=' + json.dumps(selection)], 'Labels': own,
        'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'none', 'CapDrop': ['ALL'],
            'SecurityOpt': ['no-new-privileges'], 'Memory': 134217728, 'PidsLimit': 16, 'Mounts': mounts}})
    try:
        broker.docker('POST', '/containers/' + job + '/start')
        deadline = time.time() + 20
        while time.time() < deadline:
            state = broker.docker('GET', '/containers/' + job + '/json')['State']
            if not state['Running']:
                if state['ExitCode']:
                    raise ValueError('fixed test comparison rejected')
                report = json.loads(broker.docker_stdout(job, limit=262144))
                if (report['summary']['candidate_manifest'] != digest
                        or report['summary']['previous_manifest'] != (previous['red']['manifest_sha256'] if previous else None)):
                    raise ValueError('comparison snapshot drift')
                with broker.db() as con:
                    initialize(con)
                    encoded = json.dumps(report, sort_keys=True)
                    old = con.execute('SELECT body FROM test_review_reports WHERE issue_id=? AND manifest_sha256=?',
                                      (issue, digest)).fetchone()
                    if old and old[0] != encoded:
                        raise ValueError('comparison report drift')
                    con.execute('INSERT OR IGNORE INTO test_review_reports VALUES (?,?,?)', (issue, digest, encoded))
                return report['summary']
            time.sleep(.2)
        raise ValueError('comparison deadline')
    finally:
        actual = broker.docker('GET', '/containers/' + job + '/json')
        if actual:
            if any(actual['Config'].get('Labels', {}).get(k) != v for k, v in own.items()):
                raise ValueError('comparison cleanup ownership drift')
            broker.docker('DELETE', '/containers/' + actual['Id'] + '?force=true')
