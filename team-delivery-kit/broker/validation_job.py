"""Durable fixed validation jobs; cleanup cannot invalidate a captured result."""
import json
import time
import uuid
from docker_grouping import grouped_create
try:
    from test_first_job import digest, verify
except ImportError:
    from broker.test_first_job import digest, verify


class Pending(TimeoutError):
    """Observation of the same execution is required, not another attempt."""


def run(b, task, kind, payload, *, now=None):
    if str(uuid.UUID(task)) != task or kind not in ('structure', 'suite', 'green'):
        raise ValueError('fixed validation identity required')
    now = time.time() if now is None else now
    payload = grouped_create('POST', '/containers/create?name=validation', payload, b.PREFIX)
    key = digest(dict(task=task, kind=kind, payload=payload))
    name = b.PREFIX + '-validation-job-' + task + '-' + key[:12]
    expected = {**payload, 'Labels': {**payload['Labels'],
        'delivery-kit.owner': b.OWNER, 'delivery-kit.source-task': task,
        'delivery-kit.validation-job': key}}
    identity = dict(task=task, kind=kind, name=name, payload=expected)
    with b.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS validation_jobs('
                    'job_key TEXT PRIMARY KEY,identity TEXT,state TEXT)')
        row = con.execute('SELECT identity,state FROM validation_jobs WHERE job_key=?', (key,)).fetchone()
        if row:
            if json.loads(row[0]) != identity: raise ValueError('immutable validation job drift')
            state = json.loads(row[1])
            if state['stage'] == 'complete': return state['result']
            if state['stage'] == 'blocked': raise ValueError('validation observation blocked; preserve handle')
        else:
            if b.docker('GET', '/containers/' + name + '/json'):
                raise ValueError('unregistered validation job')
            state = dict(stage='prepared', deadline=now+600, approval=False)
            con.execute('INSERT INTO validation_jobs VALUES(?,?,?)',
                        (key, json.dumps(identity, sort_keys=True), json.dumps(state, sort_keys=True)))
    def save(**values):
        state.update(values)
        with b.db() as con:
            con.execute('UPDATE validation_jobs SET state=? WHERE job_key=?',
                        (json.dumps(state, sort_keys=True), key))
    if now >= state['deadline']:
        save(stage='blocked', category='observation_deadline')
        raise ValueError('validation observation deadline; preserve exact handle')
    try:
        if state['stage'] == 'prepared':
            save(stage='create_intent')
            b.docker('POST', '/containers/create?name=' + name, expected)
        info = b.docker('GET', '/containers/' + name + '/json')
        if not info: raise Pending('observe validation create; no repeated POST')
        verify(b, info, expected)
        if state['stage'] == 'create_intent': save(stage='created', container_id=info['Id'])
        if info['Id'] != state['container_id']: raise ValueError('validation container identity drift')
        if state['stage'] == 'created':
            if info['State']['Status'] != 'created': raise ValueError('validation start state drift')
            save(stage='start_intent')
            b.docker('POST', '/containers/' + info['Id'] + '/start')
            info = b.docker('GET', '/containers/' + info['Id'] + '/json')
            if not info: raise Pending('observe validation start')
            verify(b, info, expected)
        if info['State']['Status'] != 'exited': raise Pending('validation running; observe same handle')
        output = b.docker_stdout(info['Id'], include_stderr=kind=='suite', limit=65536)
    except TimeoutError as error:
        raise Pending('validation pending: ' + str(error)) from error
    result = dict(container_id=info['Id'], exit_code=info['State']['ExitCode'],
                  output=output, output_sha256=__import__('hashlib').sha256(output.encode()).hexdigest(),
                  validation_job_key=key,validation_contract_sha256=digest(identity),approval=False)
    save(stage='complete', result=result)
    try:
        try: import helper_cleanup
        except ImportError: from broker import helper_cleanup
        helper_cleanup.schedule(b, name, task)
    except Exception:
        save(cleanup_pending=True)
    return result
