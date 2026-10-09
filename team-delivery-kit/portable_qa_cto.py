"""One bounded CTO diagnosis after Tech Lead QA diagnosis cannot progress."""
import json
from pathlib import Path

from portable_qa_incident import _set_metadata, failing_case
from release_eval import save_receipt


def find(private, key):
    path = Path(private) / 'qa-cto-escalations' / (key + '.json')
    if path.is_symlink():
        raise ValueError('unsafe QA CTO receipt')
    return json.loads(path.read_text()) if path.exists() else None


def record(private, cli, *, incident, parent_contract, cto_id, reason,
           budget_ready, protocol_recovery=None, observation_recovery=None,
           authority_recovery=None):
    """Create/dispatch one read-only CTO card; never start a second run."""
    if (not isinstance(reason, str) or not 0 < len(reason) <= 300
            or not isinstance(cto_id, str) or not cto_id):
        raise ValueError('invalid QA CTO escalation')
    key = incident['key']
    title = 'QA-CTO-' + key[:8].upper()
    path = Path(private) / 'qa-cto-escalations' / (key + '.json')
    original=find(private,key)
    if sum(value is not None for value in
           (protocol_recovery, observation_recovery, authority_recovery)) > 1:
        raise ValueError('distinct diagnostic recovery modes required')
    if authority_recovery is not None:
        from portable_qa_authority import validate
        validate(private,incident,authority_recovery)
        if authority_recovery.get('cto_id') != cto_id:
            raise ValueError('authority diagnostic owner drift')
        title+='-D1'
        path=Path(private)/'qa-authority-recoveries'/(key+'.json')
    if observation_recovery is not None:
        from portable_qa_observation import validate
        validate(private,incident,observation_recovery)
        if observation_recovery.get('cto_id') != cto_id:
            raise ValueError('observation diagnostic owner drift')
        title+='-O1'
        path=Path(private)/'qa-observation-recoveries'/(key+'.json')
    if protocol_recovery is not None:
        from portable_qa_protocol_recovery import validate
        if not original:raise ValueError('historical CTO execution required')
        validate(private,incident,original,protocol_recovery)
        title+='-P1'
        path=Path(private)/'qa-cto-protocol-recoveries'/(key+'.json')
    identity = {'incident_key': key, 'source_sha': incident['source_sha'],
                'parent_issue_id': incident['child_issue_id'],
                'cto_id': cto_id, 'reason': reason, 'title': title}
    if protocol_recovery is not None:identity['protocol_recovery']=protocol_recovery
    if observation_recovery is not None:identity['observation_recovery']=observation_recovery
    if authority_recovery is not None:identity['authority_recovery']=authority_recovery
    if path.is_symlink():raise ValueError('unsafe QA CTO receipt')
    prior = json.loads(path.read_text()) if path.exists() else None
    if prior:
        if any(prior.get(field) != value for field, value in identity.items()):
            raise ValueError('QA CTO escalation identity drift')
        receipt = prior
    else:
        receipt = {**identity, 'child_issue_id': None, 'dispatch': 'not_started',
                   'decision_contract_version': 2}
        save_receipt(path, receipt)
    code = sorted(set(parent_contract['editable_files']) -
                  set(parent_contract['test_files']))
    from portable_qa_evidence import case as qa_case, description as evidence_description, bind
    case = qa_case(parent_contract, incident)
    description = (
        'YOU ARE THE CTO. The Tech Lead could not safely diagnose a verified '
        'deployed QA failure after its bounded attempt. Technical decision, '
        'not a CEO question. Failed exact SHA: ' + incident['source_sha'] +
        '. Failure: ' + incident['category'] + '. Escalation: ' + reason +
        '. Exact operator-owned QA case: ' + json.dumps(case, sort_keys=True) +
        '. Existing allowed code files: ' + json.dumps(code) +
        '. Existing test discovery roots: ' +
        json.dumps(parent_contract['test_roots']) + '. Inspect read-only. '
        'Return ONE JSON object only: {"decision":"repair" or "blocked", '
        '"root_cause":"...", "editable_code_files":["..."], '
        '"new_test_file":"...", "acceptance":["..."]}. For repair, '
        'select only an existing allowed code file and one genuinely new safe '
        'test under an existing root. Never loosen QA cases, existing tests, '
        'test commands or security policy. For blocked, use empty arrays and '
        'test path and state the precise technical impediment. Do not edit '
        'files, claim execution, or request a technical decision from CEO.')
    description += evidence_description(incident)
    version = receipt.get('decision_contract_version', 1)
    if version not in (1, 2):
        raise ValueError('unsupported CTO decision contract')
    if version == 2:
        from qa_decision_authority import CONTRACT
        description += CONTRACT
    if protocol_recovery is not None:
        description+=' Protocol recovery P1: prior CTO execution remains failed. A counted protocol fixture passed after the controller transport correction. Inspect the SAME immutable artifacts anew; this authorizes diagnosis only, not product writes, retry, QA waiver or release approval.'
    if observation_recovery is not None:
        description+=' Observation recovery O1: the prior diagnosis remains preserved. The controller corrected its browser scenario and obtained a NEW failed observation on the SAME product SHA and image. Read the new immutable QA artifacts; decide whether this is a real product defect. This grants diagnosis only, never writes, release approval or permission to weaken tests.'
    if authority_recovery is not None:
        description+=' Decision clarification D1: the previous blocked decision requested authority from its own CTO role. That decision remains preserved. This execution clarifies proposal authority only, using the SAME immutable failed QA and product evidence. You must make your own technical decision; the controller does not prescribe repair or approve a release.'
    matches = [item for item in cli('search', title, '--include-closed',
                                    '--limit', '100')['issues']
               if item.get('title') == title]
    if len(matches) > 1:
        raise ValueError('duplicate QA CTO cards')
    child = matches[0] if matches else cli(
        'create', '--title', title, '--description', description,
        '--status', 'blocked', '--parent', incident['child_issue_id'])
    if protocol_recovery and child.get('id')==original['child_issue_id']:
        raise ValueError('protocol recovery cannot replace historical CTO card')
    if authority_recovery and child.get('id')==authority_recovery['previous']['issue_id']:
        raise ValueError('authority clarification cannot replace historical CTO card')
    if (child.get('title') != title
            or child.get('parent_issue_id') != incident['child_issue_id']
            or not child.get('id')
            or child.get('description', description) != description
            or child.get('assignee_id') not in (None, cto_id)
            or child.get('status') not in ('blocked', 'todo', 'in_progress', 'done')):
        raise ValueError('QA CTO card drift')
    if receipt['child_issue_id'] not in (None, child['id']):
        raise ValueError('QA CTO card changed')
    receipt['child_issue_id'] = child['id']
    _set_metadata(cli, child['id'], 'qa_incident_key', key)
    _set_metadata(cli, child['id'], 'qa_source_sha', incident['source_sha'])
    _set_metadata(cli, incident['child_issue_id'],
                  'qa_cto_authority_issue_id' if authority_recovery else
                  'qa_cto_observation_issue_id' if observation_recovery else
                  'qa_cto_protocol_issue_id' if protocol_recovery else 'qa_cto_issue_id', child['id'])
    if child['assignee_id'] is None:
        cli('assign', child['id'], '--to-id', cto_id, '--no-start')
    runs = cli('runs', child['id'])
    # Never rebind a historical diagnosis to a newer scenario observation.
    if budget_ready and not runs:
        bind(private, incident, child['id'], cto_id)
    if any(run.get('agent_id') != cto_id for run in runs):
        raise ValueError('QA CTO card has foreign agent run')
    if any(run.get('status') == 'failed' for run in runs):
        receipt['dispatch'] = 'cto_failed'
    elif runs:
        receipt['dispatch'] = 'cto_started'
    elif child['status'] == 'done':
        raise ValueError('completed QA CTO card has no CTO run')
    elif budget_ready:
        if cli('get', child['id'])['status'] == 'blocked':
            cli('status', child['id'], 'todo', '--no-start')
        cli('rerun', child['id'])
        receipt['dispatch'] = 'cto_started'
    else:
        receipt['dispatch'] = 'budget_paused'
    save_receipt(path, receipt)
    return receipt
