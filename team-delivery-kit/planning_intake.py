"""Durable, bounded Product -> CTO -> Tech Lead planning from a CEO brief."""
import hashlib
import json
import os
from pathlib import Path
import re
import time

from bootstrap_multica import AUTH, BACKEND_PORT, PRIVATE, request
from release_eval import save_receipt
from start_eval import check_model_budget, cli


ROOT = Path(__file__).resolve().parent
BRIEF = ROOT / 'projects' / 'pilot-feedback-board.brief.md'
NAME = 'PILOT-FEEDBACK-BOARD'
ROLES = ('product', 'cto', 'techlead')


def intake_configuration(path=None):
    """Select a versioned brief without reusing another planning ledger."""
    if path is None:
        path = os.environ.get('DELIVERY_KIT_PLANNING_CONFIG')
    if not path:
        return {'name': NAME, 'brief': BRIEF, 'minimum_calls': 64,
                'base_sha': None, 'configuration_sha256': None}
    target = Path(path)
    projects = ROOT / 'projects'
    if (target.is_symlink() or not target.is_file()
            or target.resolve().parent != projects.resolve()
            or target.stat().st_size > 16384):
        raise ValueError('planning config must be a bounded project file')
    raw = target.read_bytes()
    config = json.loads(raw)
    if not isinstance(config, dict) or set(config) != {
            'name', 'brief', 'minimum_calls', 'base_sha'}:
        raise ValueError('invalid planning config fields')
    if not isinstance(config['name'], str) or not re.fullmatch(r'[A-Z][A-Z0-9-]{2,40}', config['name']):
        raise ValueError('invalid planning run identity')
    filename = config['brief']
    if not isinstance(filename, str) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]*\.brief\.md', filename):
        raise ValueError('invalid planning brief filename')
    brief = projects / filename
    if (brief.is_symlink() or not brief.is_file()
            or brief.resolve().parent != projects.resolve()
            or brief.stat().st_size > 16384):
        raise ValueError('planning brief must be a bounded project file')
    if type(config['minimum_calls']) is not int or not 64 <= config['minimum_calls'] <= 512:
        raise ValueError('invalid planning budget reserve')
    if not isinstance(config['base_sha'], str) or not re.fullmatch(r'[a-f0-9]{40}', config['base_sha']):
        raise ValueError('invalid planning base SHA')
    return {**config, 'brief': brief,
            'configuration_sha256': hashlib.sha256(raw).hexdigest()}


def brief_body(text):
    start = text.index('## CEO request')
    end = text.index('## Decisions delegated to the team')
    result = text[start:end].strip()
    if not 100 < len(result) <= 2200:
        raise ValueError('pilot brief size outside bounds')
    return result


def parse_proposal(content, role):
    if not isinstance(content, str) or len(content) > 7000:
        raise ValueError('invalid planning output')
    candidate = content.strip()
    if candidate.startswith('```'):
        candidate = re.sub(r'^```(?:json)?\s*|\s*```$', '', candidate).strip()
    proposal = json.loads(candidate)
    if not isinstance(proposal, dict) or proposal.get('role') != role:
        raise ValueError('planning role mismatch')
    if role == 'product' and 'user_stories' in proposal and 'stories' not in proposal:
        stories = proposal['user_stories']
        if not isinstance(stories, list):
            raise ValueError('invalid product story list')
        proposal = {'role': 'product', 'stories': [
            {'title': story.get('story'), 'acceptance': story.get('acceptance_criteria')}
            if isinstance(story, dict) else {} for story in stories],
            'business_questions': proposal.get('business_questions')}
    fields = {
        'product': {'role', 'stories', 'business_questions'},
        'cto': {'role', 'stack', 'components', 'security', 'technical_decisions', 'risks'},
        'techlead': {'role', 'cards', 'integration_order'},
    }[role]
    if set(proposal) != fields:
        raise ValueError('planning output schema mismatch')
    if role == 'product':
        stories = proposal['stories']
        if not isinstance(stories, list) or not 1 <= len(stories) <= 8:
            raise ValueError('invalid story count')
        for story in stories:
            if set(story) != {'title', 'acceptance'} or not short(story['title'], 400) or not strings(story['acceptance'], 1, 8):
                raise ValueError('invalid story')
            # A valid JSON envelope is not evidence of a user-facing requirement.
            # Reject proven protocol/reasoning leakage, not business decisions.
            text = '\n'.join([story['title'], *story['acceptance']]).lower()
            if any(marker in text for marker in (
                    'my response must have role=', 'product schema response',
                    'evidence_required_controller_side', 'let me re-read the task',
                    'here i have to produce a product proposal')):
                raise ValueError('planning output contains reasoning instead of product acceptance')
        if not strings(proposal['business_questions'], 0, 3):
            raise ValueError('invalid business questions')
    elif role == 'cto':
        if not short(proposal['stack'], 300):
            raise ValueError('invalid stack')
        for field in ('components', 'security', 'technical_decisions', 'risks'):
            if not strings(proposal[field], 0 if field == 'risks' else 1, 8):
                raise ValueError('invalid CTO proposal: ' + field)
    else:
        cards = proposal['cards']
        if not isinstance(cards, list) or not 1 <= len(cards) <= 5:
            raise ValueError('invalid card count')
        previous = set()
        for card in cards:
            fields = {'id', 'title', 'owner', 'depends_on', 'acceptance', 'files', 'test_command'}
            if set(card) not in (fields, fields | {'required_files'}):
                raise ValueError('invalid card fields')
            if not isinstance(card['id'], str) or not re.fullmatch(r'C[1-5]', card['id']) or card['id'] in previous:
                raise ValueError('invalid card identity')
            if card['owner'] not in ('backend_data', 'frontend', 'devops', 'quality_security'):
                raise ValueError('invalid card owner')
            if not short(card['title']) or not strings(card['acceptance'], 1, 8):
                raise ValueError('invalid card acceptance')
            if not isinstance(card['depends_on'], list) or any(item not in previous for item in card['depends_on']):
                raise ValueError('invalid card dependency')
            if not strings(card['files'], 1, 12) or any(not safe_path(item) for item in card['files']):
                raise ValueError('invalid proposed file')
            if 'required_files' in card and (not strings(card['required_files'], 1, 12)
                    or not set(card['required_files']) <= set(card['files'])):
                raise ValueError('required deliverables outside allowed files')
            if card['test_command'] not in (
                    ['node', '--test'],
                    ['python3', '-m', 'unittest', 'discover', '-s', '.', '-q']):
                raise ValueError('unqualified test runner')
            previous.add(card['id'])
        if proposal['integration_order'] != [card['id'] for card in cards]:
            raise ValueError('integration order disagrees with card graph')
    return proposal


def short(value, limit=180):
    return isinstance(value, str) and 0 < len(value.strip()) <= limit


def strings(value, minimum, maximum):
    return isinstance(value, list) and minimum <= len(value) <= maximum and all(short(item, 300) for item in value)


def safe_path(value):
    if value == '.dockerignore':
        return True
    if not isinstance(value, str) or not value or '\\' in value or len(value) > 240:
        return False
    path = Path(value)
    return (not path.is_absolute() and len(path.parts) >= 1
            and all(part not in ('', '.', '..') for part in value.split('/'))
            and not value.startswith('.'))


def tracked_base(selection):
    import subprocess
    from project_selection import current
    return subprocess.check_output(['git', '-C', str(current()['checkout']),
        'ls-tree', '-r', '--name-only', selection['base_sha']], text=True).splitlines()


def validate_execution_plan(proposal, tracked):
    """A syntactically valid proposal can still be impossible to dispatch."""
    from portable_contract import is_test_path
    cards = proposal['cards']
    if (len(cards) != 2 or [c['id'] for c in cards] != ['C1', 'C2']
            or [c['owner'] for c in cards] != ['backend_data', 'frontend']
            or [c['depends_on'] for c in cards] != [[], ['C1']]):
        raise ValueError('unsupported execution graph')
    existing = set(tracked)
    old_tests = {p for p in existing if is_test_path(p, '.', 'python3') or p.endswith(('.test.js', '.spec.js'))}
    for card in cards:
        if card['test_command'] != ['python3', '-m', 'unittest', 'discover', '-s', '.', '-q']:
            raise ValueError('unqualified test runner')
        files = set(card['files'])
        if files & old_tests:
            raise ValueError('planning edits frozen tests')
        new_tests = {p for p in files - existing if is_test_path(p, '.', 'python3')}
        if not new_tests:
            raise ValueError('each implementation card requires a new discoverable test file')
        for p in new_tests:
            if '/' in p and not p.startswith('tests/'):
                raise ValueError('new tests must be discoverable in qualified roots')
        existing |= new_tests
        old_tests |= new_tests
    return proposal


def capability_context(selection):
    if not selection['configuration_sha256']:
        return ''
    tracked = tracked_base(selection)
    code = [p for p in tracked if not p.startswith('tests/') and not p.startswith('test_')]
    scope = ''
    profile = os.environ.get('DELIVERY_KIT_BRIEF_DELIVERY_CONFIG')
    if profile:
        from planned_delivery import load_configuration
        qualified = load_configuration(profile)
        if qualified['selection']['configuration_sha256'] != selection['configuration_sha256']:
            raise ValueError('brief capability planning identity drift')
        scope = (' Preapproved product code scopes by card: ' + json.dumps({
            'C' + str(index + 1): [p for p in stage['contract']['editable_files']
                                  if p.startswith('app/')]
            for index, stage in enumerate(qualified['stages'])}) + '. '
            'Use exactly one NEW discoverable unittest file per card. '
            'Keep the current Python stdlib server and vanilla client; no new stack. ')
    return ('\n\nCONTROLLER-VERIFIED CAPABILITIES: This qualification supports exactly '
            'two implementation cards, C1 backend_data then C2 frontend depending on C1. '
            'CI/deployment/QA are controller gates, not extra implementation cards. '
            'Allowed test_command is exactly ["python3","-m","unittest","discover","-s",".","-q"]. '
            'Never select partial tests, pytest, shell strings or Docker commands. '
            'Existing code paths: ' + json.dumps(code, separators=(',', ':')) + '. ' + scope +
            'Use those actual paths. EVERY card must declare at least one NEW '
            'uniquely named test_<name>.py at repository root or tests/test_<name>.py. '
            'Never edit pre-existing tests. File scopes remain your proposal, not an executed change.')


def issue_for(role, description, agent_id, *, retry=False, recovery=False, schema=False, run_name=NAME, wire=False, capability=False, clarification=False, ceo_answer=False, source_review=False):
    suffix = ('-capability1' if capability else '-wire1' if wire else '-schema1' if schema else '-recovery1' if recovery else '-retry1' if retry else '')
    title = run_name + ' — ' + role + ('-source-reviewed1' + suffix if source_review else '-ceoanswer1' + suffix if ceo_answer else '-briefclarification1' if clarification else suffix)
    if len(description) > 8000:
        raise ValueError('planning context exceeds issue limit')
    matches = [card for card in cli('list')['issues'] if card['title'] == title]
    if len(matches) > 1:
        raise ValueError('duplicate planning card')
    if matches:
        card = matches[0]
        if card['description'] != description:
            raise ValueError('planning issue context drift')
    else:
        card = cli('create', '--title', title, '--description', description, '--status', 'todo')
    if card.get('assignee_id') not in (None, agent_id):
        raise ValueError('planning assignee mismatch')
    if card.get('assignee_id') is None:
        assigned = cli('assign', card['id'], '--to-id', agent_id)
        if assigned.get('assignee_id') != agent_id:
            raise ValueError('planning assignment unconfirmed')
    return card['id']


def source_clarification(ledger):
    """One Product re-read of the SAME brief, never a fabricated CEO answer."""
    if (not ledger or ledger.get('stage') != 'blocked_awaiting_ceo'
            or ledger.get('brief_clarification_product')):
        return None
    outputs = ledger.get('outputs') or {}
    if set(outputs) != {'product'}:
        raise ValueError('unexpected role outputs during Product clarification')
    proposal = parse_proposal(json.dumps(outputs['product']['proposal']), 'product')
    if not proposal['business_questions'] or ledger.get('questions') != proposal['business_questions']:
        raise ValueError('Product clarification questions identity drift')
    revised = {**ledger, 'outputs': {}, 'stage': 'clarifying_product_from_original_brief',
               'brief_clarification_product': 1,
               'prior_product_clarification': {'output': outputs['product'],
                    'issue_id': ledger['issues']['product'], 'questions': ledger['questions'],
                    'ceo_answer_created': False, 'scope_approval_created': False}}
    for key in ('owner', 'questions', 'category', 'next_action'):
        revised.pop(key, None)
    return revised


def product_protocol_revalidation(ledger):
    """One revalidation of an already persisted malformed Product reply.

    Never answer its questions or move a valid business question past the CEO.
    Existing schema-retry logic performs the fresh agent execution.
    """
    if (not ledger or ledger.get('stage') != 'blocked_awaiting_ceo'
            or ledger.get('rejected_product_protocol')
            or set(ledger.get('outputs') or {}) != {'product'}):
        return None
    try:
        parse_proposal(json.dumps(ledger['outputs']['product']['proposal']), 'product')
    except ValueError as error:
        if str(error) != 'planning output contains reasoning instead of product acceptance':
            raise
        revised = {**ledger, 'outputs': {}, 'stage': 'blocked', 'active': 'product',
            'owner': 'techlead', 'category': 'ValueError:' + str(error),
            'rejected_product_protocol': {'output': ledger['outputs']['product'],
                'issue_id': ledger['issues']['product'], 'questions': ledger.get('questions',[])}}
        revised.pop('questions', None)
        return revised
    return None


def cto_context_replan(ledger):
    """Let CTO author a concise replacement once; never truncate its decisions."""
    if (not ledger or ledger.get('stage') != 'blocked' or ledger.get('active') != 'techlead'
            or ledger.get('category') != 'ValueError:planning context exceeds issue limit'
            or ledger.get('cto_context_replanned')
            or set(ledger.get('outputs') or {}) != {'product', 'cto'}):
        return None
    revised = {**ledger, 'outputs': {'product': ledger['outputs']['product']},
        'stage': 'replanning_cto_context', 'active': 'cto', 'owner': 'cto',
        'cto_context_replanned': 1, 'schema_cto': 1,
        'prior_cto_context': {'output': ledger['outputs']['cto'],
            'issue_id': ledger['issues']['cto'], 'category': ledger['category'],
            'techlead_issue_id': ledger['issues'].get('techlead')}}
    revised.pop('category', None)
    return revised


def mark_working(ledger, role):
    if role not in ROLES:raise ValueError('unknown planning role')
    if ledger.get('category'):
        incident={k:ledger.get(k) for k in ('category','active','owner')}
        history=ledger.setdefault('prior_planning_incidents',[])
        if incident not in history:history.append(incident)
    ledger.pop('category',None)
    ledger.pop('next_action',None)
    ledger.update(stage='working_'+role,active=role,owner=role)


def completed_output(issue_id, agent_id, *, timeout=600):
    account = json.loads(AUTH.read_text())
    workspace = json.loads((PRIVATE / 'workspace.json').read_text())['id']
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        runs = [run for run in cli('runs', issue_id) if run.get('agent_id') == agent_id]
        if runs:
            latest = max(runs, key=lambda run: (run.get('created_at') or '', run['id']))
            if latest['status'] == 'failed':
                raise RuntimeError('planning agent task failed: ' + latest['id'])
            if latest['status'] == 'completed':
                messages = request('/api/tasks/' + latest['id'] + '/messages',
                                   token=account['token'], workspace=workspace)
                texts = [message.get('content') for message in messages
                         if message.get('type') == 'text' and isinstance(message.get('content'), str)]
                if not texts:
                    raise ValueError('completed planning task has no text proposal')
                combined = ''.join(texts)
                if len(combined) > 20000:
                    raise ValueError('completed planning output exceeds receipt limit')
                return latest['id'], combined
        time.sleep(5)
    raise TimeoutError('planning task deadline')


def main():
    from evalctl import PROJECT
    if PROJECT != 'delivery-kit-port2':
        raise ValueError('planning pilot restricted to isolated port2 installation')
    if BACKEND_PORT != '19081':
        raise ValueError('planning pilot requires port2 backend on 19081')
    selection = intake_configuration()
    name = selection['name']
    if selection['base_sha']:
        from prepare_issue_base import verified_main
        if verified_main() != selection['base_sha']:
            raise ValueError('planning base changed; replan required')
    brief = selection['brief'].read_text()
    body = brief_body(brief)
    digest = hashlib.sha256(brief.encode()).hexdigest()
    registry = json.loads((PRIVATE / 'planning-agents.json').read_text())
    ledger_path = PRIVATE / 'planning-intake' / (name + '.json')
    existing = json.loads(ledger_path.read_text()) if ledger_path.exists() else None
    if existing and existing.get('brief_sha256') != digest:
        raise ValueError('CEO brief changed during planning')
    if existing and selection['configuration_sha256'] and (
            existing.get('configuration_sha256') != selection['configuration_sha256']
            or existing.get('base_sha') != selection['base_sha']):
        raise ValueError('planning configuration changed during execution')
    if existing and existing.get('stage') == 'plan_ready' and selection['configuration_sha256']:
        try:
            validate_execution_plan(existing['outputs']['techlead']['proposal'], tracked_base(selection))
        except ValueError as error:
            if existing.get('capability_techlead'):
                raise
            existing.update(stage='capability_replanning', active='techlead', owner='techlead',
                            capability_techlead=1, rejected_capability_category=str(error),
                            rejected_capability_output=existing['outputs'].pop('techlead'))
            save_receipt(ledger_path, existing)
    from planning_ceo_answer import receipt_at, resume, context as answered_context
    human_answer = receipt_at(PRIVATE, name)
    if human_answer is not None:
        resumed = resume(existing, human_answer)
        if resumed is not None:
            existing = resumed
            save_receipt(ledger_path, existing)
    body = answered_context(body, existing or {})
    corrected = product_protocol_revalidation(existing)
    if corrected is not None:
        existing = corrected
        save_receipt(ledger_path, existing)
    replanned = cto_context_replan(existing)
    if replanned is not None:
        existing = replanned
        save_receipt(ledger_path, existing)
    clarified = source_clarification(existing)
    if clarified:
        existing = clarified
        save_receipt(ledger_path, existing)
    from planning_source_review import pending as source_pending,run as source_review
    if source_pending(existing):
        existing=source_review(existing,brief,registry,ledger_path)
    if existing and existing.get('stage') == 'blocked':
        from planning_constraint_recovery import observe
        recovered=observe(existing,registry,cli)
        if recovered:
            existing=recovered
            save_receipt(ledger_path,existing)
    if (existing and existing.get('stage') == 'blocked'
            and existing.get('active') in ROLES
            and existing.get('category', '').startswith(('JSONDecodeError:', 'ValueError:'))
            and not existing.get('retry_' + existing['active'])):
        role = existing['active']
        existing.update(stage='retrying_' + role, **{'retry_' + role: 1},
                        rejected_category=existing['category'])
        save_receipt(ledger_path, existing)
    elif (existing and existing.get('stage') == 'blocked'
            and existing.get('active') in ROLES
            and existing.get('retry_' + existing['active']) == 1
            and existing.get('category', '').startswith('ValueError:planning output schema mismatch')):
        existing['stage'] = 'revalidating_' + existing['active']
        save_receipt(ledger_path, existing)
    elif (existing and existing.get('stage') == 'blocked'
            and existing.get('active') == 'cto'
            and not existing.get('recovery_cto')
            and existing.get('category', '').startswith('RuntimeError:planning agent task failed:')):
        issue_id = existing['issues']['cto']
        runs = [run for run in cli('runs', issue_id)
                if run.get('agent_id') == registry['agents']['cto']]
        if (len(runs) == 1 and runs[0]['status'] == 'failed'
                and 'TimeoutError' in (runs[0].get('error') or '')):
            existing.update(stage='recovering_cto', recovery_cto=1,
                            failed_cto_task_id=runs[0]['id'],
                            failed_cto_category='prompt_timeout')
            save_receipt(ledger_path, existing)
    elif (existing and existing.get('stage') == 'blocked'
            and existing.get('category', '').endswith('/messages: HTTP 401')
            and existing.get('active') in ROLES):
        role = existing['active']
        runs = [run for run in cli('runs', existing['issues'][role])
                if run.get('agent_id') == registry['agents'][role]]
        if len(runs) == 1 and runs[0]['status'] == 'completed':
            existing['stage'] = 'reading_completed_' + role
            existing['recovered_read_error'] = 'wrong_backend_port'
            save_receipt(ledger_path, existing)
    elif (existing and existing.get('stage') == 'blocked'
            and existing.get('active') in ('cto', 'techlead')
            and not existing.get('schema_' + existing['active'])
            and existing.get('category', '').startswith('JSONDecodeError:')):
        role = existing['active']
        existing['stage'] = 'schema_recovery_' + role
        existing['schema_' + role] = 1
        existing['rejected_schema_source_issue_id'] = existing['issues'][role]
        save_receipt(ledger_path, existing)
    elif (existing and existing.get('stage') == 'blocked'
            and existing.get('configuration_sha256')
            and existing.get('active') in ROLES
            and existing.get('retry_' + existing['active']) == 1
            and not existing.get('schema_' + existing['active'])
            and existing.get('category') in ('ValueError:invalid planning output',
                                            'ValueError:unqualified test runner')):
        role = existing['active']
        existing.update(stage='schema_recovery_' + role,
                        **{'schema_' + role: 1},
                        rejected_schema_source_issue_id=existing['issues'][role])
        save_receipt(ledger_path, existing)
    elif (existing and existing.get('stage') == 'blocked'
            and existing.get('configuration_sha256')
            and existing.get('active') in ROLES
            and existing.get('schema_' + existing['active']) == 1
            and not existing.get('wire_' + existing['active'])
            and existing.get('category') == 'ValueError:invalid planning output'):
        role = existing['active']
        existing.update(stage='wire_recovery_' + role,
                        **{'wire_' + role: 1},
                        rejected_wire_source_issue_id=existing['issues'][role])
        save_receipt(ledger_path, existing)
    elif (existing and existing.get('stage') == 'blocked'
            and existing.get('active') == 'techlead'
            and existing.get('category') == 'ValueError:invalid proposed file'
            and existing.get('schema_techlead') == 1
            and not existing.get('path_policy_revalidated')):
        existing['stage'] = 'revalidating_techlead'
        existing['path_policy_revalidated'] = 1
        save_receipt(ledger_path, existing)
    elif existing and existing.get('stage') in ('blocked', 'blocked_awaiting_ceo'):
        print(json.dumps({'stage': existing['stage'], 'owner': existing.get('owner'),
                          'category': existing.get('category'),
                          'questions': existing.get('questions', [])}), flush=True)
        return 1
    if not existing:
        budget = check_model_budget()
        if budget['remaining'] < selection['minimum_calls']:
            raise ValueError('planning requires at least ' + str(selection['minimum_calls']) + ' model calls')
    ledger = existing or {'brief_sha256': digest, 'stage': 'planned', 'outputs': {}, 'issues': {}}
    capabilities = capability_context(selection)
    if selection['configuration_sha256']:
        ledger.update(configuration_sha256=selection['configuration_sha256'],
                      base_sha=selection['base_sha'], name=name)
    save_receipt(ledger_path, ledger)
    for role in ROLES:
        if role in ledger['outputs']:
            continue
        schema = bool(ledger.get('schema_' + role))
        wire = bool(ledger.get('wire_' + role))
        capability = bool(ledger.get('capability_' + role))
        context = ('DELIVERY_PLANNING_SCHEMA_V1:' + role + '\n'
                   'YOU ARE THE ' + role.upper() + '. Your response must have role="' + role + '". '
                   'Reply with one valid compact JSON object only, under 6000 characters.\n\n') + body
        for previous in ROLES[:ROLES.index(role)]:
            prior = ledger['outputs'][previous]['proposal']
            if schema and previous == 'product':
                prior = {'role': 'product', 'story_titles': [s['title'] for s in prior['stories']]}
            context += '\n\nVerified ' + previous + ' proposal:\n' + json.dumps(
                prior, ensure_ascii=False, separators=(',', ':'))
        retry = bool(ledger.get('retry_' + role))
        recovery = bool(ledger.get('recovery_' + role))
        if retry:
            context += ('\n\nFORMAT CORRECTION: Your previous reply was rejected. '
                        'Reply with ONLY one JSON object matching your role schema. '
                        'No Markdown, code fences or prose outside JSON. Do not claim '
                        'that files, cards or tests were created.')
            if role == 'product':
                context += (' Include user stories with acceptance and an empty '
                            'business_questions array if the brief is clear. '
                            'Do not choose architecture or deployment stack.')
            elif role == 'cto':
                context += (' Use exactly the keys role, stack, components, security, '
                            'technical_decisions and risks. Put technical choices in those fields.')
            else:
                context += (' Use exactly the keys role, cards and integration_order. '
                            'Each card needs id, title, owner, depends_on, acceptance, '
                            'files and test_command.')
        if recovery and not schema:
            context += ('\n\nRECOVERY AFTER VERIFIED PROMPT TIMEOUT: Do not revisit the '
                        'previous attempt. Respond in one compact JSON object under 1800 '
                        'characters. Use at most two concise entries per array. Choose a '
                        'single concrete stack and record unresolved details as risks. '
                        'No Markdown, tool use, or explanations outside JSON.')
        ceo_answer = role == 'product' and bool(ledger.get('ceo_answer'))
        clarification = role == 'product' and bool(ledger.get('brief_clarification_product')) and not ceo_answer
        reviewed = role == 'product' and bool(ledger.get('source_review_product'))
        if reviewed:
            context += ('\nCTO SOURCE REVIEW (not a CEO answer or new scope): '+
                json.dumps(ledger['source_review']['resolutions'])+
                '\nIncorporate these source-grounded answers into acceptance. '
                'Do not repeat a resolved question or expand beyond the original brief.')
        if ceo_answer:
            context += ('\nThe CEO has answered the exact pending business question above. '
                        'Update the Product acceptance accordingly; do not ask that resolved '
                        'question again. This answer does not approve architecture, tools, '
                        'merge, test exceptions or the entire brief. Return the Product schema.')
            if retry:
                context += (' Only user-visible acceptance belongs in stories. No internal '
                    'monologue, schema commentary or questions about server topology, '
                    'same-origin wiring or implementation: those choices belong to CTO. '
                    'The original brief already requires query variants to behave identically '
                    'and all non-200/failure responses to show Environment unavailable. '
                    'Ask the CEO only if a new user-visible business choice is truly missing.')
        if clarification:
            context += ('\n\nSOURCE-GROUNDED CLARIFICATION: Re-read the SAME CEO request above '
                        'before asking the CEO anything. Previous questions: ' +
                        json.dumps(ledger['prior_product_clarification']['questions']) + '. '
                        'Return a fresh Product proposal. If the original request already answers '
                        'these questions, encode its acceptance and use business_questions=[]. '
                        'If a real business decision is still missing, ask only that unresolved '
                        'question. Do not invent a CEO answer, broaden scope, choose architecture, '
                        'require a JSON serialization byte length or byte-identical HTTP headers '
                        'unless the original brief explicitly requires those. Preserve literal '
                        'UI text, including the Unicode ellipsis, from the original request.')
        if schema and role == 'cto':
            context += ('\n\nCTO SCHEMA: {"role":"cto","stack":"one concise stack",'
                        '"components":["component"],"security":["control"],'
                        '"technical_decisions":["decision"],"risks":[]}. '
                        'Replace values with real choices for this brief. Keep the whole '
                        'reply under 1000 characters. Do not copy the Product role field.')
            if ledger.get('cto_context_replanned'):
                context += (' The prior CTO reply exceeded downstream handoff capacity. '
                    'Author a fresh, concise proposal, not a transcript or token fragments. '
                    'Treat JSON examples as JSON objects, not byte serialization contracts. '
                    'Keep risk statements actionable; do not introduce business scope. '
                    'The full original brief and CEO answer above remain binding.')
        elif schema and role == 'techlead':
            context += ('\n\nTECHLEAD EXECUTION CONTRACT: Return JSON only with keys role, cards, '
                        'integration_order. Use 1 to 5 cards with IDs C1..C5 in dependency '
                        'order. Every card has exactly id, title, owner, depends_on, '
                        'acceptance, files, test_command. Owners ONLY backend_data, '
                        'frontend, devops, quality_security. Paths must be relative '
                        'under a project directory (e.g. app/server.js). '
                        'test_command is ONLY ["node","--test"] or '
                        '["python3","-m","unittest","discover","-s",".","-q"]. '
                        'Use short acceptance strings. Do not claim files or tests exist. '
                        'No shell operators, npm, npx, Docker commands or Markdown. '
                        'Example: {"role":"techlead","cards":[{"id":"C1",'
                        '"title":"API","owner":"backend_data","depends_on":[],'
                        '"acceptance":["API tests pass"],"files":["app/server.js"],'
                        '"test_command":["node","--test"]}],"integration_order":["C1"]}.')
        context += capabilities
        answer = None
        try:
            issue_id = issue_for(role, context, registry['agents'][role],
                                 retry=retry, recovery=recovery, schema=schema, run_name=name, wire=wire, capability=capability,
                                 clarification=clarification, ceo_answer=ceo_answer,source_review=reviewed)
            ledger['issues'][role] = issue_id
            mark_working(ledger, role)
            save_receipt(ledger_path, ledger)
            task_id, answer = completed_output(issue_id, registry['agents'][role])
            proposal = parse_proposal(answer, role)
            if role == 'techlead' and selection['configuration_sha256']:
                validate_execution_plan(proposal, tracked_base(selection))
            ledger['outputs'][role] = {'task_id': task_id, 'proposal': proposal,
                                       'content_sha256': hashlib.sha256(answer.encode()).hexdigest()}
            ledger['stage'] = 'completed_' + role
            save_receipt(ledger_path, ledger)
            if role == 'product' and proposal['business_questions']:
                if reviewed:
                    ledger.update(stage='blocked',owner='techlead',active='product',
                        category='Product questions persisted after independent source review',
                        next_action='Tech Lead diagnoses Product protocol; never fabricate a CEO answer')
                    save_receipt(ledger_path,ledger)
                    return 1
                ledger.update(stage='blocked_awaiting_ceo', owner='ceo',
                              questions=proposal['business_questions'])
                save_receipt(ledger_path, ledger)
                print(json.dumps({'stage': ledger['stage'], 'questions': ledger['questions']}))
                return 1
        except Exception as error:
            if answer is not None and not retry:
                ledger.update(stage='retrying_' + role, **{'retry_' + role: 1},
                              rejected_task_id=task_id,
                              rejected_output_sha256=hashlib.sha256(answer.encode()).hexdigest(),
                              rejected_category=(type(error).__name__ + ':' + str(error))[:180])
                save_receipt(ledger_path, ledger)
                return main()
            ledger.update(stage='blocked', owner='techlead' if role != 'cto' else 'cto',
                          category=(type(error).__name__ + ':' + str(error))[:180],
                          next_action='Diagnose planning task and resume from its durable issue',
                          active=role)
            save_receipt(ledger_path, ledger)
            print(json.dumps({'stage': 'blocked', 'role': role,
                              'category': ledger['category']}), flush=True)
            return 1
    ledger['stage'] = 'plan_ready'
    for field in ('active', 'owner', 'category', 'next_action'):
        ledger.pop(field, None)
    save_receipt(ledger_path, ledger)
    print(json.dumps({'stage': 'plan_ready', 'issues': ledger['issues'],
                      'cards': len(ledger['outputs']['techlead']['proposal']['cards'])}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
