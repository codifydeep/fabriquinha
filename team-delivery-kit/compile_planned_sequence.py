"""Compile agent-owned scopes into immutable, controller-bounded delivery specs."""
import hashlib
import json
from pathlib import Path

from bootstrap_multica import PRIVATE
from materialize_plan import plan_from_ledger, card_description
from planning_intake import intake_configuration, tracked_base, validate_execution_plan
from planning_contract_review import digest
from portable_contract import is_test_path, validate as validate_contract
from portable_run_spec import validate as validate_spec
from prepare_issue_base import verified_main
from qa_postmerge_trial import write_once
from release_eval import save_receipt
from start_eval import cli

ROOT = Path(__file__).resolve().parent


def derive(plan, tracked, template, brief, resolution, browser_image):
    validate_execution_plan(plan, tracked)
    if resolution != {'parameter': 'status', 'absent': 'all', 'empty': '400',
                      'explicit_all': '400', 'unknown': '400'}:
        raise ValueError('resolved contract requires another independently qualified QA scenario')
    files = set(tracked)
    tests = {p for p in files if is_test_path(p, '.', 'python3')}
    outputs = {}
    stages = []
    command = 'cd /workspace && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1'
    for index, card in enumerate(plan['cards']):
        editable = set(card['files'])
        new_tests = {p for p in editable - files if is_test_path(p, '.', 'python3')}
        if any(p not in new_tests and not p.startswith('app/') for p in editable):
            raise ValueError('code scope outside qualified application root')
        files |= editable
        tests |= new_tests
        contract = {**template, 'files': sorted(files), 'required_files': sorted(files),
                    'protected_files': sorted(files - editable), 'editable_files': sorted(editable),
                    'test_files': sorted(tests)}
        validate_contract(contract)
        label = ('FILTERAPI-1', 'FILTERUI-1')[index]
        description = ('Agent-authored ' + card['id'] + ': ' + card['title'] + '. '
            'Acceptance: ' + json.dumps(card['acceptance']) + '\n'
            'Binding CTO contract: ' + json.dumps(resolution) + '. All in the UI omits status. '
            'Full approved product input: ' + brief + '\n'
            'Scope is limited to the contract-declared files in /workspace. '
            'PHASE 1 write only NEW tests: ' + json.dumps(sorted(new_tests)) + '. '
            'Use Python unittest with actual HTTP/JS behavior and bounded subprocesses. '
            'No sleeps, skipped tests, replacement app logic or swallowed exceptions. '
            'Reuse baseline harnesses faithfully if needed; every test file max32768 bytes. '
            'Controller captures Red and independent test review BEFORE implementation. '
            'PHASE 2 may edit only the declared product files; frozen tests never change. '
            'Keep all prior tests byte-identical and run exactly: ' + command + '. '
            'No GitHub, Docker, network credentials or administrative tools. '
            'Controller owns publication, deployment and independent browser QA.')
        review = ('Review immutable /delivery only. Inspect real code, controller Red/Green, '
            'independent test approval, prior test bytes, full suite and assigned acceptance. '
            'No edits, generic terminal/Python, Red reproduction or tool bypass. '
            'Invoke ONLY cd /delivery && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1; '
            'that operation must return the controller offline RPC receipt for this exact manifest. '
            'CTO contract: ' + json.dumps(resolution) + '. Acceptance: ' + json.dumps(card['acceptance']) +
            '. Finish with Decision: APPROVE or Decision: REQUEST_CHANGES;Reason: <specific finding>. '
            'Independent browser QA remains a separate mandatory gate.')
        spec = {'label': label, 'title': 'FILTER-1 — ' + card['id'] + ' — ' + card['title'],
                'description': description, 'review_instruction': review,
                'qa_host_port': 19444 + index, 'container_port': 8080,
                'dockerfile': 'Dockerfile.feedback-bootstrap',
                'implementer_registry': ('pilot-backend-data.json', 'pilot-frontend.json')[index],
                'reviewer_registry': 'pilot-techlead-reviewer.json',
                'runtime_env': {'FEEDBACK_DB_PATH': '/tmp/feedback.db'},
                'browser_qa': {'browser_image': browser_image, 'scenario':
                    ('feedback-board-status-filter-api-v1', 'feedback-board-filter-v1')[index]}}
        if len(description) > 4000 or len(review) > 2500:
            raise ValueError('generated execution context exceeds native bounds')
        validate_spec(spec, contract)
        prefix = 'descartavel2-filter-1-' + ('api', 'ui')[index]
        outputs[prefix + '.contract.json'] = contract
        outputs[prefix + '.run.json'] = spec
        stages.append({'contract': prefix + '.contract.json', 'run_spec': prefix + '.run.json',
                       'depends_on': None if index == 0 else 'FILTERAPI-1'})
    outputs['descartavel2-filter-1.sequence.json'] = {
        'sequence': 'FILTER-1-DELIVERY', 'project_config': 'descartavel2.json', 'stages': stages}
    return outputs


def main():
    selection = intake_configuration()
    if selection['name'] != 'FILTER-1' or verified_main() != selection['base_sha']:
        raise ValueError('compiler requires current FILTER-1 baseline')
    ledger = json.loads((PRIVATE / 'planning-intake' / 'FILTER-1.json').read_text())
    review = json.loads((PRIVATE / 'planning-contract-reviews' / 'FILTER-1.json').read_text())
    plan = plan_from_ledger(ledger)
    brief = selection['brief'].read_text()
    if (review['stage'] != 'decision_validated' or review['plan_sha256'] != digest(plan)
            or review['base_sha'] != selection['base_sha']
            or ledger['brief_sha256'] != hashlib.sha256(brief.encode()).hexdigest()
            or ledger['configuration_sha256'] != selection['configuration_sha256']):
        raise ValueError('review/brief/config identity drift')
    baseline = json.loads((ROOT / 'projects/descartavel2-keyboard-1.contract.json').read_text())
    browser = json.loads((ROOT / 'projects/descartavel2-keyboard-1.run.json').read_text())['browser_qa']['browser_image']
    outputs = derive(plan, tracked_base(selection), baseline, brief, review['resolution'], browser)
    mapped = json.loads((PRIVATE / 'planned-cards' / 'FILTER-1.json').read_text())
    if mapped['plan_sha256'] != digest(plan):
        raise ValueError('native card plan identity drift')
    # Preflight BOTH cards before any board change. No workers are dispatched.
    for card in plan['cards']:
        item = cli('get', mapped['cards'][card['id']])
        old = card_description(card, mapped['plan_sha256'])
        spec = outputs['descartavel2-filter-1-' + ('api' if card['id'] == 'C1' else 'ui') + '.run.json']
        if item['status'] != 'blocked' or item.get('assignee_id') is not None or item['title'] != spec['title'] or item['description'] not in (old, spec['description']):
            raise ValueError('native card drift or premature dispatch')
    path = PRIVATE / 'generated-contracts' / 'FILTER-1.json'
    receipt = {'stage': 'generated_not_dispatched', 'base_sha': selection['base_sha'],
               'plan_sha256': digest(plan), 'cto_task': review['task_id'],
               'artifacts': {name: digest(value) for name, value in outputs.items()}}
    if path.exists() and json.loads(path.read_text()) != receipt:
        raise ValueError('compiled artifact receipt drift')
    save_receipt(path, receipt)
    for name, value in outputs.items():
        write_once(ROOT / 'projects' / name, value)
    for index, card in enumerate(plan['cards']):
        issue = mapped['cards'][card['id']]
        spec = outputs['descartavel2-filter-1-' + ('api', 'ui')[index] + '.run.json']
        cli('update', issue, '--description', spec['description'], '--no-start')
        if cli('get', issue)['description'] != spec['description']:
            raise ValueError('native scope update unconfirmed')
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
