"""Operator-only dispatch of the pinned non-calculator portability issue."""
import hashlib
import json
import os
import uuid

from bootstrap_multica import PRIVATE
from portable_contract import from_environment
from portable_run_spec import load as load_run_spec
from prepare_issue_base import broker_post, prepare, verified_main
from project_selection import current as selected_project
from release_eval import save_receipt
from review_wakeup import ensure_review_wakeup
from start_eval import cli, issue
from review_instruction import bounded as bounded_review_instruction


LABEL = os.environ.get('DELIVERY_KIT_PORTABLE_LABEL', 'PORT-4')
TITLE = LABEL + ' — text-slug delivery, independent review and local QA'
DESCRIPTION_PORT4 = (
    'Disposable text-slug fixture only. Implement truncate_slug(text, max_length) '
    'in slugapp.py. It first calls slugify(text), takes at most max_length characters, '
    'then removes a trailing hyphen. max_length must be a positive integer; '
    'otherwise raise ValueError. Add slug_tests/test_truncate.py with a failing '
    'basic test first, observe Red, implement, observe Green, and run the complete '
    'suite. Preserve all existing tests and protected files byte-for-byte. '
    'An independent reviewer must require boundary and invalid-limit tests before '
    'approval. Do not use GitHub, Docker, credentials, network or any other project.'
)
REVIEW_INSTRUCTION_PORT4 = (
    'Review only frozen /delivery; do not edit. Verify truncate_slug at a '
    'hyphen boundary (Hello World, limit 6 -> hello) and invalid limits, in '
    'addition to the basic case. If either test is absent, REQUEST_CHANGES with '
    'a concrete finding. Run cd /delivery && PYTHONDONTWRITEBYTECODE=1 '
    'python3 -m unittest discover -s slug_tests -q 2>&1, without piping. '
    'Finish with exactly one standalone line Decision: APPROVE or '
    'Decision: REQUEST_CHANGES;Reason: <specific finding>, followed by evidence.'
)
DESCRIPTION_PORT5 = (
    'Disposable text-slug fixture only. Change slugify in slugapp.py so accented '
    'Latin letters are transliterated to ASCII before the existing lowercase and '
    'hyphen normalization; Olá Mundo must become ola-mundo and Ação must become '
    'acao. Preserve current behavior for ASCII and all existing tests. Add '
    'slug_tests/test_unicode.py with a failing accented-word test first, observe '
    'Red, implement, observe Green, and run the complete suite. Do not edit '
    'pre-existing test files. Do not access GitHub, Docker, credentials, network '
    'or any other project.'
)
REVIEW_INSTRUCTION_PORT5 = (
    'Review only frozen /delivery; do not edit. Verify new tests cover Olá Mundo '
    'and Ação, existing tests remain unchanged, and the complete suite passes. '
    'If coverage is absent, REQUEST_CHANGES with a concrete finding. Run '
    'cd /delivery && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover '
    '-s slug_tests -q 2>&1, without piping. Finish with exactly one standalone '
    'line Decision: APPROVE or Decision: REQUEST_CHANGES;Reason: <specific finding>, '
    'followed by evidence.'
)
DESCRIPTION_PORT7 = DESCRIPTION_PORT5 + (
    ' For Red, Green and full-suite evidence, use exactly one terminal command: '
    'cd /workspace && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover '
    '-s slug_tests -q 2>&1. Do not append probes or other commands.'
)
DESCRIPTION_PORT8 = (
    'Disposable text-slug fixture only. Extend slugify in slugapp.py so the '
    'German sharp s transliterates to ss: Straße must become strasse. Preserve '
    'all existing behavior and every pre-existing test unchanged. Add only '
    'slug_tests/test_german.py with a failing test first, observe Red, implement, '
    'observe Green, and run the complete suite. Use exactly: cd /workspace && '
    'PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s slug_tests -q 2>&1. '
    'Do not append commands. No GitHub, Docker, credentials, network or other projects.'
)
REVIEW_INSTRUCTION_PORT8 = (
    'Review only frozen /delivery; do not edit. Require a separate '
    'slug_tests/test_german.py asserting slugify("Straße") == "strasse"; '
    'preserve every pre-existing test and assertion. Run exactly: cd /delivery && '
    'PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s slug_tests -q 2>&1. '
    'No piping or appended commands. Request changes if evidence is absent. '
    'Finish with Decision: APPROVE or Decision: REQUEST_CHANGES;Reason: '
    '<specific finding>, followed by test evidence.'
)
DESCRIPTION_PORT9 = (
    'Disposable text-slug fixture only. Extend slugify in slugapp.py so the '
    'Latin AE ligature transliterates to ae: Æther must become aether. Preserve '
    'all existing behavior and every pre-existing test unchanged. Add only '
    'slug_tests/test_ligature.py with a failing test first, observe Red, implement, '
    'observe Green, and run the complete suite. Use exactly: cd /workspace && '
    'PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s slug_tests -q 2>&1. '
    'Do not append commands. No GitHub, Docker, credentials, network or other projects.'
)
REVIEW_INSTRUCTION_PORT9 = (
    'Review only frozen /delivery; do not edit. Require a separate '
    'slug_tests/test_ligature.py asserting slugify("Æther") == "aether"; '
    'preserve every pre-existing test and assertion. Run exactly: cd /delivery && '
    'PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s slug_tests -q 2>&1. '
    'No piping or appended commands. Request changes if evidence is absent. '
    'Finish with Decision: APPROVE or Decision: REQUEST_CHANGES;Reason: '
    '<specific finding>, followed by test evidence.'
)
if LABEL not in ('PORT-4', 'PORT-5', 'PORT-6', 'PORT-7', 'PORT-8', 'PORT-9') and not os.environ.get('DELIVERY_KIT_RUN_SPEC'):
    raise ValueError('unsupported portable qualification label')
DESCRIPTION = (DESCRIPTION_PORT4 if LABEL == 'PORT-4' else
               DESCRIPTION_PORT7 if LABEL == 'PORT-7' else
               DESCRIPTION_PORT8 if LABEL == 'PORT-8' else DESCRIPTION_PORT5)
if LABEL == 'PORT-9':
    DESCRIPTION = DESCRIPTION_PORT9
REVIEW_INSTRUCTION = (REVIEW_INSTRUCTION_PORT4 if LABEL == 'PORT-4' else
                      REVIEW_INSTRUCTION_PORT8 if LABEL == 'PORT-8' else
                      REVIEW_INSTRUCTION_PORT5)
if LABEL == 'PORT-9':
    REVIEW_INSTRUCTION = REVIEW_INSTRUCTION_PORT9


def main():
    contract = from_environment()
    controlled_fault=os.environ.get('DELIVERY_KIT_CONTROLLED_WORKER_LOSS')=='1'
    if controlled_fault and (contract['schema_version']!=2 or os.environ.get('DELIVERY_KIT_TEST_FIRST')!='1'):
        raise ValueError('controlled fault requires durable test-first delivery')
    project = selected_project()
    if contract['repository'] != project['repository']:
        raise ValueError('contract repository differs from selected project')
    spec = load_run_spec(contract)
    if spec:
        label, title = spec['label'], spec['title']
        description, review_instruction = spec['description'], spec['review_instruction']
        author_file, reviewer_file = spec['implementer_registry'], spec['reviewer_registry']
    else:
        if contract['repository'] != 'codifydeep/descartavel2':
            raise ValueError('legacy portable pilot is restricted to descartavel2')
        label, title = LABEL, TITLE
        description, review_instruction = DESCRIPTION, REVIEW_INSTRUCTION
        suffix = '-v2' if LABEL in ('PORT-7', 'PORT-8', 'PORT-9') else ''
        author_file, reviewer_file = ('portable-implementer' + suffix + '.json',
                                      'portable-reviewer' + suffix + '.json')
    implementer = json.loads((PRIVATE / author_file).read_text())
    reviewer = json.loads((PRIVATE / reviewer_file).read_text())
    if implementer['workspace_id'] != reviewer['workspace_id']:
        raise ValueError('portable agent workspace mismatch')
    if implementer['agent_id'] == reviewer['agent_id']:
        raise ValueError('reviewer must differ from implementer')
    review_instruction = bounded_review_instruction(review_instruction)
    existing_issue_id = os.environ.get('DELIVERY_KIT_EXISTING_ISSUE_ID')
    if existing_issue_id:
        if str(uuid.UUID(existing_issue_id)) != existing_issue_id or not spec:
            raise ValueError('existing issue requires canonical identity and run spec')
        current = cli('get', existing_issue_id)
        metadata = cli('metadata', 'list', existing_issue_id)
        expected_plan_sha = os.environ.get('DELIVERY_KIT_EXPECTED_PLAN_SHA')
        if (current.get('title') != title or current.get('status') != 'blocked'
                or current.get('assignee_id') is not None
                or not expected_plan_sha
                or metadata.get('planning_sha256') != expected_plan_sha
                or metadata.get('execution_gate') != 'awaiting_generated_contract'):
            raise ValueError('planned issue is not safely releasable')
    else:
        current = issue(title, description)
    if current.get('assignee_id') not in (None, implementer['agent_id']):
        raise ValueError('unexpected issue assignee')
    if current.get('assignee_id') is not None:
        raise ValueError('portable pilot is dispatched already; reconcile its receipt')
    pinned = prepare(current['id'])
    if verified_main() != pinned['base_sha']:
        raise ValueError('main moved before portable assignment')
    durable = contract['schema_version'] == 2
    if durable:
        planning = json.loads((PRIVATE / 'planning-agents.json').read_text())['agents']
        route = {
            'issue_id': current['id'], 'author': implementer['agent_id'], 'reviewer': reviewer['agent_id'],
            'techlead': planning['techlead'], 'cto': planning['cto'],
            'contract_sha256': hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'review_instruction': review_instruction, 'minimum_calls': 8, 'enabled': True}
        if os.environ.get('DELIVERY_KIT_TEST_FIRST') == '1':
            route.update(test_first=True,
                         test_first_files=sorted(set(contract['test_files']) &
                                                 set(contract['editable_files'])))
        broker_post('/v1/delivery-routes', route)
        revision_parent = os.environ.get('DELIVERY_KIT_TEST_REVISION_PARENT')
        if revision_parent:
            broker_post('/v1/test-revision-trials', {'issue_id': current['id'], 'parent_issue': revision_parent})
    else:
        ensure_review_wakeup(cli, current['id'], implementer['agent_id'],
                             reviewer['agent_id'], review_instruction)
    context = {'label': label, 'issue_id': current['id'], 'base_sha': pinned['base_sha'],
               'contract_sha256': hashlib.sha256(json.dumps(contract, sort_keys=True,
                     separators=(',', ':')).encode()).hexdigest()}
    if spec:
        context['run_spec_sha256'] = spec['sha256']
    if durable:
        context['durable_handoffs'] = True
    path = PRIVATE / ('portable-context.json' if not spec and label == 'PORT-4'
                      else 'portable-context-' + label + '.json')
    if path.exists() and json.loads(path.read_text()) != context:
        raise ValueError('portable context drift')
    if not path.exists():
        save_receipt(path, context)
    if existing_issue_id:
        updated = cli('update', existing_issue_id, '--description', description,
                      '--status', 'todo', '--no-start')
        if updated.get('description') != description or updated.get('status') != 'todo':
            raise ValueError('planned issue release not confirmed')
    if (os.environ.get('DELIVERY_KIT_REQUIRE_BROWSER_ACCEPTANCE') == '1'
            or (spec and spec.get('browser_qa'))):
        cli('metadata', 'set', current['id'], '--key', 'browser_acceptance',
            '--value', 'pending_real_browser', '--type', 'string')
        if cli('metadata', 'list', current['id']).get('browser_acceptance') != 'pending_real_browser':
            raise ValueError('mandatory browser acceptance gate was not persisted')
    if controlled_fault:
        from arm_controlled_worker_loss import arm
        from evalctl import PROJECT
        arm(PRIVATE,PROJECT,current['id'])
    assigned = cli('assign', current['id'], '--to-id', implementer['agent_id'])
    if assigned.get('assignee_id') != implementer['agent_id']:
        raise ValueError('portable assignment failed')
    if existing_issue_id:
        cli('metadata', 'set', existing_issue_id, '--key', 'execution_gate',
            '--value', 'dispatched', '--type', 'string')
    print(json.dumps({**context, 'assigned': True}))


if __name__ == '__main__':
    main()
