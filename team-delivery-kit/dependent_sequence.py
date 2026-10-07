"""Durable, two-card dependency gate for the disposable portable pilot.

This operator process never grants worker tools. A successor is dispatched only
after the predecessor's exact merged SHA, CI, board metadata and live QA pass.
"""
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from portable_contract import load as load_contract
from portable_run_spec import validate as validate_run_spec


ROOT = Path(__file__).resolve().parent
PROJECTS = ROOT / 'projects'
NAME = re.compile(r'[a-z0-9][a-z0-9.-]{1,100}\.json\Z')


def protection_transition_allowed(predecessor, successor):
    newly_editable = (set(predecessor['protected_files'])
                      - set(successor['protected_files']))
    return (newly_editable <= set(successor['editable_files'])
            and not newly_editable & set(predecessor['test_files']))


def project_file(name):
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError('invalid sequence file name')
    path = PROJECTS / name
    if path.is_symlink() or not path.is_file() or path.resolve().parent != PROJECTS.resolve():
        raise ValueError('sequence file must be an operator-owned project file')
    return path


def load_plan(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.resolve().parent != PROJECTS.resolve():
        raise ValueError('sequence plan must be an operator-owned project file')
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict) or set(raw) != {'sequence', 'project_config', 'stages'}:
        raise ValueError('invalid sequence plan')
    if not isinstance(raw['sequence'], str) or not re.fullmatch(r'[A-Z][A-Z0-9-]{2,40}', raw['sequence']):
        raise ValueError('invalid sequence identity')
    if not isinstance(raw['stages'], list) or len(raw['stages']) != 2:
        raise ValueError('exactly two stages required')
    project = json.loads(project_file(raw['project_config']).read_text())
    if set(project) != {'repository', 'checkout'}:
        raise ValueError('invalid selected project')
    loaded = []
    digests = [hashlib.sha256(path.read_bytes()).hexdigest(),
               hashlib.sha256(project_file(raw['project_config']).read_bytes()).hexdigest()]
    for index, stage in enumerate(raw['stages']):
        if not isinstance(stage, dict) or set(stage) != {'contract', 'run_spec', 'depends_on'}:
            raise ValueError('invalid stage')
        contract_path, spec_path = project_file(stage['contract']), project_file(stage['run_spec'])
        contract = load_contract(contract_path)
        spec = validate_run_spec(json.loads(spec_path.read_text()), contract)
        if contract['repository'] != project['repository']:
            raise ValueError('stage repository mismatch')
        if stage['depends_on'] != (None if index == 0 else loaded[0]['spec']['label']):
            raise ValueError('dependency graph mismatch')
        loaded.append({'contract': contract, 'spec': spec, 'contract_path': contract_path,
                       'spec_path': spec_path})
        digests.extend(hashlib.sha256(p.read_bytes()).hexdigest() for p in (contract_path, spec_path))
    if loaded[0]['spec']['label'] == loaded[1]['spec']['label'] or \
            loaded[0]['spec']['qa_host_port'] == loaded[1]['spec']['qa_host_port']:
        raise ValueError('stage identities and QA ports must differ')
    predecessor_tests = set(loaded[0]['contract']['editable_files']) & set(loaded[0]['contract']['test_files'])
    if not predecessor_tests or not predecessor_tests <= set(loaded[1]['contract']['protected_files']):
        raise ValueError('successor must freeze predecessor tests')
    # A dependent UI card may legitimately edit an asset frozen during the
    # preceding API card. The successor must explicitly own it, while every
    # test from the predecessor remains frozen. The exact file sets are pinned
    # in the operator-owned sequence plan before either card is dispatched.
    if not protection_transition_allowed(loaded[0]['contract'], loaded[1]['contract']):
        raise ValueError('successor lost protected baseline files or tests')
    return {'name': raw['sequence'], 'project_config': project_file(raw['project_config']),
            'stages': loaded, 'sha256': hashlib.sha256(''.join(digests).encode()).hexdigest()}


def stage_env(base, plan, stage):
    return {**base, 'DELIVERY_KIT_PROJECT_CONFIG': str(plan['project_config']),
            'DELIVERY_KIT_DELIVERY_CONTRACT': str(stage['contract_path']),
            'DELIVERY_KIT_RUN_SPEC': str(stage['spec_path'])}


def read_json(path):
    path = Path(path)
    return json.loads(path.read_text()) if path.is_file() and not path.is_symlink() else None


def receipt_identity(receipt, stage):
    recovered = receipt.get('recovery_parent') if isinstance(receipt, dict) else None
    label_matches = isinstance(receipt, dict) and receipt.get('label') == stage['spec']['label']
    if recovered:
        label_matches = (recovered.get('label') == stage['spec']['label']
                         and recovered.get('issue_id') != receipt.get('issue_id')
                         and ((recovered.get('base_sha') == receipt.get('base_sha')
                               and recovered.get('contract_sha256') == receipt.get('contract_sha256'))
                              or (receipt.get('recovery_kind') == 'qa'
                                  and receipt.get('recovery_origin', {}).get('source_sha') == receipt.get('base_sha')
                                  and receipt.get('recovery_origin', {}).get('contract_sha256') == receipt.get('contract_sha256'))))
    return (isinstance(receipt, dict) and receipt.get('stage') == 'deployed_qa_passed'
            and label_matches
            and isinstance(receipt.get('merge_sha'), str)
            and re.fullmatch(r'[0-9a-f]{40}', receipt['merge_sha'])
            and receipt.get('deployment', {}).get('source_sha') == receipt.get('merge_sha')
            and receipt.get('frozen_tests', {}).get('status') == 'passed'
            and receipt.get('board', {}).get('status') == 'done')


def read_stage_delivery(private, stage, *, _ancestry=()):
    """Resolve an exact published recovery child; never relabel its evidence."""
    private = Path(private)
    label = stage['spec']['label']
    if label in _ancestry or len(_ancestry) > 2:
        raise ValueError('cyclic or excessive recovery ancestry')
    receipt = read_json(private / 'release-receipts' / (label + '.json'))
    if receipt_identity(receipt, stage):
        return receipt
    context = read_json(private / ('portable-context-' + label + '.json'))
    if not context:
        return receipt
    from remediation_parent_delivery import resolve as resolve_remediation
    remediation = resolve_remediation(private, context)
    if remediation is not None:
        if not receipt_identity(remediation, stage):
            raise ValueError('remediation recovered delivery incomplete')
        return remediation
    intent = read_json(private / 'test-revision-recovery' / (context['issue_id'] + '.json'))
    if not intent or intent.get('stage') != 'recovered_by_test_revision':
        qa = read_json(private / 'qa-recoveries' / (context['issue_id'] + '.json'))
        if qa:
            return qa_stage_delivery(private, stage, context, receipt, qa)
        return receipt
    child_label = intent.get('label', '')
    if not re.fullmatch(r'TESTREV[A-F0-9]{12}-1', child_label):
        raise ValueError('invalid recovery child label')
    child = read_json(private / 'release-receipts' / (child_label + '.json'))
    immediate_issue = intent.get('child_issue')
    if not child:
        child_context = read_json(private / ('portable-context-' + child_label + '.json'))
        if (not child_context or child_context.get('issue_id') != immediate_issue
                or child_context.get('label') != child_label
                or child_context.get('base_sha') != context.get('base_sha')
                or child_context.get('contract_sha256') != context.get('contract_sha256')):
            raise ValueError('nested recovery child context drift')
        child = read_stage_delivery(private,
            {**stage, 'spec': {**stage['spec'], 'label': child_label}},
            _ancestry=(*_ancestry, label))
        if not child or child.get('recovery_parent') != child_context:
            raise ValueError('nested recovery child delivery missing')
    else:
        if child.get('issue_id') != immediate_issue or child.get('label') != child_label:
            raise ValueError('recovery child identity drift')
    expected_contract = hashlib.sha256(json.dumps(stage['contract'], sort_keys=True,
                                                 separators=(',', ':')).encode()).hexdigest()
    if (not child or context.get('label') != label
            or intent.get('parent_issue') != context['issue_id']
            or child.get('base_sha') != context.get('base_sha')
            or child.get('contract_sha256') != context.get('contract_sha256')
            or child.get('contract_sha256') != expected_contract
            or child.get('merge_sha') != intent.get('merge_sha')
            or intent.get('parent_board') != {'status': 'done', 'via': 'test_revision_child',
                     'child_issue': immediate_issue, 'merge_sha': child['merge_sha']}
            or child.get('browser_qa', {}).get('status') != 'passed'
            or child.get('browser_qa', {}).get('cleanup') != 'passed'
            or child.get('browser_qa', {}).get('automated') is not True
            or child.get('browser_qa', {}).get('result', {}).get('source_sha') != child.get('merge_sha')
            or child.get('browser_qa', {}).get('identity', {}).get('source_sha') != child.get('merge_sha')):
        raise ValueError('recovery delivery identity or evidence drift')
    result = {**child, 'recovery_parent': context,
              'recovery_links': [{'parent_issue': context['issue_id'],
                                  'child_issue': immediate_issue},
                                 *child.get('recovery_links', [])]}
    if not receipt_identity(result, stage):
        raise ValueError('recovery delivery incomplete')
    return result


def qa_stage_delivery(private, stage, context, failed, proof):
    """A failed merged parent stays cancelled; sequence consumes its proven repair."""
    incident, recovery = proof.get('incident', {}), proof.get('recovery', {})
    key, label = incident.get('key', ''), recovery.get('label', '')
    if (not re.fullmatch(r'[a-f0-9]{16}', key)
            or label != 'QA' + key[:8].upper() + '-1'
            or incident.get('parent_issue_id') != context['issue_id']
            or not failed or failed.get('issue_id') != context['issue_id']
            or failed.get('merge_sha') != incident.get('source_sha')
            or recovery.get('stage') != 'qa_recovered_by_child'):
        raise ValueError('QA recovery lineage drift')
    child = read_json(private / 'release-receipts' / (label + '.json'))
    contract = read_json(private / 'qa-repairs' / (key + '.contract.json'))
    parent = stage['contract']
    if (not child or not contract or child.get('issue_id') != proof.get('child_issue_id')
            or child.get('label') != label or child.get('base_sha') != incident['source_sha']
            or child.get('merge_sha') != recovery.get('merge_sha')
            or child.get('contract_sha256') != hashlib.sha256(json.dumps(contract,
                                sort_keys=True,separators=(',', ':')).encode()).hexdigest()
            or any(contract.get(k) != parent.get(k) for k in
                   ('repository','qa_cases','test_command','test_image','test_roots'))
            or not set(parent['test_files']) <= set(contract['protected_files'])):
        raise ValueError('QA recovery contract or delivery drift')
    config = stage['spec'].get('browser_qa')
    if config:
        browser = child.get('browser_qa', {})
        if (browser.get('status') != 'passed' or browser.get('cleanup') != 'passed'
                or browser.get('automated') is not True
                or browser.get('identity', {}).get('config') != config
                or browser.get('identity', {}).get('source_sha') != child['merge_sha']
                or browser.get('result', {}).get('source_sha') != child['merge_sha']):
            raise ValueError('QA recovery browser proof missing')
    result = {**child, 'recovery_parent': context, 'recovery_kind': 'qa',
              'recovery_origin': {'source_sha': incident['source_sha'],
                                  'contract_sha256': child['contract_sha256']}}
    if not receipt_identity(result, stage):
        raise ValueError('QA recovered delivery incomplete')
    return result


def verify_predecessor(receipt, stage, *, allow_advanced_main=False,
                       require_live_qa=True):
    if not receipt_identity(receipt, stage):
        raise ValueError('predecessor delivery receipt incomplete')
    from portable_qualification import verify_docker_deployment
    deployment = receipt['deployment']
    if require_live_qa:
        verify_docker_deployment(deployment['container'], deployment['url'],
                                 receipt['merge_sha'], stage['contract'])
    from prepare_issue_base import verified_main
    from project_selection import current as selected_project
    current_main = verified_main()
    if current_main != receipt['merge_sha']:
        if not allow_advanced_main or subprocess.run(
                ['git', '-C', str(selected_project()['checkout']), 'merge-base', '--is-ancestor',
                 receipt['merge_sha'], current_main]).returncode:
            raise ValueError('predecessor main or CI identity changed')
    from start_eval import cli
    if receipt.get('recovery_parent'):
        parent = receipt['recovery_parent']['issue_id']
        metadata = cli('metadata', 'list', parent)
        if receipt.get('recovery_kind') == 'qa':
            if (cli('get', parent).get('status') != 'cancelled'
                    or metadata.get('qa_repair_issue_id') != receipt['issue_id']
                    or metadata.get('qa_failed_source_sha') != receipt['base_sha']
                    or metadata.get('qa_repair_merge_sha') != receipt['merge_sha']):
                raise ValueError('QA recovery parent board evidence missing')
        elif receipt.get('recovery_kind') == 'remediation':
            from remediation_parent_delivery import board_fields
            proof = receipt.get('recovery_origin', {})
            if (proof.get('parent_issue') != parent or proof.get('delivery_issue') != receipt['issue_id']
                    or proof.get('merge_sha') != receipt['merge_sha']
                    or cli('get', parent).get('status') != 'done'
                    or any(metadata.get(k) != v for k, v in board_fields(proof).items())):
                raise ValueError('remediation parent board evidence missing')
        else:
            links = receipt.get('recovery_links', [{'parent_issue': parent,
                                                    'child_issue': receipt['issue_id']}])
            if (not isinstance(links, list) or not 1 <= len(links) <= 2
                    or links[0].get('parent_issue') != parent
                    or links[-1].get('child_issue') != receipt['issue_id']
                    or any(a.get('child_issue') != b.get('parent_issue')
                           for a, b in zip(links, links[1:]))):
                raise ValueError('recovery parent lineage missing')
            for link in links:
                origin = link['parent_issue']
                proof = cli('metadata', 'list', origin)
                if (cli('get', origin).get('status') != 'done'
                        or proof.get('test_revision_child_issue') != link['child_issue']
                        or proof.get('recovery_receipt_sha') != receipt['merge_sha']):
                    raise ValueError('recovery parent board evidence missing')
    issue = cli('get', receipt['issue_id'])
    metadata = cli('metadata', 'list', receipt['issue_id'])
    if issue.get('status') != 'done' or metadata.get('delivery_receipt_sha') != receipt['merge_sha']:
        raise ValueError('predecessor board evidence missing')
    pr = json.loads(subprocess.check_output(['gh', 'pr', 'view', str(receipt['pr_number']),
        '-R', stage['contract']['repository'], '--json', 'state,mergeCommit'], text=True))
    if pr.get('state') != 'MERGED' or (pr.get('mergeCommit') or {}).get('oid') != receipt['merge_sha']:
        raise ValueError('predecessor PR identity mismatch')


def run_command(script, env):
    return subprocess.run([sys.executable, str(ROOT / script)], env=env, cwd=ROOT,
                          check=False).returncode


def compiled_card_ids(private, plan):
    """Use controller-owned compiled IDs, never a paginated title search."""
    name = plan['name'].removesuffix('-DELIVERY')
    receipt = read_json(Path(private) / 'compiled-plans' / (name + '.json'))
    if receipt is None:
        return None  # preserved legacy, operator-seeded sequences
    cards = receipt.get('cards') or {}
    if (receipt.get('stage') != 'generated_not_dispatched' or set(cards) != {'C1', 'C2'}
            or len(set(cards.values())) != 2
            or any(not isinstance(v, str) or not re.fullmatch(r'[0-9a-f-]{36}', v) for v in cards.values())):
        raise ValueError('compiled card receipt identity drift')
    artifacts = receipt.get('artifacts') or {}
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    for stage in plan['stages']:
        for key, value in (('contract_path', stage['contract']), ('spec_path', stage['spec'])):
            if artifacts.get(stage[key].name) != digest(value):
                raise ValueError('compiled stage artifact drift')
    sequence = {'sequence': plan['name'], 'project_config': plan['project_config'].name,
                'stages': [{'contract': s['contract_path'].name, 'run_spec': s['spec_path'].name,
                            'depends_on': None if i == 0 else plan['stages'][0]['spec']['label']}
                           for i, s in enumerate(plan['stages'])]}
    if digest(sequence) not in [value for key, value in artifacts.items() if key.endswith('.sequence.json')]:
        raise ValueError('compiled dependency artifact drift')
    return cards


def activate_compiled_cards(private, plan, cards, cli):
    """Promote verified compilation to the EXISTING planned-dispatch contract."""
    if not cards:
        return None
    receipt = read_json(Path(private) / 'compiled-plans' /
                        (plan['name'].removesuffix('-DELIVERY') + '.json'))
    sha = receipt['plan_sha256']
    pending = []
    for index, stage in enumerate(plan['stages']):
        if read_json(Path(private) / ('portable-context-' + stage['spec']['label'] + '.json')):
            continue  # never reset a dispatched card
        ident = cards['C' + str(index + 1)]
        item, meta = cli('get', ident), cli('metadata', 'list', ident)
        if (item.get('title') != stage['spec']['title']
                or item.get('description') != stage['spec']['description']
                or item.get('status') not in ('blocked', 'todo')
                or item.get('assignee_id') is not None or cli('runs', ident)
                or meta.get('planning_sha256') != sha
                or meta.get('execution_gate') not in ('awaiting_bootstrap_contract', 'awaiting_generated_contract')):
            raise ValueError('compiled planned-dispatch precondition drift')
        pending.append((ident, item, meta))
    for ident, item, meta in pending:
        if meta['execution_gate'] == 'awaiting_bootstrap_contract':
            cli('metadata', 'set', ident, '--key', 'execution_gate',
                '--value', 'awaiting_generated_contract', '--type', 'string')
        # Planned dispatch itself atomically releases the blocked native card
        # after base registration, unlike legacy operator-seeded todo cards.
        if item['status'] == 'todo':
            cli('status', ident, 'blocked', '--no-start')
        if (cli('get', ident)['status'] != 'blocked'
                or cli('metadata', 'list', ident).get('execution_gate') != 'awaiting_generated_contract'):
            raise ValueError('compiled planned-dispatch promotion unconfirmed')
    return sha


def reconcile_compiled_predispatch(ledger, plan, cards, cli, *, no_context=True):
    """Recover one pre-dispatch identity failure only if neither card ran."""
    category = str(ledger.get('category', ''))
    dispatch = category == 'RuntimeError:stage dispatch failed: ' + plan['stages'][0]['spec']['label']
    field = 'compiled_dispatch_reconciliation' if dispatch else 'compiled_predispatch_reconciliation'
    expected = {s['spec']['label']: cards['C' + str(i + 1)] for i, s in enumerate(plan['stages'])} if cards else {}
    if (not cards or not no_context or ledger.get('stage') != 'blocked'
            or ledger.get('completed') != [] or ledger.get(field)
            or (dispatch and (ledger.get('active') != plan['stages'][0]['spec']['label']
                              or ledger.get('issues') != expected))
            or (not dispatch and (ledger.get('active') is not None or ledger.get('issues')
                                  or not category.startswith('CalledProcessError:')))):
        return None
    for index, stage in enumerate(plan['stages']):
        ident = cards['C' + str(index + 1)]
        item = cli('get', ident)
        if (item.get('title') != stage['spec']['title']
                or item.get('description') != stage['spec']['description']
                or item.get('status') != 'blocked' or item.get('assignee_id') is not None
                or cli('runs', ident)):
            raise ValueError('compiled pre-dispatch card identity or activity drift')
    revised = {**ledger, 'stage': 'planned', 'active': None, field: {
        'prior_category': ledger['category'], 'cards': cards,
        'both_unassigned_without_runs': True, 'delivery_approved': False}}
    for field in ('category', 'owner', 'next_action'):
        revised.pop(field, None)
    return revised


def ensure_cards(plan, cli, issue, ledger, save_receipt, ledger_path, *, pinned_cards=None):
    first, second = (stage['spec'] for stage in plan['stages'])
    if pinned_cards:
        predecessor, successor = (cli('get', pinned_cards[key]) for key in ('C1', 'C2'))
        for card, spec in ((predecessor, first), (successor, second)):
            if card.get('title') != spec['title'] or card.get('description') != spec['description']:
                raise ValueError('compiled native card identity drift')
    else:
        predecessor = issue(first['title'], first['description'])
        matches = [card for card in cli('list')['issues'] if card['title'] == second['title']]
        if len(matches) > 1:
            raise ValueError('duplicate dependent card')
        if matches:
            successor = matches[0]
            if successor['description'] != second['description']:
                raise ValueError('dependent card description drift')
        else:
            successor = cli('create', '--title', second['title'], '--description',
                            second['description'], '--status', 'blocked')
    expected = {first['label']: predecessor['id'], second['label']: successor['id']}
    if ledger.get('issues') and ledger['issues'] != expected:
        raise ValueError('sequence issue identities changed')
    ledger['issues'] = expected
    save_receipt(ledger_path, ledger)
    for card_id, fields in ((predecessor['id'], {'sequence': plan['name']}),
                            (successor['id'], {'sequence': plan['name'],
                             'depends_on_issue_id': predecessor['id']})):
        existing = cli('metadata', 'list', card_id)
        for key, value in fields.items():
            if key in existing and existing[key] != value:
                raise ValueError('dependency metadata drift')
            if key not in existing:
                cli('metadata', 'set', card_id, '--key', key, '--value', value,
                    '--type', 'string')
    return expected


def release_first_card(cli, card_id):
    card = cli('get', card_id)
    if card.get('assignee_id') is not None or card.get('status') not in ('blocked', 'todo'):
        raise ValueError('first planned card changed before release')
    if card['status'] == 'blocked':
        cli('status', card['id'], 'todo', '--no-start')


def verify_recovery_ci(receipt, stage):
    repository = stage['contract']['repository']
    match = re.fullmatch(re.escape('https://github.com/' + repository + '/actions/runs/')
                         + r'([0-9]+)', receipt.get('main_ci_run', ''))
    if not match:
        raise ValueError('exact recovery CI run required')
    run = json.loads(subprocess.check_output(['gh', 'run', 'view', match[1], '-R', repository,
                    '--json', 'status,conclusion,headSha'], text=True))
    if (run.get('status') != 'completed' or run.get('conclusion') != 'success'
            or run.get('headSha') != receipt['merge_sha']):
        raise ValueError('recovery CI did not pass at exact merged SHA')


def resume_verified_recovery(ledger, plan, private, *, read_delivery=read_stage_delivery,
                             verify=verify_predecessor, verify_ci=verify_recovery_ci):
    """Only a delivered, identity-bound recovery resolves a blocked stage.

    No worker existence, free-form agent message or retry request can resume it.
    Verification runs before ledger mutation; the old incident is retained.
    """
    if ledger.get('stage') != 'blocked' or ledger.get('plan_sha256') != plan['sha256']:
        return None
    label = ledger.get('active')
    labels = [s['spec']['label'] for s in plan['stages']]
    if label not in labels or not str(ledger.get('category', '')).startswith('RuntimeError:'):
        return None
    index = labels.index(label)
    if ledger.get('completed') != labels[:index]:
        return None
    stage = plan['stages'][index]
    receipt = read_delivery(private, stage)
    if (not receipt_identity(receipt, stage) or not receipt.get('recovery_parent')
            or receipt['recovery_parent'].get('issue_id') != ledger.get('issues', {}).get(label)):
        return None
    verify(receipt, stage, allow_advanced_main=False, require_live_qa=True)
    verify_ci(receipt, stage)
    event = {'stage_label': label, 'category': ledger['category'], 'owner': ledger.get('owner'),
             'next_action': ledger.get('next_action'), 'recovered_issue': receipt['issue_id'],
             'merge_sha': receipt['merge_sha'], 'pr_url': receipt['pr_url'], 'at': time.time()}
    resumed = {**ledger, 'stage': 'stage_complete', 'active': None,
               'completed': [*ledger['completed'], label],
               'resolved_incidents': [*ledger.get('resolved_incidents', []), event], 'updated_at': time.time()}
    for key in ('category', 'owner', 'next_action', 'board_notification_error'):
        resumed.pop(key, None)
    return resumed


def resolve_delivered_incident(ledger, stage, receipt, *, verify=verify_predecessor):
    """Clear current fault fields only after verifying the exact delivered stage.

    Resuming supervision does not resolve an incident; deployed evidence does.
    Preserve both the fault and supervision history in the durable ledger.
    """
    if not ledger.get('category'):
        return ledger
    label=stage['spec']['label']
    if (ledger.get('stage') not in ('stage_complete','done')
            or label not in ledger.get('completed',[])
            or ledger.get('active') is not None or not receipt_identity(receipt,stage)):
        raise ValueError('delivered stage identity required before resolving incident')
    verify(receipt,stage,allow_advanced_main=True,require_live_qa=True)
    event=dict(stage_label=label,category=ledger['category'],owner=ledger.get('owner'),
        next_action=ledger.get('next_action'),merge_sha=receipt['merge_sha'],
        pr_url=receipt['pr_url'],status='resolved_by_verified_delivery',at=time.time())
    result={**ledger,'resolved_incidents':[*ledger.get('resolved_incidents',[]),event]}
    for field in ('category','owner','next_action','board_notification_error'):
        result.pop(field,None)
    return result


def read_review_context_recovery(context):
    script = '''import broker as b,json,native,review_context_recovery as recovery,sys
issue=sys.argv[1];s=json.loads((b.STATE/'native.json').read_text())
with b.db() as c:
 row=c.execute('SELECT * FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(issue,)).fetchone()
 route_row=c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
 if not row or not route_row:print('null');sys.exit()
 d=json.loads(row['data']);r=json.loads(route_row[0]);repair=d.get('review_context_recovery') or {};used=d.get('review_context_recovery_used') or {}
 qualified=recovery.qualified(c,issue,row['source_task'],d)
 presentation=c.execute('SELECT receipt FROM review_context_presentations WHERE task_id=?',(d.get('recipient_task'),)).fetchone() if c.execute("SELECT 1 FROM sqlite_master WHERE name='review_context_presentations'").fetchone() else None
 presentation=json.loads(presentation[0]) if presentation else {}
 context_presentation=c.execute('SELECT receipt FROM execution_context_presentations WHERE task_id=?',(d.get('recipient_task'),)).fetchone() if c.execute("SELECT 1 FROM sqlite_master WHERE name='execution_context_presentations'").fetchone() else None
 context_presentation=json.loads(context_presentation[0]) if context_presentation else {}
runs=native.issue_task_runs(s,issue)
author=next((x for x in runs if x['id']==row['source_task']),{})
cto=next((x for x in runs if x['id']==used.get('cto_task')),{});
review=next((x for x in runs if x['id']==d.get('recipient_task')),{})
print(json.dumps(dict(issue_id=issue,enabled=r.get('enabled'),contract_sha256=r.get('contract_sha256'),
 qualified=qualified,stage=row['stage'],source_task=row['source_task'],source_status=author.get('status'),
 source_agent=author.get('agent_id'),author=r.get('author'),reviewer=r.get('reviewer'),cto=r.get('cto'),
 request=repair.get('request'),approval=repair.get('approval'),manifest_sha256=d.get('evidence',{}).get('manifest_sha256'),
 baseline_tests_intact=d.get('evidence',{}).get('baseline_tests_intact'),review_retries=d.get('review_retries'),
 cto_task=cto.get('id'),cto_status=cto.get('status'),cto_agent=cto.get('agent_id'),cto_wakeup=cto.get('wakeup_id'),
 used=used,review_task=review.get('id'),review_agent=review.get('agent_id'),review_status=review.get('status'),
 review_wakeup=review.get('wakeup_id'),wakeup=d.get('wakeup_id'),presentation=presentation,
 context_presentation=context_presentation,repair_context_sha256=repair.get('presentation',{}).get('context_sha256'))))'''
    from evalctl import PROJECT
    return json.loads(subprocess.check_output(['docker','exec','-e','PYTHONPATH=/',
        PROJECT+'-execution-broker-1','python','-c',script,context['issue_id']],text=True))


def verify_initial_review_base(context, stage):
    from prepare_issue_base import verified_main
    if verified_main() != context.get('base_sha'):
        raise ValueError('initial review recovery base or required CI drift')


def resume_verified_review_context(ledger, plan, private, *, read_proof=read_review_context_recovery,
                                  read_delivery=read_stage_delivery, verify=verify_predecessor,
                                  verify_ci=verify_recovery_ci, verify_initial=verify_initial_review_base):
    """Supervise a fresh qualified review, never infer delivery from activity."""
    labels=[s['spec']['label'] for s in plan['stages']];label=ledger.get('active')
    if (ledger.get('stage')!='blocked' or ledger.get('plan_sha256')!=plan['sha256']
            or ledger.get('category')!='RuntimeError:technical_decision_required:recipient_execution_failed'
            or label not in labels):return None
    index=labels.index(label)
    if ledger.get('completed')!=labels[:index]:return None
    stage=plan['stages'][index];context=read_json(Path(private)/('portable-context-'+label+'.json'))
    contract_sha=hashlib.sha256(json.dumps(stage['contract'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if (not context or context.get('label')!=label or context.get('issue_id')!=ledger.get('issues',{}).get(label)
            or not context.get('durable_handoffs') or context.get('contract_sha256')!=contract_sha):return None
    p=read_proof(context) or {};req=p.get('request') or {};used=p.get('used') or {};presentation=p.get('presentation') or {}
    capsule=stage['spec'].get('execution_context')
    capsule_presentation=False
    if capsule is not None:
        from execution_context import validate
        validate(capsule)
        cp=p.get('context_presentation') or {}
        spec_sha=hashlib.sha256(json.dumps(stage['spec'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        capsule_presentation=(context.get('run_spec_sha256')==spec_sha
            and p.get('repair_context_sha256')==capsule['sha256']
            and cp.get('issue_id')==context['issue_id'] and cp.get('task_id')==p.get('review_task')
            and cp.get('agent_id')==p.get('reviewer') and cp.get('mode')=='review'
            and cp.get('context_sha256')==capsule['sha256'] and cp.get('delivery_approval') is False)
    legacy_presentation=(presentation.get('operation')=='registered_review_presentation_v1'
        and presentation.get('approval') is False and presentation.get('source_task')==p.get('source_task')
        and presentation.get('issue_id')==context['issue_id'] and presentation.get('wakeup_id')==p.get('wakeup')
        and presentation.get('manifest_sha256')==p.get('manifest_sha256'))
    if index==0 and not capsule_presentation:return None
    if (p.get('qualified') is not True or p.get('enabled') is not True or p.get('approval') is not False
            or p.get('issue_id')!=context['issue_id'] or p.get('contract_sha256')!=contract_sha
            or p.get('stage') not in ('awaiting_acceptance','accepted','approved')
            or p.get('source_status')!='completed' or p.get('source_agent')!=p.get('author')
            or len({p.get('author'),p.get('reviewer'),p.get('cto')})!=3
            or not all(p.get(k) for k in ('author','reviewer','cto','source_task','cto_task','review_task','wakeup'))
            or req.get('issue_id')!=context['issue_id'] or req.get('source_task')!=p['source_task']
            or p.get('review_retries')!=1 or p.get('baseline_tests_intact') is not True
            or p.get('cto_status')!='completed' or p.get('cto_agent')!=p['cto']
            or used.get('cto_task')!=p['cto_task'] or used.get('cto_wakeup')!=p.get('cto_wakeup')
            or used.get('decision',{}).get('action')!='retry_review' or used.get('decision',{}).get('optional_files')!=[]
            or p.get('review_agent')!=p['reviewer'] or p.get('review_status') not in ('running','completed')
            or p.get('review_task') in (req.get('failed_review'),p['source_task'],p['cto_task'])
            or p.get('review_wakeup')!=p['wakeup']
            or not (capsule_presentation or legacy_presentation)
            or not re.fullmatch('[a-f0-9]{64}',str(p.get('manifest_sha256','')))):return None
    if index==0:
        verify_initial(context,stage)
    else:
        prior_stage=plan['stages'][index-1];receipt=read_delivery(private,prior_stage)
        if not receipt_identity(receipt,prior_stage) or receipt.get('merge_sha')!=context.get('base_sha'):return None
        verify(receipt,prior_stage,allow_advanced_main=False,require_live_qa=True);verify_ci(receipt,prior_stage)
    event=dict(category=ledger['category'],stage_label=label,source_task=p['source_task'],
        cto_task=p['cto_task'],review_task=p['review_task'],status='supervision_resumed_not_delivered',at=time.time())
    return {**ledger,'stage':'working','updated_at':time.time(),
            'recovery_supervision':[*ledger.get('recovery_supervision',[]),event]}


def read_active_test_correction(context):
    """Read only identity/status fields from controller-owned correction state."""
    script = '''import broker as b,json,native,sys
s=json.loads((b.STATE/'native.json').read_text()); issue=sys.argv[1]
with b.db() as c:
 row=c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
 route=json.loads(row[0]) if row else {}
 rows=c.execute('SELECT source_task,stage,data FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC',(issue,)).fetchall()
latest=rows[0]['stage'] if rows else None
runs=native.issue_task_runs(s,issue)
proof=None
for row in rows:
 d=json.loads(row['data']); provider=d.get('provider_recovery') or {}
 transport=d.get('integration_recovery') or d.get('transport_recovery') or {}
 repair=transport or provider.get('artifact_contract') or d.get('artifact_recovery') or {}; req=repair.get('request') or {}
 wake=d.get('artifact_recovery_wakeup') if repair else d.get('test_first_correction_wakeup')
 source=next((r for r in runs if r['id']==(transport.get('original_source') or (provider.get('original_source') if provider else row['source_task']))),{})
 cto=next((r for r in runs if r['id']==(transport.get('cto_task') if transport else req.get('cto_task') if repair else d.get('cto_task'))),{})
 candidates=[r for r in runs if wake and r.get('wakeup_id')==wake and r.get('agent_id')==route.get('author')]
 if len(candidates)!=1:continue
 task=candidates[0]
 infra=d.get('infrastructure_replan') or {}
 if infra:
  import pre_red_infra_replan
  with b.db() as c: qualified=pre_red_infra_replan.qualified(c,issue,row['source_task'],d)
  infra={k:infra.get(k) for k in ('operation','request','proof','prompt_presentation','author_retry_authorized')}
  infra['qualified']=qualified
 proof={'issue_id':issue,'enabled':route.get('enabled'),'test_first':route.get('test_first'),
  'author':route.get('author'),'cto':route.get('cto'),'latest_stage':latest,
  'source_task':source.get('id'),'source_agent':source.get('agent_id'),'source_status':source.get('status'),
  'source_error':source.get('error'),'infrastructure_contract':infra or None,
  'cto_task':cto.get('id'),'cto_agent':cto.get('agent_id'),'cto_status':cto.get('status'),
  'decision':repair.get('decision') if repair else d.get('decision'),
  'diagnostic':repair.get('diagnostic') if repair else d.get('diagnostic'),
  'artifact_contract':{'request':req,'contract':repair.get('contract'),'contract_sha256':repair.get('contract_sha256')} if repair and not transport else None,
  'transport_contract':{k:transport.get(k) for k in ('request','kind','diagnostic_sha256','repair_kind','original_source','pretool_verified','postread_verified','recovery_policy','activity','failed_snapshot')} if transport else None,
  'structural_contract':{k:d['structural_replan'].get(k) for k in ('request','kind','diagnostic_sha256')} if d.get('structural_replan') else None,
  'correction_task':task['id'],'correction_status':task.get('status'),'wakeup':wake}
 break
print(json.dumps(proof))'''
    from evalctl import PROJECT
    return json.loads(subprocess.check_output(['docker', 'exec', '-e', 'PYTHONPATH=/',
        PROJECT + '-execution-broker-1', 'python', '-c', script, context['issue_id']], text=True))


def resume_verified_test_correction(ledger, plan, private, *, read_proof=read_active_test_correction,
                                   read_delivery=read_stage_delivery, verify=verify_predecessor,
                                   verify_ci=verify_recovery_ci):
    """Resume supervision, NOT completion, of an already-dispatched CTO correction."""
    labels = [s['spec']['label'] for s in plan['stages']]
    label = ledger.get('active')
    if (ledger.get('stage') != 'blocked' or ledger.get('plan_sha256') != plan['sha256']
            or label not in labels or ledger.get('category') not in (
            'RuntimeError:technical_decision_required:ValueError:test-first snapshot rejected',
            'RuntimeError:technical_decision_required:ValueError:test-first NEW test has no executable test methods',
            'RuntimeError:test_first_blocked:test_first_correction_failed_after_cto_diagnosis',
            'RuntimeError:test_first_blocked:test_first_cto_requires_replanning',
            'RuntimeError:technical_decision_required:ValueError:test-first NEW test is empty')):
        return None
    index = labels.index(label)
    if index == 0 or ledger.get('completed') != labels[:index]:
        return None
    stage = plan['stages'][index]
    context = read_json(Path(private) / ('portable-context-' + label + '.json'))
    contract_sha = hashlib.sha256(json.dumps(stage['contract'], sort_keys=True,
                                separators=(',', ':')).encode()).hexdigest()
    if (not context or context.get('issue_id') != ledger.get('issues', {}).get(label)
            or context.get('label') != label or context.get('contract_sha256') != contract_sha
            or not context.get('durable_handoffs')):
        return None
    proof = read_proof(context)
    if not proof:
        return None
    if ledger.get('category')=='RuntimeError:test_first_blocked:test_first_cto_requires_replanning':
        from generated_context import compact
        _, presentation=compact(stage['spec']['description'])
        infra=proof.get('infrastructure_contract') or {}
        request=infra.get('request') or {}
        preserved=infra.get('proof') or {}
        diagnostic=proof.get('diagnostic') or {}
        decision=proof.get('decision') or {}
        if (not presentation or presentation['effective_characters']>4000
                or infra.get('qualified') is not True
                or infra.get('operation')!='preserved_pretool_infrastructure_diagnosis_v1'
                or infra.get('author_retry_authorized') is not False
                or infra.get('prompt_presentation')!=presentation
                or request.get('issue_id')!=context['issue_id']
                or request.get('source_task')!=proof.get('source_task')
                or request.get('cto_task')==proof.get('cto_task')
                or preserved.get('verified') is not True or preserved.get('baseline_unchanged') is not True
                or not re.fullmatch('[a-f0-9]{64}',str(preserved.get('manifest_sha256','')))
                or proof.get('issue_id')!=context['issue_id'] or proof.get('enabled') is not True
                or proof.get('test_first') is not True or not proof.get('author') or proof.get('author')==proof.get('cto')
                or proof.get('source_agent')!=proof['author'] or proof.get('source_status')!='failed'
                or 'restricted broker stream failed: native_prompt_bounds' not in (proof.get('source_error') or '')
                or proof.get('cto_agent')!=proof.get('cto') or proof.get('cto_status')!='completed'
                or decision.get('action')!='request_correction' or decision.get('optional_files')!=[]
                or not proof.get('correction_task') or not proof.get('wakeup')
                or proof.get('correction_task')==proof.get('source_task')
                or proof.get('correction_status') not in ('queued','running','completed')
                or proof.get('latest_stage') not in ('test_first_cto_correction_wait','test_author_active',
                    'awaiting_test_revision_review','awaiting_implementation','approved','author_active','accepted')
                or diagnostic.get('category')!='native_prompt_bounds'
                or diagnostic.get('task_id')!=proof.get('source_task')
                or diagnostic.get('issue_id')!=context['issue_id']
                or diagnostic.get('baseline_unchanged') is not True or diagnostic.get('accepted_tools')!=0):
            return None
        prior_stage=plan['stages'][index-1]
        receipt=read_delivery(private,prior_stage)
        if not receipt_identity(receipt,prior_stage) or receipt.get('merge_sha')!=context.get('base_sha'):
            return None
        verify(receipt,prior_stage,allow_advanced_main=False,require_live_qa=True)
        verify_ci(receipt,prior_stage)
        event={'stage_label':label,'category':ledger['category'],'source_task':proof['source_task'],
               'cto_task':proof['cto_task'],'correction_task':proof['correction_task'],
               'status':'supervision_resumed_not_delivered','at':time.time()}
        return {**ledger,'stage':'working','updated_at':time.time(),
                'recovery_supervision':[*ledger.get('recovery_supervision',[]),event]}
    diagnostic = proof.get('diagnostic') or {}
    files = diagnostic.get('files') or {}
    decision = proof.get('decision') or {}
    artifact = proof.get('artifact_contract')
    structural = proof.get('structural_contract')
    transport = proof.get('transport_contract')
    if (ledger.get('category') == 'RuntimeError:test_first_blocked:test_first_correction_failed_after_cto_diagnosis'
            and (not transport or transport.get('repair_kind') not in
                 ('pre_tool_read_schema_repair_v1','post_read_compact_write_replan_v1'))):
        return None
    if transport:
        from broker.artifact_transport_recovery import validate_probe
        request = transport.get('request') or {}
        probe = request.get('probe') or {}
        compact = transport.get('repair_kind') == 'post_read_compact_write_replan_v1'
        integration = compact or transport.get('repair_kind') == 'pre_tool_read_schema_repair_v1'
        try:
            validate_probe(probe, probe.get('worker_image'))
        except (ValueError, KeyError, TypeError, AttributeError):
            return None
        if (transport.get('kind') != 'qualified_acp_response_enforcement_v1'
                or request.get('issue_id') != context['issue_id']
                or (transport.get('original_source') if integration else request.get('source_task')) != proof.get('source_task')
                or integration and ((transport.get('postread_verified') if compact else transport.get('pretool_verified')) is not True
                    or request.get('source_task') == transport.get('original_source')
                    or not re.fullmatch(r'[0-9a-f-]{36}', str(request.get('source_task', ''))))
                or transport.get('diagnostic_sha256') != hashlib.sha256(
                    json.dumps(diagnostic, sort_keys=True).encode()).hexdigest()):
            return None
        if compact:
            policy = transport.get('recovery_policy') or {}
            activity = transport.get('activity') or {}
            snapshot = transport.get('failed_snapshot') or {}
            failure = request.get('failure') or {}
            if (transport.get('pretool_verified') is not False
                    or policy != {'first_write_max_characters':6144, 'incremental_full_coverage':True,
                                  'truncation_proven':False, 'same_class_attempt_limit':1}
                    or activity.get('write_file_call_count') != 0
                    or activity.get('tool_result_counts', {}).get('read_file:read_returned', 0) < 1
                    or snapshot.get('verified') is not True or snapshot.get('baseline_unchanged') is not True
                    or snapshot.get('task_id') != request.get('source_task')
                    or failure.get('selected_tool') != 'write_file'
                    or failure.get('completion_tokens') != 8192 or failure.get('output_limit') != 8192):
                return None
    if structural:
        request = structural.get('request') or {}
        if (structural.get('kind') != 'nonempty_no_methods_cto_replan_v1'
                or request.get('issue_id') != context['issue_id']
                or request.get('source_task') != proof.get('source_task')
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', str(request.get('worker_image', '')))
                or diagnostic.get('category') != 'new_test_no_methods'
                or structural.get('diagnostic_sha256') != hashlib.sha256(
                    json.dumps(diagnostic, sort_keys=True).encode()).hexdigest()):
            return None
    if artifact:
        request = artifact.get('request') or {}
        if (artifact.get('contract') != 'observed-source-read-verified-test-write-v1'
                or not re.fullmatch(r'[0-9a-f]{64}', str(artifact.get('contract_sha256', '')))
                or request.get('issue_id') != context['issue_id']
                or request.get('source_task') != proof.get('source_task')
                or request.get('cto_task') != proof.get('cto_task')
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', str(request.get('worker_image', '')))):
            return None
    if (ledger.get('category').endswith('NEW test is empty') and not artifact and not structural):
        return None
    if ledger.get('category').endswith('no executable test methods') and not (structural or transport):
        return None
    if (proof.get('issue_id') != context['issue_id'] or proof.get('enabled') is not True
            or proof.get('test_first') is not True or proof.get('author') == proof.get('cto')
            or not proof.get('author') or not proof.get('cto')
            or proof.get('source_agent') != proof['author'] or proof.get('source_status') != 'completed'
            or proof.get('cto_agent') != proof['cto'] or proof.get('cto_status') != 'completed'
            or not proof.get('cto_task') or not proof.get('wakeup') or not proof.get('correction_task')
            or proof.get('correction_task') == proof.get('source_task')
            or proof.get('correction_status') not in ('queued', 'running', 'completed')
            or proof.get('latest_stage') not in ('test_first_cto_correction_wait', 'test_author_active',
                    'test_first_artifact_recovery_wait', 'test_first_provider_recovery_wait',
                    'test_first_transport_recovery_wait',
                    'test_first_integration_recovery_wait',
                    'awaiting_test_revision_review', 'awaiting_implementation', 'approved')
            or set(decision) != {'action', 'reason', 'optional_files'}
            or decision.get('action') != 'request_correction' or decision.get('optional_files') != []
            or not isinstance(decision.get('reason'), str) or not 1 <= len(decision['reason']) <= 3000
            or diagnostic.get('kind') != 'rejected_snapshot'
            or diagnostic.get('category') != ('new_test_no_methods' if structural or transport else 'empty_new_test')
            or diagnostic.get('issue_id') != context['issue_id']
            or diagnostic.get('task_id') != proof.get('source_task')
            or not isinstance(files, dict) or not files
            or any(not isinstance(f, dict) or (not (type(f.get('bytes')) is int and 0 < f['bytes'] <= 32768)
                   or not re.fullmatch(r'[0-9a-f]{64}',str(f.get('sha256',''))) if structural or transport
                   else f.get('bytes') != 0 or f.get('sha256') != hashlib.sha256(b'').hexdigest()) for f in files.values())):
        return None
    prior_stage = plan['stages'][index - 1]
    receipt = read_delivery(private, prior_stage)
    if not receipt_identity(receipt, prior_stage) or receipt.get('merge_sha') != context.get('base_sha'):
        return None
    verify(receipt, prior_stage, allow_advanced_main=False, require_live_qa=True)
    verify_ci(receipt, prior_stage)
    event = {'stage_label': label, 'category': ledger['category'],
             'source_task': proof['source_task'], 'cto_task': proof['cto_task'],
             'correction_task': proof['correction_task'], 'wakeup': proof['wakeup'],
             'proof_sha256': hashlib.sha256(json.dumps(proof, sort_keys=True).encode()).hexdigest(),
             'status': 'supervision_resumed_not_delivered', 'at': time.time()}
    return {**ledger, 'stage': 'working', 'updated_at': time.time(),
            'recovery_supervision': [*ledger.get('recovery_supervision', []), event]}


def reconcile_compiled_successor_dispatch(ledger, plan, cards, cli, private, *,
        read_delivery=read_stage_delivery, identity=receipt_identity,
        verify=verify_predecessor, verify_ci=verify_recovery_ci):
    """One never-started successor retry, with its predecessor revalidated."""
    if not cards or len(plan['stages']) != 2:
        return None
    first, second = plan['stages']
    label = second['spec']['label']
    expected = {first['spec']['label']: cards['C1'], label: cards['C2']}
    context = Path(private) / ('portable-context-' + label + '.json')
    if (ledger.get('stage') != 'blocked' or ledger.get('active') != label
            or ledger.get('completed') != [first['spec']['label']]
            or ledger.get('issues') != expected
            or ledger.get('category') != 'RuntimeError:stage dispatch failed: ' + label
            or ledger.get('compiled_successor_dispatch_reconciliation')
            or context.exists() or context.is_symlink()):
        return None
    item = cli('get', cards['C2'])
    if (item.get('title') != second['spec']['title']
            or item.get('description') != second['spec']['description']
            or item.get('status') != 'blocked' or item.get('assignee_id') is not None
            or cli('runs', cards['C2'])):
        raise ValueError('compiled successor identity or activity drift')
    receipt = read_delivery(private, first)
    if not identity(receipt, first):
        raise ValueError('compiled successor needs qualified predecessor')
    verify(receipt, first, allow_advanced_main=False, require_live_qa=True)
    verify_ci(receipt, first)
    revised = {**ledger, 'stage': 'planned', 'active': None,
        'compiled_successor_dispatch_reconciliation': {
            'prior_category': ledger['category'], 'card': cards['C2'],
            'predecessor_sha': receipt['merge_sha'],
            'unassigned_without_runs': True, 'delivery_approved': False}}
    for field in ('category', 'owner', 'next_action'):
        revised.pop(field, None)
    return revised


def supervise_recovery_publication(ledger,plan,private,cli,instance):
    """Supervise a real approved recovery without resuming the failed author."""
    if ledger.get('stage')!='blocked' or ledger.get('plan_sha256')!=plan['sha256']:return None
    from remediation_publication_schedule import reconcile as supervise_publication
    labels=[s['spec']['label'] for s in plan['stages']]
    if ledger.get('active') not in labels:return None
    index=labels.index(ledger['active']);current_stage=plan['stages'][index]
    context=read_json(Path(private)/('portable-context-'+ledger['active']+'.json'))
    if (not context or context.get('issue_id')!=ledger.get('issues',{}).get(ledger['active'])
            or ledger.get('completed')!=labels[:index]):return None
    publication=supervise_publication(private,current_stage,context,plan['project_config'],instance=instance)
    if publication:
        projection={k:publication[k] for k in ('stage','owner','category','attention_required') if k in publication}
        if publication.get('stage')=='blocked':
            from r3_incident_runtime import supervise as supervise_incident
            incident=supervise_incident(private,context,publication,instance=instance,contract=current_stage['contract'])
            if incident:
                projection['incident']={k:incident[k] for k in
                    ('stage','owner','category','incident_sha256','issue_id','attention_required','experiment') if k in incident}
        metadata=cli('metadata','list',context['issue_id'])
        value=json.dumps(projection,sort_keys=True,separators=(',',':'))
        if metadata.get('remediation_publication_status')!=value:
            cli('metadata','set',context['issue_id'],'--key','remediation_publication_status',
                '--value',value,'--type','string')
    return publication


def run_sequence():
    selected = os.environ.get('DELIVERY_KIT_SEQUENCE_PLAN')
    if not selected:
        raise ValueError('DELIVERY_KIT_SEQUENCE_PLAN required')
    plan = load_plan(selected)
    os.environ['DELIVERY_KIT_PROJECT_CONFIG'] = str(plan['project_config'])
    from evalctl import PRIVATE, PROJECT
    from release_eval import save_receipt
    from start_eval import check_model_budget, cli, issue
    if PROJECT != 'delivery-kit-port2':
        raise ValueError('dependent pilot restricted to isolated port2 installation')
    ledger_path = PRIVATE / 'dependent-sequences' / (plan['name'] + '.json')
    ledger = read_json(ledger_path)
    if ledger and ledger.get('plan_sha256') != plan['sha256']:
        raise ValueError('dependent plan changed after start')
    if not ledger:
        budget = check_model_budget()
        if budget['remaining'] < 64:
            raise ValueError('two-card sequence requires 64 reserved model calls before dispatch')
        ledger = {'sequence': plan['name'], 'plan_sha256': plan['sha256'],
                  'stage': 'planned', 'completed': []}
        save_receipt(ledger_path, ledger)
    pinned_cards = compiled_card_ids(PRIVATE, plan)
    expected_plan_sha = activate_compiled_cards(PRIVATE, plan, pinned_cards, cli)
    no_context = all(not read_json(PRIVATE / ('portable-context-' + s['spec']['label'] + '.json'))
                     for s in plan['stages'])
    reconciled = reconcile_compiled_predispatch(ledger, plan, pinned_cards, cli, no_context=no_context)
    if reconciled:
        ledger = reconciled
        save_receipt(ledger_path, ledger)
    reconciled = reconcile_compiled_successor_dispatch(ledger, plan, pinned_cards, cli, PRIVATE)
    if reconciled:
        ledger = reconciled
        save_receipt(ledger_path, ledger)
    if ledger['stage'] == 'blocked':
        try:
            supervise_recovery_publication(ledger,plan,PRIVATE,cli,PROJECT)
            resumed = resume_verified_recovery(ledger, plan, PRIVATE)
            if not resumed:
                resumed = resume_verified_test_correction(ledger, plan, PRIVATE)
            if not resumed:
                resumed = resume_verified_review_context(ledger, plan, PRIVATE)
            if not resumed:
                from citation_supervision import resume as resume_citation_supervision
                resumed = resume_citation_supervision(ledger, plan, PRIVATE)
            if not resumed:
                from pre_red_supervision import resume as resume_pre_red_supervision
                resumed = resume_pre_red_supervision(ledger, plan, PRIVATE)
        except Exception as error:
            print(json.dumps({'stage': 'blocked', 'sequence': plan['name'],
                              'recovery_verification': (type(error).__name__ + ':' + str(error))[:160]}), flush=True)
            return 1
        if not resumed:
            print(json.dumps({'stage': 'blocked', 'sequence': plan['name'],
                              'active': ledger.get('active'), 'category': ledger.get('category')}), flush=True)
            return 1
        ledger = resumed
        save_receipt(ledger_path, ledger)
    active = None
    try:
        if ledger['stage'] == 'done':
            last = plan['stages'][-1]
            receipt = read_stage_delivery(PRIVATE, last)
            verify_predecessor(receipt, last, allow_advanced_main=True,
                               require_live_qa=False)
            reconciled=resolve_delivered_incident(ledger,last,receipt)
            if reconciled is not ledger:
                ledger=reconciled
                save_receipt(ledger_path,ledger)
            print(json.dumps({'stage': 'done', 'sequence': plan['name'],
                              'completed': ledger['completed']}), flush=True)
            return 0
        ensure_cards(plan, cli, issue, ledger, save_receipt, ledger_path, pinned_cards=pinned_cards)
        for index, stage in enumerate(plan['stages']):
            label = stage['spec']['label']
            if label in ledger['completed']:
                continue
            active = label
            existing_delivery = read_stage_delivery(PRIVATE, stage)
            if receipt_identity(existing_delivery, stage):
                verify_predecessor(existing_delivery, stage, allow_advanced_main=True)
                ledger['completed'].append(label)
                ledger.update(stage='stage_complete', active=None, updated_at=time.time())
                ledger=resolve_delivered_incident(ledger,stage,existing_delivery)
                save_receipt(ledger_path, ledger)
                continue
            env = stage_env(os.environ, plan, stage)
            if pinned_cards:
                env['DELIVERY_KIT_EXISTING_ISSUE_ID'] = ledger['issues'][label]
                env['DELIVERY_KIT_EXPECTED_PLAN_SHA'] = expected_plan_sha
            context = read_json(PRIVATE / ('portable-context-' + label + '.json'))
            if index == 0 and not context and not pinned_cards:
                release_first_card(cli, ledger['issues'][label])
            if index:
                prior = read_stage_delivery(PRIVATE, plan['stages'][index - 1])
                verify_predecessor(prior, plan['stages'][index - 1],
                                   allow_advanced_main=bool(context),
                                   require_live_qa=not bool(context))
                if plan['stages'][index - 1]['spec']['label'] not in ledger['completed']:
                    raise ValueError('predecessor not completed in sequence ledger')
                if not context:
                    dependent = cli('get', ledger['issues'][label])
                    if dependent.get('assignee_id') is not None or dependent.get('status') not in ('blocked', 'todo'):
                        raise ValueError('dependent card changed before release')
                    if dependent['status'] == 'blocked' and not pinned_cards:
                        cli('status', dependent['id'], 'todo', '--no-start')
            if context:
                issue = cli('get', context['issue_id'])
                registry = read_json(PRIVATE / stage['spec']['implementer_registry'])
                if not registry or issue.get('assignee_id') not in (None, registry['agent_id']):
                    raise ValueError('existing stage context has unexpected assignee')
                if issue.get('assignee_id') is None and run_command('start_portable.py', env):
                    raise RuntimeError('stage assignment recovery failed: ' + label)
            else:
                ledger.update(stage='dispatching', active=label, updated_at=time.time())
                save_receipt(ledger_path, ledger)
                if run_command('start_portable.py', env):
                    raise RuntimeError('stage dispatch failed: ' + label)
            ledger.update(stage='working', active=label, updated_at=time.time())
            save_receipt(ledger_path, ledger)
            result = run_command('portable_delivery.py', env)
            receipt = read_stage_delivery(PRIVATE, stage)
            if result or not receipt_identity(receipt, stage):
                status = read_json(PRIVATE / 'autonomy-status' / (label + '.json')) or {}
                raise RuntimeError(status.get('category', 'delivery_incomplete'))
            verify_predecessor(receipt, stage)
            ledger['completed'].append(label)
            ledger.update(stage='stage_complete', active=None, updated_at=time.time())
            ledger=resolve_delivered_incident(ledger,stage,receipt)
            save_receipt(ledger_path, ledger)
            if index == 0 and os.environ.get('DELIVERY_KIT_SEQUENCE_CRASH_AFTER_FIRST') == plan['name']:
                os._exit(86)
        ledger.update(stage='done', active=None, updated_at=time.time())
        save_receipt(ledger_path, ledger)
        print(json.dumps({'stage': 'done', 'sequence': plan['name'],
                          'completed': ledger['completed']}), flush=True)
        return 0
    except Exception as error:
        if ledger['stage'] == 'done':
            print(json.dumps({'stage': 'verification_unavailable',
                              'sequence': plan['name'],
                              'category': (type(error).__name__ + ':' + str(error))[:160]}),
                  flush=True)
            return 2
        ledger.update(stage='blocked', active=active,
                      owner='techlead',
                      next_action='Diagnose recorded failure and resume with a new authorized attempt',
                      category=(type(error).__name__ + ':' + str(error))[:160],
                      updated_at=time.time())
        save_receipt(ledger_path, ledger)
        if active and active in ledger.get('issues', {}):
            card_id = ledger['issues'][active]
            try:
                for key, value in (('sequence_status', 'blocked'),
                                   ('incident_owner', 'techlead'),
                                   ('incident_category', ledger['category'])):
                    cli('metadata', 'set', card_id, '--key', key,
                        '--value', value, '--type', 'string')
            except Exception as board_error:
                ledger['board_notification_error'] = type(board_error).__name__
                save_receipt(ledger_path, ledger)
        print(json.dumps({'stage': 'blocked', 'active': active,
                          'category': ledger['category']}), flush=True)
        return 1


def main():
    selected = os.environ.get('DELIVERY_KIT_SEQUENCE_PLAN')
    if not selected:
        raise ValueError('DELIVERY_KIT_SEQUENCE_PLAN required')
    plan = load_plan(selected)
    from evalctl import PRIVATE
    lock_path = PRIVATE / 'controller-locks' / (plan['name'] + '.lock')
    lock_path.parent.mkdir(mode=0o700, exist_ok=True)
    with lock_path.open('a+') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        return run_sequence()


if __name__ == '__main__':
    raise SystemExit(main())
