"""Once-only independent diagnosis from an unexecuted frozen proposal experiment.

Controller archives only. Never convert a prospective restriction into the cause
of a historical native failure, a Red receipt, or an author authorization.
"""
import hashlib
import json
import re
import uuid


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def validate_proof(probe,inputs,issue,source):
    for key in ('execution_id','diagnostic_parent'):
        if str(uuid.UUID(probe.get(key,'')))!=probe[key]:raise ValueError('canonical experiment identity required')
    if (probe.get('issue_id')!=issue or probe.get('source_task')!=source
            or inputs.get('issue_id')!=issue or inputs.get('source_task')!=source
            or probe.get('status')!='failed' or probe.get('failure_category')!='fixture_protocol_rejected'
            or probe.get('fixture_kind')!='frozen_context_prospective_v1'
            or probe.get('input_sha256')!=digest(inputs)
            or probe.get('manifest_sha256')!=inputs.get('manifest_sha256')
            or not re.fullmatch(r'[a-f0-9]{64}',str(probe.get('manifest_sha256')))
            or any(probe.get(k) is not False for k in ('tools_executed','candidate_files_written',
                'native_read_evidence','historical_failure_cause_proven','product_retry','delivery_approval'))):
        raise ValueError('same frozen nonexecuted nonapproving experiment required')
    rejection=probe.get('local_rejection') or {}
    if (rejection.get('schema')!='local-proposal-rejection-v1' or rejection.get('constraint')!='artifact_size'
            or not re.fullmatch(r'[a-f0-9]{64}',str(rejection.get('response_sha256')))
            or any(rejection.get(k) is not False for k in ('tools_executed','candidate_files_written'))):
        raise ValueError('measured prospective artifact size rejection required')
    target=inputs.get('target','');files=inputs.get('files',{})
    if (not re.fullmatch(r'/workspace/tests/test_[A-Za-z0-9_]+\.py',target)
            or not isinstance(files.get(target),str) or not 32000<=len(files[target].encode())<=32768):
        raise ValueError('bounded frozen NEW test with scarce headroom required')
    return dict(kind='prospective_capacity_experiment_v1',issue_id=issue,source_task=source,
        execution_id=probe['execution_id'],diagnostic_parent=probe['diagnostic_parent'],
        probe_sha256=digest(probe),input_sha256=digest(inputs),manifest_sha256=probe['manifest_sha256'],
        target=target,test_sha256=hashlib.sha256(files[target].encode()).hexdigest(),
        test_bytes=len(files[target].encode()),file_limit_bytes=32768,
        available_growth_bytes=32768-len(files[target].encode()),
        prospective_constraint='artifact_size',historical_failure_cause_proven=False,
        author_retry_authorized=False,delivery_approval=False)


def claim(c,proof):
    c.execute('CREATE TABLE IF NOT EXISTS prospective_capacity_experiments('
        'issue_id TEXT PRIMARY KEY,source_task TEXT,receipt TEXT)')
    old=c.execute('SELECT source_task,receipt FROM prospective_capacity_experiments WHERE issue_id=?',
        (proof['issue_id'],)).fetchone()
    if old:
        if old[0]!=proof['source_task'] or json.loads(old[1])!=proof:
            raise ValueError('one capacity experiment per issue; identity drift cannot rearm it')
        return proof
    c.execute('INSERT INTO prospective_capacity_experiments VALUES(?,?,?)',
        (proof['issue_id'],proof['source_task'],json.dumps(proof,sort_keys=True)))
    return proof


def qualified(c,issue,source,data):
    proof=(data.get('prospective_capacity_replay') or {}).get('certificate')
    if not proof or not c.execute("SELECT 1 FROM sqlite_master WHERE name='prospective_capacity_experiments'").fetchone():return False
    row=c.execute('SELECT source_task,receipt FROM prospective_capacity_experiments WHERE issue_id=?',(issue,)).fetchone()
    return bool(row and row[0]==source and json.loads(row[1])==proof
        and all(proof.get(k) is False for k in ('historical_failure_cause_proven','author_retry_authorized','delivery_approval')))


def capture(b,issue,source):
    try:import transport_qualification
    except ImportError:from broker import transport_qualification
    config_path=b.STATE/'prospective-capacity.json'
    if not config_path.exists():return None
    config=transport_qualification.private_json(config_path,1024)
    if set(config)!={'execution_id'}:raise ValueError('exact controller archive selector required')
    identifier=config['execution_id']
    if str(uuid.UUID(identifier))!=identifier:raise ValueError('canonical archive selector required')
    folder=b.STATE/'prospective-capacity-evidence'
    if folder.is_symlink():raise ValueError('restricted evidence folder required')
    probe=transport_qualification.private_json(folder/(identifier+'.json'),65536)
    inputs=transport_qualification.private_json(folder/(identifier+'.input.json'),262144)
    if probe.get('execution_id')!=identifier:raise ValueError('archive identity drift')
    proof=validate_proof(probe,inputs,issue,source)
    with b.db() as c:
        row=c.execute('SELECT stage,data FROM delivery_handoffs WHERE issue_id=? AND source_task=?',(issue,source)).fetchone()
        if not row or row['stage']!='test_first_blocked':return None
        data=json.loads(row['data'])
        route=c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
        route=json.loads(route[0]) if route else {}
        latest=c.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(issue,)).fetchone()
        snapshot=c.execute('SELECT volume,status FROM failed_execution_snapshots WHERE task_id=?',(source,)).fetchone()
        if (data.get('error')!='test_first_cto_requires_replanning'
                or data.get('decision',{}).get('action')!='escalate_cto'
                or data.get('verified_tool_incident',{}).get('cause_known') is not False
                or data.get('prospective_capacity_replay') or not latest or latest[0]!=source
                or route.get('enabled') is not True or route.get('test_first') is not True
                or not route.get('author') or route.get('author')==route.get('cto')
                or route.get('test_first_files')!=[proof['target'].removeprefix('/workspace/')]
                or not snapshot or snapshot['status']!='complete'
                or c.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
                or c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):return None
        labels=b.docker('GET','/volumes/'+snapshot['volume']).get('Labels',{})
        if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=source:
            raise ValueError('owned exact frozen snapshot required')
        return claim(c,proof)
