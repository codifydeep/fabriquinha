"""Compile agent-authored dependent scopes against operator-pinned QA templates.

No agent controls ports, registries, Docker, QA scenarios or publication policy.
This bridge is deliberately restricted to the qualified two-card Python/web
pilot. Supporting another stack or QA scenario requires separate qualification.
"""
import hashlib
import json
import os
from pathlib import Path
import re

from dependent_sequence import project_file
from materialize_plan import card_description, plan_from_ledger
from planning_intake import (brief_body, intake_configuration, parse_proposal,
                             tracked_base, validate_execution_plan)
from portable_contract import is_test_path, validate as validate_contract
from portable_run_spec import validate as validate_spec
from review_instruction import bounded as bounded_review_instruction
from generated_context import compact as compact_generated_context
from qa_postmerge_trial import digest, write_once
from release_eval import save_receipt
from planning_ceo_answer import context as answered_context

ROOT = Path(__file__).resolve().parent


def derive(plan, tracked, stages, brief, cto, *, name, prefix, project_config, context_capsules=False):
    if (not isinstance(name, str) or not re.fullmatch(r'[A-Z][A-Z0-9-]{2,31}', name)
            or not isinstance(prefix, str) or not re.fullmatch(r'[a-z][a-z0-9-]{2,63}', prefix)
            or not isinstance(project_config, str)
            or not re.fullmatch(r'[a-z0-9][a-z0-9.-]*\.json', project_config)):
        raise ValueError('invalid compiled delivery identity')
    parse_proposal(json.dumps(plan), 'techlead')
    parse_proposal(json.dumps(cto), 'cto')
    validate_execution_plan(plan, tracked)
    if not isinstance(stages, list) or len(stages) != 2:
        raise ValueError('exactly two preapproved QA stages required')
    labels = [stage['spec']['label'] for stage in stages]
    ports = [stage['spec']['qa_host_port'] for stage in stages]
    if len(set(labels)) != 2 or len(set(ports)) != 2:
        raise ValueError('stage identities and QA ports must differ')
    files = set(tracked)
    tests = {p for p in files if is_test_path(p, '.', 'python3')}
    if not tests:
        raise ValueError('protected baseline test suite required')
    outputs, sequence = {}, []
    repository = stages[0]['contract']['repository']
    command = 'cd /workspace && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1'
    for index, (card, stage) in enumerate(zip(plan['cards'], stages)):
        template, run = stage['contract'], stage['spec']
        if template['repository'] != repository or template['base_branch'] != 'main':
            raise ValueError('preapproved stage repository mismatch')
        registry = ('pilot-backend-data.json', 'pilot-frontend.json')[index]
        if run['implementer_registry'] != registry:
            raise ValueError('template implementer does not match card owner')
        if template['test_command'] != card['test_command'] or template['test_roots'] != ['.']:
            raise ValueError('preapproved full-suite runner required')
        editable = set(card['files'])
        new_tests = {p for p in editable - files if is_test_path(p, '.', 'python3')}
        allowed_code = {p for p in template['editable_files']
                        if p.startswith('app/') and not is_test_path(p, '.', 'python3')}
        if not editable <= allowed_code | new_tests:
            raise ValueError('agent scope exceeds preapproved template code paths')
        files |= editable
        tests |= new_tests
        contract = {**template, 'files': sorted(files), 'required_files': sorted(files),
                    'protected_files': sorted(files - editable), 'editable_files': sorted(editable),
                    'test_files': sorted(tests)}
        validate_contract(contract)
        acceptance = json.dumps(card['acceptance'], ensure_ascii=False)
        architecture = json.dumps(cto, ensure_ascii=False, separators=(',', ':'))
        description = ('Agent-authored ' + card['id'] + ': ' + card['title'] + '. '
            'Acceptance: ' + acceptance + '\nApproved CEO request: ' + brief +
            '\nBinding CTO proposal: ' + architecture + '\n'
            'Scope is ONLY the contract-declared files in /workspace. '
            'PHASE 1: write only NEW discoverable tests ' + json.dumps(sorted(new_tests)) + '. '
            'Use actual HTTP/JS behavior, bounded subprocesses and the baseline harnesses. '
            'No sleeps, skipped tests, invented app logic or swallowed exceptions. '
            'Controller captures Red and independent immutable test review BEFORE implementation. '
            'PHASE 2: edit only the declared product paths; frozen tests NEVER change. '
            'Keep every preexisting test byte-identical. Run exactly: ' + command + '. '
            'Do not use GitHub, Docker, credentials or administrative operations. '
            'Controller owns publication, required CI and independent deployed/browser QA.')
        if 'DELIVERY_TYPED_TEST_SOURCE_V1' in run['description']:
            description += '\nDELIVERY_TYPED_TEST_SOURCE_V1\n'
        review = ('Review immutable /delivery only: acceptance ' + acceptance +
            '; binding CTO proposal ' + architecture + '. '
            'Inspect existing controller Red/Green and independent initial test approval. '
            'Do not edit files, reproduce Red, run generic terminal/Python or bypass tools. '
            'Run ONLY cd /delivery && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1 '
            'and require the exact-manifest offline RPC receipt. '
            'Finish with Decision: APPROVE or Decision: REQUEST_CHANGES;Reason: <specific finding>. '
            'Deployment/browser QA is a separate mandatory gate.')
        description, _ = compact_generated_context(description)
        capsule = None
        if context_capsules:
            from execution_context import freeze, reference
            capsule = freeze(description, review)
            description = reference(capsule, 'implementation')
            review = reference(capsule, 'review')
        if len(description) > 4000:
            raise ValueError('generated execution context exceeds native bounds')
        spec = {**run, 'title': name + ' — ' + card['id'] + ' — ' + card['title'],
                'description': description, 'review_instruction': bounded_review_instruction(review)}
        if capsule is not None:
            spec['execution_context'] = capsule
        validate_spec(spec, contract)
        stem = prefix + '-c' + str(index + 1)
        outputs[stem + '.contract.json'] = contract
        outputs[stem + '.run.json'] = spec
        sequence.append({'contract': stem + '.contract.json', 'run_spec': stem + '.run.json',
                         'depends_on': None if index == 0 else labels[0]})
    outputs[prefix + '.sequence.json'] = {
        'sequence': name + '-DELIVERY', 'project_config': project_config, 'stages': sequence}
    return outputs


def load_configuration(path):
    """Hash every operator input, not just filenames, before any model dispatch."""
    path = Path(path)
    checked = project_file(path.name)
    if path.resolve() != checked.resolve() or path.is_symlink() or checked.stat().st_size > 16384:
        raise ValueError('brief delivery configuration must be a bounded project file')
    raw = json.loads(checked.read_text())
    if (not isinstance(raw, dict) or set(raw) != {
            'name', 'prefix', 'project_config', 'planning_config', 'minimum_calls', 'stages'}
            or type(raw['minimum_calls']) is not int or not 256 <= raw['minimum_calls'] <= 512
            or not isinstance(raw['stages'], list) or len(raw['stages']) != 2):
        raise ValueError('invalid brief delivery configuration')
    if (not isinstance(raw['name'], str) or not re.fullmatch(r'[A-Z][A-Z0-9-]{2,31}', raw['name'])
            or not isinstance(raw['prefix'], str) or not re.fullmatch(r'[a-z][a-z0-9-]{2,63}', raw['prefix'])):
        raise ValueError('invalid brief delivery identity')
    planning_path = project_file(raw['planning_config'])
    selection = intake_configuration(planning_path)
    if selection['name'] != raw['name'] or raw['minimum_calls'] < selection['minimum_calls']:
        raise ValueError('planning identity or reserve mismatch')
    project_path = project_file(raw['project_config'])
    project = json.loads(project_path.read_text())
    if set(project) != {'repository', 'checkout'}:
        raise ValueError('invalid project selection')
    input_paths = [checked, planning_path, selection['brief'], project_path]
    stages = []
    for stage in raw['stages']:
        if not isinstance(stage, dict) or set(stage) != {'contract', 'run_spec'}:
            raise ValueError('invalid preapproved stage')
        contract_path, spec_path = project_file(stage['contract']), project_file(stage['run_spec'])
        if any(p.stat().st_size > 131072 for p in (contract_path, spec_path)):
            raise ValueError('preapproved stage files exceed bound')
        from portable_contract import load
        contract = load(contract_path)
        spec = validate_spec(json.loads(spec_path.read_text()), contract)
        if contract['repository'] != project['repository']:
            raise ValueError('configuration repository mismatch')
        if 'browser_qa' not in spec:
            raise ValueError('independent deployed browser QA required')
        stages.append({'contract': contract, 'spec': spec})
        input_paths.extend((contract_path, spec_path))
    if any(p.stat().st_size > 131072 for p in input_paths):
        raise ValueError('brief delivery input exceeds bound')
    return {**raw, 'selection': selection, 'planning_path': planning_path,
            'stages': stages, 'path': checked,
            'sha256': digest({str(p.name): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in input_paths})}


def main():
    from bootstrap_multica import BACKEND_PORT, PRIVATE
    from evalctl import PROJECT
    from prepare_issue_base import verified_main
    from project_selection import current
    from start_eval import cli
    if PROJECT != 'delivery-kit-port2' or BACKEND_PORT != '19081':
        raise ValueError('brief compiler restricted to isolated port2 installation')
    config = load_configuration(os.environ['DELIVERY_KIT_BRIEF_DELIVERY_CONFIG'])
    selection, name = config['selection'], config['name']
    if intake_configuration()['configuration_sha256'] != selection['configuration_sha256']:
        raise ValueError('active planning selection drift')
    project = json.loads(project_file(config['project_config']).read_text())
    selected = current()
    if (selected['repository'] != project['repository']
            or selected['checkout'] != ROOT / project['checkout']
            or verified_main() != selection['base_sha']):
        raise ValueError('planning baseline or selected repository drift')
    ledger = json.loads((PRIVATE / 'planning-intake' / (name + '.json')).read_text())
    plan = plan_from_ledger(ledger)
    if (ledger.get('configuration_sha256') != selection['configuration_sha256']
            or ledger.get('base_sha') != selection['base_sha']
            or ledger.get('brief_sha256') != hashlib.sha256(selection['brief'].read_bytes()).hexdigest()):
        raise ValueError('planning ledger identity drift')
    outputs = derive(plan, tracked_base(selection), config['stages'],
                     answered_context(brief_body(selection['brief'].read_text()), ledger), ledger['outputs']['cto']['proposal'],
                     name=name, prefix=config['prefix'], project_config=config['project_config'],
                     context_capsules=True)
    mapped = json.loads((PRIVATE / 'planned-cards' / (name + '.json')).read_text())
    if mapped['plan_sha256'] != digest(plan) or set(mapped['cards']) != {'C1', 'C2'}:
        raise ValueError('materialized plan identity drift')
    # Preflight both board cards BEFORE changing either. Retries may observe an
    # already updated description after an interrupted acknowledgement.
    for index, card in enumerate(plan['cards']):
        item = cli('get', mapped['cards'][card['id']])
        spec = outputs[config['prefix'] + '-c' + str(index + 1) + '.run.json']
        if (item['status'] != 'blocked' or item.get('assignee_id') is not None
                or item['title'] != spec['title']
                or item['description'] not in (card_description(card, mapped['plan_sha256']),
                                               spec['description'])):
            raise ValueError('native planned card drift or premature dispatch')
    receipt_path = PRIVATE / 'generated-contracts' / (name + '.json')
    receipt = {'stage': 'generated_not_dispatched', 'input_sha256': config['sha256'],
               'base_sha': selection['base_sha'], 'plan_sha256': digest(plan),
               'planning_outputs_sha256': digest(ledger['outputs']), 'cards': mapped['cards'],
               'artifacts': {key: digest(value) for key, value in outputs.items()}}
    write_once(receipt_path, receipt)
    for filename, value in outputs.items():
        write_once(ROOT / 'projects' / filename, value)
    # Also exercise the same graph/scope transition validator used at dispatch.
    from dependent_sequence import load_plan
    load_plan(ROOT / 'projects' / (config['prefix'] + '.sequence.json'))
    for index, card in enumerate(plan['cards']):
        spec = outputs[config['prefix'] + '-c' + str(index + 1) + '.run.json']
        issue_id = mapped['cards'][card['id']]
        cli('update', issue_id, '--description', spec['description'], '--no-start')
        if cli('get', issue_id)['description'] != spec['description']:
            raise ValueError('native scope update unconfirmed')
    save_receipt(PRIVATE / 'compiled-plans' / (name + '.json'), receipt)
    print(json.dumps({'stage': receipt['stage'], 'name': name, 'cards': mapped['cards']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
