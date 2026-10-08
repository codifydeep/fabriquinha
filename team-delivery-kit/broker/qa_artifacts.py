"""Operator-bound, read-only browser incident artifacts for planning workers."""
import base64
import hashlib
import json
import re
import time
import uuid
import zlib
from pathlib import Path
from artifact_read_evidence import observations
from browser_qa_recipes import SCENARIOS


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS qa_diagnostic_artifacts('
                'issue_id TEXT PRIMARY KEY, config TEXT)')


def unpack(payload):
    fields = {'issue_id', 'root_issue_id', 'agent_id', 'source_task', 'manifest_sha256',
              'source_sha', 'browser_receipt', 'scenario_zlib', 'read_files'}
    if not isinstance(payload, dict) or set(payload) not in (fields, fields | {'runtime_spike'}):
        raise ValueError('exact QA artifact registration required')
    for key in ('issue_id', 'root_issue_id', 'agent_id', 'source_task'):
        if str(uuid.UUID(payload[key])) != payload[key]:
            raise ValueError('invalid QA artifact identity')
    if (not re.fullmatch(r'[a-f0-9]{40}', payload['source_sha'])
            or not re.fullmatch(r'[a-f0-9]{64}', payload['manifest_sha256'])):
        raise ValueError('invalid QA artifact hash')
    compressed = payload['scenario_zlib']
    if not isinstance(compressed, str) or len(compressed) > 12000:
        raise ValueError('bounded QA scenario required')
    decoder = zlib.decompressobj()
    code = decoder.decompress(base64.b64decode(compressed, validate=True), 32769)
    if len(code) > 32768 or not decoder.eof or decoder.unused_data:
        raise ValueError('QA scenario exceeds immutable artifact bound')
    code.decode('utf-8')
    receipt = payload['browser_receipt']
    if (not isinstance(receipt, dict) or set(receipt) != {'status', 'cleanup', 'automated', 'identity', 'error'}
            or receipt['status'] != 'failed' or receipt['cleanup'] != 'passed'
            or receipt['automated'] is not True
            or not isinstance(receipt['error'], str) or len(receipt['error']) > 1600
            or not isinstance(receipt.get('identity'), dict)
            or receipt['identity'].get('source_sha') != payload['source_sha']
            or receipt['identity'].get('scenario_sha256') != hashlib.sha256(code).hexdigest()):
        raise ValueError('failed browser evidence or scenario hash mismatch')
    identity = receipt['identity']
    if (set(identity) != {'source_sha', 'deployed_container_id', 'application_image',
                         'config', 'scenario_sha256', 'runtime_env'}
            or not re.fullmatch(r'[a-f0-9]{64}', identity['deployed_container_id'])
            or not re.fullmatch(r'sha256:[a-f0-9]{64}', identity['application_image'])
            or identity['runtime_env'] != {'FEEDBACK_DB_PATH': '/tmp/feedback.db'}):
        raise ValueError('safe exact browser fixture identity required')
    config = receipt['identity'].get('config')
    if (not isinstance(config, dict) or set(config) != {'scenario', 'browser_image'}
            or config['scenario'] not in SCENARIOS
            or not re.fullmatch(r'sha256:[a-f0-9]{64}', config['browser_image'])):
        raise ValueError('fixed browser operation required')
    from portable_contract import safe_path
    names = payload['read_files']
    if (not isinstance(names, list) or not 1 <= len(names) <= 8
            or len(set(names)) != len(names)):
        raise ValueError('bounded product inspection paths required')
    for name in names:
        safe_path(name)
    # Hermes counts newline delimiters in its read header. Include the final
    # newline so one real JSON source line is not reported as zero total lines.
    raw = json.dumps(receipt, sort_keys=True).encode() + b'\n'
    if len(raw) > 8192:
        raise ValueError('browser receipt too large')
    files = {'qa.json': raw, 'scenario.py': code}
    if 'runtime_spike' in payload:
        files.update(spike_bundle(payload))
    return files


def spike_bundle(payload):
    capsule=payload['runtime_spike']
    if not isinstance(capsule,dict) or set(capsule)!={'receipt','probe_zlib'}:
        raise ValueError('fixed runtime spike capsule required')
    receipt=capsule['receipt']; identity=receipt.get('identity',{}); proof=receipt.get('proof',{})
    encoded=capsule['probe_zlib']
    if not isinstance(encoded,str) or len(encoded)>12000:
        raise ValueError('bounded fixed probe required')
    decoder=zlib.decompressobj()
    code=decoder.decompress(base64.b64decode(encoded,validate=True),32769)
    if len(code)>32768 or not decoder.eof or decoder.unused_data:
        raise ValueError('runtime probe bound exceeded')
    installed=Path('/qa_runtime_probe.py')
    if not installed.exists():
        installed=Path(__file__).resolve().parents[1]/'browser_runtime_probe.py'
    if code!=installed.read_bytes():
        raise ValueError('unapproved runtime probe recipe')
    if (receipt.get('status')!='causal_spike_passed' or receipt.get('cleanup')!='passed'
            or receipt.get('scope')!='diagnostic_only_not_delivery'
            or identity.get('source_sha')!=payload['source_sha']
            or identity.get('image')!=payload['browser_receipt']['identity']['application_image']
            or identity.get('probe_sha256')!=hashlib.sha256(code).hexdigest()
            or proof.get('status')!='causal_spike_passed'
            or proof.get('scope')!='diagnostic_only_not_delivery'
            or proof.get('source_sha')!=payload['source_sha']
            or proof.get('script_sha256')!=identity.get('script_sha256')
            or not re.fullmatch(r'[a-f0-9]{64}',identity.get('script_sha256',''))
            or proof.get('original_source_unchanged') is not True):
        raise ValueError('runtime spike evidence identity drift')
    raw=json.dumps(receipt,sort_keys=True).encode()+b'\n'
    if len(raw)>8192:raise ValueError('bounded runtime receipt required')
    return {'spike.json':raw,'probe.py':code}


def copy_bundle(broker, volume, files, digest):
    """Fixed offline copy; no operator/agent-supplied argv or host bind mounts."""
    name = broker.PREFIX + '-qa-evidence-copy-' + digest[:16]
    labels = {'delivery-kit.owner': broker.OWNER, 'delivery-kit.qa-evidence': digest}
    old = broker.docker('GET', '/containers/' + name + '/json')
    if old:
        if any(old['Config']['Labels'].get(k) != v for k,v in labels.items()) or old['State']['Running']:
            raise ValueError('QA copy container identity or activity drift')
        broker.docker('DELETE', '/containers/' + name)
    program = (
        'import os,json,base64; from pathlib import Path; '
        'files=json.loads(os.environ["QA_FILES"]); root=Path("/target"); '
        'assert {p.name for p in root.iterdir()} <= set(files); '
        '\nfor name, encoded in files.items():\n'
        ' p=root/name; data=base64.b64decode(encoded,validate=True); '
        'assert not p.is_symlink(); '
        'assert not p.exists() or p.read_bytes()==data; '
        '\n if not p.exists(): p.write_bytes(data); p.chmod(0o444)\n')
    broker.docker('POST', '/containers/create?name=' + name, {
        'Image': broker.IMAGE, 'User': '0:0', 'Entrypoint': ['python3'], 'Cmd': ['-c', program],
        'Env': ['QA_FILES=' + json.dumps({k: base64.b64encode(v).decode() for k,v in files.items()})],
        'Labels': labels,
        'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'none', 'CapDrop': ['ALL'],
                       'SecurityOpt': ['no-new-privileges'], 'Memory': 67108864,
                       'PidsLimit': 32, 'NanoCpus': 500000000,
                       'Mounts': [{'Type': 'volume', 'Source': volume, 'Target': '/target'}]}})
    broker.docker('POST', '/containers/' + name + '/start')
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        info = broker.docker('GET', '/containers/' + name + '/json')
        if not info['State']['Running']:
            if info['State']['ExitCode']:
                raise ValueError('QA artifact copy failed')
            broker.docker('DELETE', '/containers/' + name)
            return
        time.sleep(.1)
    raise ValueError('QA artifact copy deadline; controller inspection required')


def register(broker, payload):
    files = unpack(payload)
    try:
        import native
    except ImportError:
        from broker import native
    with broker.LOCK, broker.db() as con:
        initialize(con)
        prior = con.execute('SELECT config FROM qa_diagnostic_artifacts WHERE issue_id=?',
                            (payload['issue_id'],)).fetchone()
        if prior:
            config = json.loads(prior[0])
            if config['request'] != payload:
                raise ValueError('QA artifact registration drift')
            return {'issue_id': payload['issue_id'], 'status': 'registered'}
        route = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                            (payload['root_issue_id'],)).fetchone()
        source = con.execute('SELECT stage,data FROM delivery_handoffs WHERE source_task=? AND issue_id=?',
                             (payload['source_task'], payload['root_issue_id'])).fetchone()
        snapshot = con.execute('SELECT volume FROM snapshots WHERE task_id=? AND status=?',
                               (payload['source_task'], 'complete')).fetchone()
        route = json.loads(route[0]) if route else {}
        source_data = json.loads(source['data']) if source else {}
        if (not source or source['stage'] != 'approved' or not snapshot
                or source_data.get('evidence', {}).get('manifest_sha256') != payload['manifest_sha256']
                or source_data.get('review', {}).get('status') != 'approved'
                or source_data.get('review', {}).get('manifest_sha256') != payload['manifest_sha256']
                or payload['agent_id'] not in (route.get('techlead'), route.get('cto'))):
            raise ValueError('approved immutable source and technical role required')
        settings = json.loads((broker.STATE / 'native.json').read_text())
        child = native.issue_record(settings, payload['issue_id'])
        parent = child.get('parent_issue_id')
        if parent != payload['root_issue_id']:
            lineage = con.execute('SELECT config FROM qa_diagnostic_artifacts WHERE issue_id=?', (parent,)).fetchone()
            if not lineage or json.loads(lineage[0])['request']['root_issue_id'] != payload['root_issue_id']:
                raise ValueError('QA diagnosis hierarchy mismatch')
        if (child.get('assignee_id') != payload['agent_id']
                or settings['agents'].get(payload['agent_id']) != 'planning'
                or native.issue_task_runs(settings, payload['issue_id'])):
            raise ValueError('registration must precede assigned planning execution')
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        volume = broker.PREFIX + '-qa-evidence-' + digest[:24]
        labels = {'delivery-kit.owner': broker.OWNER, 'delivery-kit.qa-evidence': digest}
        existing = broker.docker('GET', '/volumes/' + volume)
        if existing is None:
            broker.docker('POST', '/volumes/create', {'Name': volume, 'Labels': labels})
        elif existing.get('Labels') != labels:
            raise ValueError('QA evidence volume identity drift')
        copy_bundle(broker, volume, files, digest)
        config = {'request': payload, 'volume': volume, 'candidate_volume': snapshot[0], 'digest': digest}
        con.execute('INSERT INTO qa_diagnostic_artifacts VALUES (?,?)',
                    (payload['issue_id'], json.dumps(config, sort_keys=True)))
        return {'issue_id': payload['issue_id'], 'status': 'registered'}


def config_for(broker, issue_id, agent_id):
    with broker.db() as con:
        initialize(con)
        row = con.execute('SELECT config FROM qa_diagnostic_artifacts WHERE issue_id=?', (issue_id,)).fetchone()
    if not row:
        return None
    config = json.loads(row[0])
    if config['request']['agent_id'] != agent_id:
        raise ValueError('QA artifact recipient mismatch')
    return config


def mounts(broker, request_id):
    with broker.db() as con:
        binding = con.execute('SELECT issue_id,agent_id FROM native_bindings WHERE request_id=?', (request_id,)).fetchone()
    config = config_for(broker, binding['issue_id'], binding['agent_id']) if binding else None
    if not config:
        return []
    result = []
    for target, volume, key, value in (
        ('/evidence/candidate', config['candidate_volume'], 'delivery-kit.source-task', config['request']['source_task']),
        ('/evidence/previous', config['volume'], 'delivery-kit.qa-evidence', config['digest'])):
        actual = broker.docker('GET', '/volumes/' + volume)
        labels = actual.get('Labels', {}) if actual else {}
        if labels.get('delivery-kit.owner') != broker.OWNER or labels.get(key) != value:
            raise ValueError('QA read-only artifact identity drift')
        result.append({'Type': 'volume', 'Source': volume, 'Target': target, 'ReadOnly': True})
    return result


def read_paths(config):
    paths=['/evidence/previous/qa.json', '/evidence/previous/scenario.py']
    if 'runtime_spike' in config['request']:
        paths += ['/evidence/previous/spike.json','/evidence/previous/probe.py']
    return paths + [
        '/evidence/candidate/' + name for name in config['request']['read_files']]


def verify_reads(broker, task_id):
    try:
        import native
    except ImportError:
        from broker import native
    with broker.db() as con:
        binding = con.execute('SELECT issue_id,agent_id FROM native_bindings WHERE task_id=?', (task_id,)).fetchone()
    if not binding:
        raise ValueError('QA diagnostic execution binding missing')
    config = config_for(broker, binding['issue_id'], binding['agent_id'])
    if not config:
        raise ValueError('QA artifacts not registered')
    settings = json.loads((broker.STATE / 'native.json').read_text())
    observed = observations(native.task_messages(settings, task_id))
    paths = read_paths(config)
    required={p for p in paths if p.startswith('/evidence/previous/')}
    product={p for p in paths if p.startswith('/evidence/candidate/')}
    if not required <= set(observed) or not product & set(observed):
        raise ValueError('QA diagnosis lacks completed scenario, receipt and product reads')
    return {'status': 'read_evidence_verified', 'task_id': task_id, 'paths': sorted(set(paths) & set(observed))}
