"""Bind failed browser receipts before a diagnostic card can run."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import zlib


def description(incident):
    if incident.get('phase') != 'browser':
        return ''
    return (' QA_DIAGNOSIS_V1: Read /evidence/previous/qa.json and '
            '/evidence/previous/scenario.py, then actual product in '
            '/evidence/candidate. Artifacts are immutable. Identify product vs '
            'scenario vs infrastructure defect from evidence; never change the '
            'scenario or tests. A repair proposal must cite concrete product code. '
            'For a scenario or infrastructure defect return decision=blocked '
            'with a precise technical impediment for CTO, not a CEO question.')


def bind(private, incident, issue_id, agent_id):
    if incident.get('phase') != 'browser':
        return
    from portable_browser_qa import SCRIPT
    from prepare_issue_base import broker_post
    root = Path(private)
    delivery = json.loads((root / 'release-receipts' / (incident['label'] + '.json')).read_text())
    if (delivery['issue_id'] != incident['parent_issue_id']
            or delivery['merge_sha'] != incident['source_sha']
            or delivery['deployment']['source_sha'] != incident['source_sha']):
        raise ValueError('QA diagnosis delivery identity drift')
    folder = root / 'browser-acceptance' / incident['label']
    script = SCRIPT.read_bytes()
    matches = []
    for path in folder.glob('*.json'):
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError('unsafe browser evidence')
        receipt = json.loads(path.read_text())
        identity = receipt.get('identity', {})
        if (receipt.get('status') == 'failed' and identity.get('source_sha') == incident['source_sha']
                and identity.get('scenario_sha256') == hashlib.sha256(script).hexdigest()
                and identity.get('application_image') == delivery['deployment']['image_id']):
            matches.append(receipt)
    if len(matches) != 1:
        raise ValueError('exact failed browser artifact and current scenario required')
    receipt = matches[0]
    safe = {k: receipt[k] for k in ('status','cleanup','automated','identity')}
    safe['error'] = receipt['error'][:1600]
    paths = delivery['preflight']['changed_code']
    payload = {'issue_id': issue_id, 'root_issue_id': incident['parent_issue_id'],
               'agent_id': agent_id, 'source_task': delivery['delivery']['source_task'],
               'manifest_sha256': delivery['delivery']['manifest_sha256'],
               'source_sha': incident['source_sha'], 'browser_receipt': safe,
               'scenario_zlib': base64.b64encode(zlib.compress(script)).decode(),
               'read_files': paths[:8]}
    broker_post('/v1/qa-diagnostic-artifacts', payload)


def confirm_reads(task_id):
    from evalctl import PROJECT
    output = subprocess.check_output(['docker','exec','-e','PYTHONPATH=/',
        PROJECT + '-execution-broker-1','python','-c',
        'import broker,qa_artifacts,json,sys; '
        'print(json.dumps(qa_artifacts.verify_reads(broker.handoff_context(),sys.argv[1])))',
        task_id],text=True)
    proof = json.loads(output)
    if proof.get('status') != 'read_evidence_verified' or proof.get('task_id') != task_id:
        raise ValueError('QA diagnostic read proof mismatch')
    return proof


def case(contract, incident):
    if incident.get('phase') == 'browser':
        return {'phase': 'browser', 'source_sha': incident['source_sha'],
                'receipt': '/evidence/previous/qa.json',
                'scenario': '/evidence/previous/scenario.py', 'policy': 'unchanged real-browser gate'}
    from portable_qa_incident import failing_case
    return failing_case(contract, incident['category'])
