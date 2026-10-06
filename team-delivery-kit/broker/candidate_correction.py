"""Controller-only, bounded return of a failed pre-PR candidate to its author."""
import json
import re
import time

try:
    import handoffs
except ImportError:
    from broker import handoffs


def register(broker, payload):
    keys = {'issue_id', 'source_task', 'manifest_sha256', 'incident_key', 'finding'}
    if (not isinstance(payload, dict) or set(payload) != keys
            or not re.fullmatch(r'[a-f0-9]{16}', payload['incident_key'])
            or not isinstance(payload['finding'], str)
            or not 1 <= len(payload['finding']) <= 2500):
        raise ValueError('invalid candidate correction')
    with broker.LOCK, broker.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS candidate_corrections('
                    'incident_key TEXT PRIMARY KEY, payload TEXT)')
        old = con.execute('SELECT payload FROM candidate_corrections WHERE incident_key=?',
                          (payload['incident_key'],)).fetchone()
        encoded = json.dumps(payload, sort_keys=True)
        if old:
            if old[0] != encoded:
                raise ValueError('candidate correction identity drift')
            return {'status': 'registered', 'incident_key': payload['incident_key']}
        row = handoffs.load(con, payload['source_task'])
        if not row or row['issue_id'] != payload['issue_id'] or row['stage'] != 'approved':
            raise ValueError('candidate correction requires exact approved source')
        data = json.loads(row['data'])
        if data['evidence']['manifest_sha256'] != payload['manifest_sha256']:
            raise ValueError('candidate correction snapshot drift')
        if con.execute('SELECT 1 FROM candidate_corrections WHERE json_extract(payload,\'$.issue_id\')=?',
                       (payload['issue_id'],)).fetchone():
            raise ValueError('candidate correction already attempted; technical replanning required')
        config = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                        (payload['issue_id'],)).fetchone()[0])
        if not con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',
                           (payload['issue_id'],)).fetchone():
            raise ValueError('candidate correction requires preserved controller Red')
        data.update(finding=payload['finding'], candidate_incident=payload['incident_key'],
                    trigger_task=payload['source_task'])
        now, body = time.time(), json.dumps(data, sort_keys=True)
        con.execute('UPDATE delivery_handoffs SET stage=?,owner=?,data=?,updated=? WHERE source_task=?',
                    ('correct_author', config['author'], body, now, payload['source_task']))
        con.execute('INSERT INTO delivery_handoff_events(source_task,stage,data,at) VALUES (?,?,?,?)',
                    (payload['source_task'], 'correct_author', body, now))
        config['enabled'] = True
        con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',
                    (json.dumps(config, sort_keys=True), payload['issue_id']))
        con.execute('INSERT INTO candidate_corrections VALUES (?,?)',
                    (payload['incident_key'], encoded))
    return {'status': 'registered', 'incident_key': payload['incident_key']}
