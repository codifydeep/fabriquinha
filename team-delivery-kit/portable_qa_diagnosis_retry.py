"""One bounded, durable Tech Lead retry after a rejected QA diagnosis."""
import json
from pathlib import Path

from portable_qa_incident import _set_metadata, failing_case
from release_eval import save_receipt


def find(private, key):
    path = Path(private) / 'qa-diagnosis-retries' / (key + '.json')
    if path.is_symlink():
        raise ValueError('unsafe QA diagnosis retry receipt')
    return json.loads(path.read_text()) if path.exists() else None


def record(private, cli, *, incident, parent_contract, task_id, reason,
           budget_ready):
    key = incident['key']
    if (not isinstance(task_id, str) or not task_id
            or not isinstance(reason, str) or not reason or len(reason) > 300):
        raise ValueError('invalid QA diagnosis rejection')
    title = 'QA-DIAG-RETRY-' + key[:8].upper()
    folder = Path(private) / 'qa-diagnosis-retries'
    path = folder / (key + '.json')
    identity = {'incident_key': key, 'source_sha': incident['source_sha'],
                'parent_issue_id': incident['child_issue_id'],
                'techlead_id': incident['techlead_id'],
                'rejected_task_id': task_id, 'rejection_reason': reason,
                'title': title}
    prior = find(private, key)
    if prior:
        if {field: prior.get(field) for field in identity} != identity:
            raise ValueError('QA diagnosis retry identity drift')
        receipt = prior
    else:
        receipt = {**identity, 'child_issue_id': None, 'dispatch': 'not_started'}
        save_receipt(path, receipt)
    code = sorted(set(parent_contract['editable_files']) -
                  set(parent_contract['test_files']))
    if not code:
        raise ValueError('QA diagnosis retry lacks a precise operator contract')
    from portable_qa_evidence import case as qa_case, description as evidence_description, bind
    case = qa_case(parent_contract, incident)
    description = (
        'The previous QA diagnosis was rejected by the controller: ' + reason +
        '. Inspect the actual code and return exactly ONE JSON object, no '
        'Markdown: {"decision":"repair" or "blocked", "root_cause":"...", '
        '"editable_code_files":["..."], "new_test_file":"...", '
        '"acceptance":["..."]}. root_cause must be at most 1000 '
        'characters. Exact operator-owned QA case: ' +
        json.dumps(case, sort_keys=True) + '. Existing allowed code '
        'paths: ' + json.dumps(code) + '. Existing discovery roots: ' +
        json.dumps(parent_contract['test_roots']) + '. A repair must choose '
        'only an allowed code path and ONE genuinely new safe relative test '
        'path, with no ../ or absolute segments. Acceptance has 1 to 5 '
        'bounded items. The QA case is exact: never broaden MIME acceptance '
        'or claim text/javascript is equivalent to application/javascript. '
        'Do not modify files, change tests/QA policy, or ask the CEO. If no '
        'safe fix exists, use decision=blocked with empty file lists and '
        'acceptance, stating the precise technical impediment.')
    description += evidence_description(incident)
    matches = [item for item in cli('search', title, '--include-closed',
                                    '--limit', '100')['issues']
               if item.get('title') == title]
    if len(matches) > 1:
        raise ValueError('duplicate QA diagnosis retry cards')
    child = matches[0] if matches else cli(
        'create', '--title', title, '--description', description,
        '--status', 'blocked', '--parent', incident['child_issue_id'])
    if (child.get('title') != title
            or child.get('parent_issue_id') != incident['child_issue_id']
            or not child.get('id')
            or child.get('assignee_id') not in (None, incident['techlead_id'])):
        raise ValueError('QA diagnosis retry card drift')
    if receipt['child_issue_id'] not in (None, child['id']):
        raise ValueError('QA diagnosis retry child changed')
    receipt['child_issue_id'] = child['id']
    _set_metadata(cli, child['id'], 'qa_incident_key', key)
    _set_metadata(cli, child['id'], 'qa_source_sha', incident['source_sha'])
    _set_metadata(cli, incident['child_issue_id'], 'qa_diagnosis_retry_issue_id', child['id'])
    if child['assignee_id'] is None:
        cli('assign', child['id'], '--to-id', incident['techlead_id'], '--no-start')
    if budget_ready:
        bind(private, incident, child['id'], incident['techlead_id'])
    runs = cli('runs', child['id'])
    if any(run.get('agent_id') != incident['techlead_id'] for run in runs):
        raise ValueError('QA diagnosis retry has foreign agent run')
    if any(run.get('status') == 'failed' for run in runs):
        receipt['dispatch'] = 'retry_failed'
    elif runs:
        receipt['dispatch'] = 'techlead_started'
    elif budget_ready:
        current = cli('get', child['id'])
        if current['status'] == 'blocked':
            cli('status', child['id'], 'todo', '--no-start')
        cli('rerun', child['id'])
        receipt['dispatch'] = 'techlead_started'
    else:
        receipt['dispatch'] = 'budget_paused'
    save_receipt(path, receipt)
    return receipt
