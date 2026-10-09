"""Idempotent, durable handoff for a failed candidate or deployed HTTP QA."""
import hashlib
import json
from pathlib import Path
import re
import uuid

from release_eval import save_receipt


class QualityBlocked(Exception):
    def __init__(self, incident):
        self.incident = incident
        super().__init__(incident['category'])


def failing_case(contract, reason):
    matches = [case for case in contract['qa_cases']
               if reason.endswith(': ' + case['path'])]
    marker = re.search(r' \[qa-case=([a-f0-9]{64})\]: ', reason)
    if marker:
        matches = [case for case in matches if hashlib.sha256(json.dumps(
            case, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == marker[1]]
    if len(matches) != 1:
        raise ValueError('QA incident does not identify one exact contract case')
    return matches[0]


def find(private, parent_issue_id, label):
    folder = Path(private) / 'qa-incidents'
    if not folder.exists():
        return None
    matches = []
    for path in folder.glob('*.json'):
        if path.is_symlink() or not path.is_file():
            raise ValueError('unsafe QA incident receipt')
        candidate = json.loads(path.read_text())
        if (candidate.get('parent_issue_id') == parent_issue_id
                and candidate.get('label') == label):
            matches.append(candidate)
    if len(matches) > 1:
        raise ValueError('multiple QA incidents for one delivery run')
    return matches[0] if matches else None


def _set_metadata(cli, issue_id, key, value):
    existing = cli('metadata', 'list', issue_id)
    if not isinstance(existing, dict):
        raise ValueError('QA issue metadata unavailable')
    if key in existing and existing[key] != value:
        raise ValueError('QA issue metadata drift: ' + key)
    if key not in existing:
        cli('metadata', 'set', issue_id, '--key', key, '--value', value,
            '--type', 'string')


def _advance_gate(cli, issue_id, target):
    existing = cli('metadata', 'list', issue_id)
    current = existing.get('execution_gate')
    if current not in (None, target, 'budget_paused'):
        raise ValueError('QA incident gate drift')
    if current != target:
        cli('metadata', 'set', issue_id, '--key', 'execution_gate',
            '--value', target, '--type', 'string')


def _block_delivery_gate(private, cli, incident):
    """Transition execution state, never treating it as immutable identity.

    A dispatched delivery may enter QA failure only with its exact durable
    publication receipt and independently approved handoff. Unknown states and
    stale deliveries fail closed; replay of the same incident is idempotent.
    """
    issue_id = incident['parent_issue_id']
    metadata = cli('metadata', 'list', issue_id)
    target = 'blocked_' + incident['phase'] + '_qa'
    current = metadata.get('execution_gate')
    if current == 'dispatched' or (current == target and 'delivery_handoff' in metadata):
        path = Path(private) / 'release-receipts' / (incident['label'] + '.json')
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1048576:
            raise ValueError('QA gate requires exact delivery receipt')
        delivery = json.loads(path.read_text())
        approved = delivery.get('delivery', {})
        handoff = metadata.get('delivery_handoff')
        if isinstance(handoff, str):
            handoff = json.loads(handoff)
        sha_field = 'head_sha' if incident['phase'] == 'candidate' else 'merge_sha'
        if (delivery.get('issue_id') != issue_id
                or delivery.get('label') != incident['label']
                or delivery.get(sha_field) != incident['source_sha']
                or not approved.get('source_task')
                or not approved.get('author') or not approved.get('reviewer')
                or approved['author'] == approved['reviewer']
                or not approved.get('review_task')
                or not re.fullmatch(r'[a-f0-9]{64}', approved.get('manifest_sha256', ''))):
            raise ValueError('QA gate delivery evidence drift')
        identity={'issue_id':issue_id,'label':incident['label'],'phase':incident['phase'],
                  'source_sha':incident['source_sha'],'delivery':approved}
        approved_projection=(isinstance(handoff,dict) and handoff.get('stage')=='approved'
                    and handoff.get('source_task')==approved['source_task']
                    and handoff.get('owner')==approved['reviewer'])
        paused_projection=(current==target and isinstance(handoff,dict) and handoff.get('stage')=='paused'
                    and handoff.get('source_task') in (None,approved['source_task'])
                    and handoff.get('owner')==incident['techlead_id'])
        if not approved_projection and not paused_projection:
            raise ValueError('QA gate delivery evidence drift')
        frozen=Path(private)/'qa-gate-transitions'/(incident['key']+'.json')
        if frozen.exists():
            if frozen.is_symlink() or frozen.stat().st_size>262144:
                raise ValueError('safe frozen QA gate evidence required')
            proof=json.loads(frozen.read_text())
            if proof.get('identity')!=identity or proof.get('delivery_approval') is not False:
                raise ValueError('frozen QA gate evidence drift')
        else:
            if approved_projection:
                evidence={'approved_handoff':handoff}
            elif paused_projection:
                # Older installations did not freeze this transition. Verify
                # actual prior independent approval; never convert paused text
                # or old test receipts into new approval evidence.
                from portable_qa_gate_evidence import verify
                verified=verify(incident,approved)
                if (verified.get('operation')!='existing_approved_snapshot_verified_not_new_approval'
                        or verified.get('issue_id')!=issue_id or verified.get('delivery')!=approved
                        or verified.get('delivery_approval') is not False):
                    raise ValueError('QA gate historical verification drift')
                evidence={'historical_verification':verified}
            else:
                raise ValueError('QA gate delivery evidence drift')
            save_receipt(frozen,{'identity':identity,'evidence':evidence,'delivery_approval':False})
    elif current not in (None, target):
        raise ValueError('QA incident parent gate drift')
    if current != target:
        cli('metadata', 'set', issue_id, '--key', 'execution_gate',
            '--value', target, '--type', 'string')


def record(private, cli, *, context, label, phase, source_sha, error,
           techlead_id, budget_ready, parent_contract=None):
    """Create one child incident, bind ownership, and fail closed on drift.

    Agent execution is allowed only when an operator's existing model proxy has
    the normal new-card budget. Otherwise the issue is visibly budget-paused.
    """
    if (phase not in ('candidate', 'deployed', 'browser')
            or not re.fullmatch(r'[0-9a-f]{40}', source_sha)
            or not isinstance(context.get('issue_id'), str)
            or not re.fullmatch(r'[A-Z][A-Z0-9]{1,31}-[1-9][0-9]{0,5}', label)):
        raise ValueError('invalid QA incident identity')
    for value in (techlead_id, context['issue_id']):
        if str(uuid.UUID(value)) != value:
            raise ValueError('invalid QA incident UUID')
    reason = str(error).replace('\r', ' ').replace('\n', ' ')[:300]
    if not reason.startswith('post-deploy '):
        raise ValueError('not a contract HTTP QA failure')
    contract_details = ''
    if parent_contract is not None:
        from portable_contract import validate as validate_contract
        validate_contract(parent_contract)
        code_paths = sorted(set(parent_contract['editable_files']) -
                            set(parent_contract['test_files']))
        if phase == 'browser':
            if not reason.startswith('post-deploy browser QA '):
                raise ValueError('not an isolated browser QA failure')
            evidence = (' Isolated real-browser acceptance failed. Inspect the durable '
                        'browser-acceptance receipt for exact image, scenario hash and cleanup '
                        'result. Distinguish infrastructure from application failure. Do not '
                        'weaken the trusted scenario or claim HTTP checks replace browser QA. '
                        'Product defects can create a new same-main TDD repair; scenario '
                        'or infrastructure defects must escalate technically without modifying QA.')
        else:
            matching = [failing_case(parent_contract, reason)]
            evidence = ' Existing operator-owned QA case: ' + json.dumps(matching[:1], sort_keys=True)[:1200]
        contract_details = (evidence +
                            '. Allowed code paths: ' + ', '.join(code_paths)[:1000] +
                            '. Test roots: ' + ', '.join(parent_contract['test_roots'])[:500] + '.')
    parent = cli('get', context['issue_id'])
    if parent.get('id') != context['issue_id'] or parent.get('status') == 'done':
        raise ValueError('QA failure cannot replace a completed delivery')
    key = hashlib.sha256((context['issue_id'] + ':' + phase + ':' +
                          source_sha).encode()).hexdigest()[:16]
    title = 'QA-' + label + '-' + phase.upper() + '-' + key[:8]
    path = Path(private) / 'qa-incidents' / (key + '.json')
    identity = {'key': key, 'parent_issue_id': context['issue_id'], 'label': label,
                'phase': phase, 'source_sha': source_sha, 'category': reason,
                'techlead_id': techlead_id, 'title': title}
    if parent_contract is not None:
        identity['parent_contract_sha256'] = hashlib.sha256(json.dumps(
            parent_contract, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if path.exists():
        prior = json.loads(path.read_text())
        if {field: prior.get(field) for field in identity} != identity:
            raise ValueError('QA incident identity drift')
        incident = prior
    else:
        incident = {**identity, 'child_issue_id': None, 'dispatch': 'not_started'}
        save_receipt(path, incident)

    matches = [item for item in cli('search', title, '--include-closed',
                                    '--limit', '100')['issues']
               if item.get('title') == title]
    if len(matches) > 1:
        raise ValueError('duplicate QA incident cards')
    if matches:
        child = matches[0]
    else:
        description = (
            'Controller-verified ' + ('browser' if phase == 'browser' else 'HTTP') +
            ' QA failure. Parent: ' + context['issue_id'] +
            '. Phase: ' + phase + '. Source SHA: ' + source_sha + '. Failure: ' +
            reason + '.' + contract_details + ' Technical owner: Tech Lead. Inspect the contract and '
            'implementation read-only. Return exactly one JSON object (no Markdown): '
            '{"decision":"repair" or "blocked", "root_cause":"...", '
            '"editable_code_files":["..."], "new_test_file":"...", '
            '"acceptance":["..."]}. For repair, choose only code paths already '
            'editable in the parent contract and one NEW regression test under '
            'its existing test roots. For blocked, use empty code files, an empty '
            'new_test_file and explain why. Do not change QA cases, test commands, '
            'Dockerfile, baseline tests, reviewers or evidence. Candidate/pre-merge '
            'failures cannot yet be auto-dispatched; still diagnose them. Do not '
            'mark the parent delivered.')
        from portable_qa_evidence import description as evidence_description
        description += evidence_description(identity)
        child = cli('create', '--title', title, '--description', description,
                    '--status', 'blocked', '--parent', context['issue_id'])
    if (child.get('parent_issue_id') != context['issue_id']
            or child.get('title') != title or not child.get('id')
            or child.get('status') not in ('blocked', 'todo', 'in_progress', 'done')):
        raise ValueError('QA incident card identity drift')
    if incident.get('child_issue_id') not in (None, child['id']):
        raise ValueError('QA incident child changed')
    incident['child_issue_id'] = child['id']
    _set_metadata(cli, child['id'], 'qa_incident_key', key)
    _set_metadata(cli, child['id'], 'qa_source_sha', source_sha)
    _set_metadata(cli, context['issue_id'], 'qa_incident_issue_id', child['id'])
    _block_delivery_gate(private, cli, incident)
    if parent['status'] != 'blocked':
        cli('status', context['issue_id'], 'blocked', '--no-start')
    if child.get('assignee_id') not in (None, techlead_id):
        raise ValueError('QA incident assignee drift')
    if child.get('assignee_id') is None:
        cli('assign', child['id'], '--to-id', techlead_id, '--no-start')
    from portable_qa_evidence import bind
    if budget_ready and not cli('runs', child['id']):
        bind(private, incident, child['id'], techlead_id)
    if child['status'] == 'done':
        if not any(run.get('agent_id') == techlead_id for run in cli('runs', child['id'])):
            raise ValueError('completed QA diagnosis has no Tech Lead execution')
        incident['dispatch'] = 'techlead_started'
        _advance_gate(cli, child['id'], 'techlead_diagnosis')
        save_receipt(path, incident)
        return incident
    if budget_ready:
        current = cli('get', child['id'])
        if current['status'] == 'blocked':
            cli('status', child['id'], 'todo', '--no-start')
        if incident['dispatch'] in ('not_started', 'budget_paused'):
            # A lost CLI response can be reconciled by inspecting task runs.
            runs = cli('runs', child['id'])
            if not any(run.get('agent_id') == techlead_id for run in runs):
                cli('rerun', child['id'])
            incident['dispatch'] = 'techlead_started'
        _advance_gate(cli, child['id'], 'techlead_diagnosis')
    else:
        if incident['dispatch'] != 'techlead_started':
            _advance_gate(cli, child['id'], 'budget_paused')
            incident['dispatch'] = 'budget_paused'
    save_receipt(path, incident)
    return incident
