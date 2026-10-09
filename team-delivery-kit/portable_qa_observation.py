"""One new read-only diagnosis after a changed, failed browser observation.

This is not a scenario resolution: a failed run cannot approve a release or
dispatch an implementer. Historical diagnostic artifacts are never rebound.
"""
import hashlib
import json
from pathlib import Path
import subprocess

from portable_qa_protocol_recovery import digest, read
from release_eval import save_receipt


def previous(incident, prior, cli):
    child = cli('get', prior['child_issue_id'])
    runs = cli('runs', child['id'])
    if (child.get('parent_issue_id') != incident['child_issue_id']
            or child.get('assignee_id') != prior['cto_id'] or len(runs) != 1
            or runs[0].get('agent_id') != prior['cto_id']):
        raise ValueError('exact prior CTO observation required')
    if runs[0].get('status') != 'completed':
        return None
    output = runs[0].get('result', {}).get('output')
    if not isinstance(output, str) or len(output) > 32768:
        raise ValueError('bounded prior CTO decision required')
    decision = json.loads(output)
    if (not isinstance(decision, dict) or set(decision) !=
            {'decision', 'root_cause', 'editable_code_files', 'new_test_file', 'acceptance'}):
        raise ValueError('exact prior CTO decision required')
    if decision['decision'] != 'blocked':
        return None
    if (decision['editable_code_files'] != [] or decision['new_test_file'] != ''
            or decision['acceptance'] != [] or not isinstance(decision['root_cause'], str)
            or not decision['root_cause'].strip()):
        raise ValueError('non-authorizing blocked CTO decision required')
    from portable_qa_evidence import confirm_reads
    confirm_reads(runs[0]['id'])
    from evalctl import PROJECT
    name = PROJECT + '-execution-broker-1'
    labels = json.loads(subprocess.check_output(['docker','inspect','--format',
        '{{json .Config.Labels}}', name], text=True, timeout=10))
    if (labels.get('com.docker.compose.project') != PROJECT
            or labels.get('com.docker.compose.service') != 'execution-broker'):
        raise ValueError('owned diagnostic evidence controller required')
    program = ('import broker as b,qa_artifacts,json,sys; '
               'c=qa_artifacts.config_for(b.handoff_context(),sys.argv[1],sys.argv[2]); '
               'print(json.dumps(c["request"]["browser_receipt"]))')
    old = json.loads(subprocess.check_output(['docker','exec','-w','/', name,
        'python','-c',program,child['id'],prior['cto_id']], text=True, timeout=30))
    if old.get('identity', {}).get('source_sha') != incident['source_sha']:
        raise ValueError('prior diagnostic source drift')
    return {'task_id': runs[0]['id'], 'issue_id': child['id'],
            'decision_sha256': digest(decision), 'browser_receipt': old}


def current(private, incident, old):
    from portable_browser_qa import script_for
    delivery = read(Path(private)/'release-receipts'/(incident['label']+'.json'))
    if (delivery.get('issue_id') != incident['parent_issue_id']
            or delivery.get('merge_sha') != incident['source_sha']
            or delivery.get('deployment', {}).get('source_sha') != incident['source_sha']):
        raise ValueError('observation delivery drift')
    identity = old.get('identity', {})
    if (old.get('status') != 'failed' or old.get('cleanup') != 'passed'
            or old.get('automated') is not True
            or identity.get('application_image') != delivery['deployment']['image_id']):
        raise ValueError('previous immutable failed observation required')
    folder = Path(private)/'browser-acceptance'/incident['label']
    matches = []
    for path in folder.glob('*.json'):
        value = read(path)
        new = value.get('identity', {})
        if (new.get('config') != identity.get('config')
                or new.get('source_sha') != incident['source_sha']):
            continue
        recipe_hash = hashlib.sha256(script_for(new['config']).read_bytes()).hexdigest()
        if new.get('scenario_sha256') != recipe_hash:
            continue
        if recipe_hash == identity.get('scenario_sha256'):
            return None
        if (value.get('status') != 'failed' or value.get('cleanup') != 'passed'
                or value.get('automated') is not True):
            return None
        if ({k:v for k,v in new.items() if k != 'scenario_sha256'} !=
                {k:v for k,v in identity.items() if k != 'scenario_sha256'}):
            raise ValueError('changed product cannot be observation recovery')
        if not isinstance(value.get('error'), str) or not value['error'].strip():
            raise ValueError('new failed observation requires error evidence')
        matches.append({'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'identity': new})
    if len(matches) > 1:
        raise ValueError('ambiguous new browser observation')
    return matches[0] if matches else None


def validate(private, incident, proof):
    path = Path(private)/'qa-observation-proofs'/(incident['key']+'.json')
    if (not isinstance(proof, dict) or read(path) != proof
            or proof.get('incident_key') != incident['key']
            or proof.get('source_sha') != incident['source_sha']
            or proof.get('delivery_approval') is not False
            or proof.get('author_retry_authorized') is not False):
        raise ValueError('durable non-authorizing observation proof required')
    fresh = current(private, incident, proof['previous']['browser_receipt'])
    if fresh != proof['current']:
        raise ValueError('new diagnostic observation drift')


def recover(private, cli, *, incident, prior, parent_contract, budget_ready,
            observe=previous):
    if incident.get('phase') != 'browser' or not budget_ready:
        return None
    old = observe(incident, prior, cli)
    if old is None:
        return None
    new = current(private, incident, old['browser_receipt'])
    if new is None:
        return None
    proof = {'incident_key': incident['key'], 'source_sha': incident['source_sha'],
             'cto_id': prior['cto_id'], 'previous': old, 'current': new,
             'delivery_approval': False, 'author_retry_authorized': False}
    path = Path(private)/'qa-observation-proofs'/(incident['key']+'.json')
    if path.exists():
        if read(path) != proof:
            raise ValueError('one observation recovery per incident; technical replan required')
    else:
        save_receipt(path, proof)
    validate(private, incident, proof)
    from portable_qa_cto import record
    return record(private, cli, incident=incident, parent_contract=parent_contract,
                  cto_id=prior['cto_id'], reason='New failed QA observation after scenario correction',
                  budget_ready=True, observation_recovery=proof)
