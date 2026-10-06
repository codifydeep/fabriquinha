"""One bounded, CTO-sponsored child; never unfreeze or approve its parent."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from portable_run_spec import validate
from release_eval import save_receipt
from start_eval import check_model_budget

ROOT = Path(__file__).resolve().parent


def publish_recovered_parent(cli, context, child, receipt, *, lineage=()):
    """Project proven child delivery without approving the rejected parent snapshot."""
    sha = receipt.get('merge_sha')
    browser = receipt.get('browser_qa', {})
    if (not isinstance(sha, str) or len(sha) != 40
            or any(ch not in '0123456789abcdef' for ch in sha)
            or child.get('issue_id') == context.get('issue_id')
            or receipt.get('issue_id') != (lineage[-1] if lineage else child.get('issue_id'))
            or receipt.get('base_sha') != context.get('base_sha')
            or receipt.get('contract_sha256') != context.get('contract_sha256')
            or receipt.get('stage') != 'deployed_qa_passed'
            or receipt.get('board', {}).get('status') != 'done'
            or browser.get('status') != 'passed' or browser.get('cleanup') != 'passed'
            or browser.get('automated') is not True
            or browser.get('identity', {}).get('source_sha') != sha
            or browser.get('result', {}).get('source_sha') != sha
            or browser.get('result', {}).get('status') != 'passed'
            or receipt.get('deployment', {}).get('status') != 'passed'
            or receipt.get('deployment', {}).get('source_sha') != sha
            or not receipt.get('main_ci_run') or not receipt.get('pr_url')):
        raise ValueError('exact child homologation required for parent recovery')
    if lineage:
        chain = [child['issue_id'], *lineage]
        if len(chain) > 3 or len(set(chain)) != len(chain) or context['issue_id'] in chain:
            raise ValueError('invalid recovery lineage')
        for origin, destination in zip(chain, chain[1:]):
            link = cli('metadata', 'list', origin)
            if (cli('get', origin).get('status') != 'done'
                    or link.get('test_revision_child_issue') != destination
                    or link.get('test_revision_recovery') != 'recovered_by_test_revision'
                    or link.get('recovery_receipt_sha') != sha
                    or link.get('recovery_pr_url') != receipt['pr_url']):
                raise ValueError('unproven recovery lineage')
    parent_id = context['issue_id']
    metadata = cli('metadata', 'list', parent_id)
    if metadata.get('test_revision_child_issue') != child['issue_id']:
        raise ValueError('parent recovery child linkage drift')
    child_item = cli('get', child['issue_id'])
    if child_item.get('status') != 'done':
        raise ValueError('child card is not delivered')
    parent = cli('get', parent_id)
    if parent.get('status') not in ('todo', 'in_progress', 'blocked', 'done'):
        raise ValueError('parent recovery cannot override cancellation or unknown state')
    fields = {'test_revision_recovery': 'recovered_by_test_revision',
              'recovery_receipt_sha': sha, 'recovery_pr_url': receipt['pr_url'],
              'recovery_main_ci_url': receipt['main_ci_run'],
              'recovery_qa_url': receipt['deployment']['url']}
    # Check every binding before the first mutation. Preserve original rejection
    # and browser_acceptance fields: this is the child's delivery, not its parent.
    if any(k in metadata and metadata[k] != v for k, v in fields.items()):
        raise ValueError('parent recovery evidence drift')
    for key, value in fields.items():
        if key not in metadata:
            cli('metadata', 'set', parent_id, '--key', key, '--value', value, '--type', 'string')
    if parent['status'] != 'done':
        cli('status', parent_id, 'done', '--no-start')
    return {'status': 'done', 'via': 'test_revision_child',
            'child_issue': child['issue_id'], 'merge_sha': sha}


def reconcile_ancestors(private, label, cli):
    """Completion-driven, bottom-up projection; never launch workers or forge receipts."""
    private = Path(private)
    def read(path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 131072:
            raise ValueError('unsafe recovery evidence')
        return json.loads(path.read_text())
    leaf = read(private / ('portable-context-' + label + '.json'))
    receipt = read(private / 'release-receipts' / (label + '.json'))
    if receipt.get('issue_id') != leaf['issue_id'] or receipt.get('label') != label:
        raise ValueError('recovery leaf identity drift')
    current, lineage, results = leaf, [], []
    while True:
        matches = []
        for path in (private / 'test-revision-recovery').glob('*.json'):
            if path.name.endswith('.run.json'):
                continue
            intent = read(path)
            if (intent.get('child_issue') == current['issue_id']
                    and path.stem == intent.get('parent_issue')):
                matches.append((path, intent))
        if not matches:
            return results
        if len(matches) != 1 or len(results) >= 2:
            raise ValueError('ambiguous or excessive recovery ancestry')
        path, intent = matches[0]
        spec = intent.get('spec', {})
        digest = hashlib.sha256(json.dumps(spec, sort_keys=True,
                                separators=(',', ':')).encode()).hexdigest()
        if (intent.get('label') != current.get('label')
                or spec.get('label') != current.get('label')
                or current.get('run_spec_sha256') != digest
                or current.get('base_sha') != receipt.get('base_sha')
                or current.get('contract_sha256') != receipt.get('contract_sha256')):
            raise ValueError('recovery intent child label drift')
        contexts = [read(p) for p in private.glob('portable-context-*.json')]
        parents = [c for c in contexts if c.get('issue_id') == intent['parent_issue']]
        if len(parents) != 1:
            raise ValueError('recovery parent context missing or ambiguous')
        parent = parents[0]
        board = publish_recovered_parent(cli, parent, current, receipt, lineage=lineage)
        intent.update(stage='recovered_by_test_revision', parent_board=board,
                      child_receipt=str(private / 'release-receipts' / (label + '.json')),
                      merge_sha=receipt['merge_sha'], pr_url=receipt['pr_url'])
        save_receipt(path, intent)
        save_receipt(private / 'autonomy-status' / (parent['label'] + '.json'),
                     {'label': parent['label'], 'issue_id': parent['issue_id'],
                      'stage': 'recovered_by_test_revision', 'child_issue_id': current['issue_id'],
                      'merge_sha': receipt['merge_sha'], 'pr_url': receipt['pr_url'],
                      'qa_url': receipt['deployment']['url']})
        results.append(board)
        lineage = [current['issue_id'], *lineage]
        current = parent


def child_spec(context, spec, managed):
    route, state = managed['route'], managed['state']
    data = json.loads(state['data'])
    proposal = data.get('test_revision_proposal', {})
    if (state['stage'] != 'test_revision_required' or data.get('target') != route['cto']
            or not route.get('test_first') or not proposal.get('decision_task')
            or proposal.get('source_task') != data.get('source_task')
            or set(proposal.get('new_test_files', [])) != set(route['test_first_files'])
            or data.get('decision', {}).get('action') != 'request_test_revision'
            or data.get('decision', {}).get('optional_files') != []
            or not isinstance(proposal.get('reason'), str)):
        raise ValueError('exact CTO-sponsored test revision required')
    key = hashlib.sha256((context['issue_id'] + ':' + proposal['decision_task']).encode()).hexdigest()[:12]
    label = 'TESTREV' + key.upper() + '-1'
    result = {k: v for k, v in spec.items() if k != 'sha256'}
    description=spec['description'];review=spec.get('review_instruction')
    capsule=spec.get('execution_context')
    if capsule:
        from execution_context import resolve
        description=resolve(capsule,description,'implementation')
        review=resolve(capsule,review,'review')
    result.update(label=label, title=label + ' — CTO-sponsored new-test repair and full delivery',
        description=description.split('\nCTO-SPONSORED NEW TEST REVISION:', 1)[0]
        + '\nCTO-SPONSORED NEW TEST REVISION: ' + proposal['reason']
        + '\nThis is a NEW child on the ORIGINAL Git base, not permission to change '
        'the old snapshot. The controller seeds only the declared NEW test from '
        'the prior immutable Red into your workspace. Read it and make a targeted '
        'correction; do not recreate it from scratch. Preserve existing behavioral '
        'coverage and use distinct pre-submit and pending observations. Keep consistent mock '
        'state transitions and all required behavioral coverage. In particular, '
        'failed operations must not fabricate committed backend state. Do not '
        'remove rendering/summary coverage or loosen assertions to hide a defect. '
        'Controller captures a NEW Red and an independent profile compares the '
        'candidate against the prior frozen test BEFORE implementation. Then follow '
        'the same code scope, full suite, delivery review and browser acceptance.')
    if data.get('semantic_fixture_experiment'):
        from broker.candidate_qualification import validate_semantic_checks, experiment_hash, validate_repair_findings
        proof = data['semantic_fixture_experiment']
        qualification = data.get('candidate_qualification') or {}
        if (qualification.get('stage') != 'semantic_test_revision_qualified'
                or qualification.get('sponsor_task') != proposal['decision_task']):
            raise ValueError('experiment-consistent test revision sponsorship required')
        validate_semantic_checks(qualification['review_decision'], proof)
        validate_semantic_checks(qualification['sponsor_decision'], proof)
        contradictions = validate_repair_findings(data.get('semantic_repair_findings'), proof, route['test_first_files'])
        # Preserve the sponsor's historical prose in controller state, but never
        # send contradictory prose as the author's operative repair instruction.
        result['description'] = result['description'].replace(
            '\nCTO-SPONSORED NEW TEST REVISION: ' + proposal['reason'],
            '\nCTO-SPONSORED NEW TEST REVISION: Correct the mechanically verified '
            'NEW assertion contradictions below, preserving behavioral coverage.')
        result['description'] += ('\nSOURCE-BOUND ASSERTION FINDINGS: '
            + json.dumps(contradictions, ensure_ascii=False, separators=(',', ':')))
        facts = [[f['file'], f['query_line'], f['query'], f['title'], f['casefold_substring']]
                 for f in proof['facts']]
        result['description'] += ('\nCONTROLLER STRING EXPERIMENT ' + experiment_hash(proof)
            + ': [file, physical line, query, fixture title, casefold_substring] '
            + json.dumps(facts, ensure_ascii=False, separators=(',', ':'))
            + '\nThese are primitive string facts, not permission to alter baseline tests '
            'or product semantics. Correct the contradictory NEW expectations while '
            'retaining substring, genuine nonmatch and accent-preserving Unicode coverage. '
            'Do not mistake comparisons to unrelated fixtures for failing assertions.')
    if data.get('assertion_replan'):
        from broker.assertion_replan import validated_record
        proof = validated_record(data)
        result['description'] += ('\nSOURCE-BOUND ASSERTION FINDINGS: '
            + json.dumps(proof['contradictions'], ensure_ascii=False, separators=(',', ':'))
            + '\nCorrect EVERY listed contradictory NEW assertion; retain each assertion, '
            'genuine nonmatch and accent-preserving casefold coverage. Do not alter product '
            'semantics to satisfy an incorrect expectation. The next candidate is checked '
            'deterministically before independent review and before any implementation permission.')
    if len(result['title']) > 200 or len(result['description']) > (12000 if capsule else 8000):
        raise ValueError('test revision child brief exceeds bounded controller context')
    if capsule:
        from execution_context import freeze,reference
        updated=freeze(result['description'],review)
        result.update(execution_context=updated,description=reference(updated,'implementation'),
                      review_instruction=reference(updated,'review'))
    return result


def next_revision_depth(context, managed, depth):
    """An additional revision needs a controller-recorded, source-bound replan.

    The certificate is broker state, not worker text or an environment override.
    Only one additional level is supported; further failures stay escalated.
    """
    if depth == '0':
        return '1'
    data = json.loads(managed['state']['data'])
    proof = data.get('technical_replan_certificate') or {}
    proposal = data.get('test_revision_proposal') or {}
    reads = proof.get('read_evidence') or {}
    paths = proof.get('required_read_paths') or []
    if (depth != '1' or proof.get('version') != 'complete-source-replan-v1'
            or proof.get('issue_id') != context['issue_id']
            or proof.get('source_task') != managed['state']['source_task']
            or proof.get('decision_task') != proposal.get('decision_task')
            or proof.get('source_task') != proposal.get('source_task')
            or proof.get('output_sha256') != proposal.get('output_sha256')
            or proof.get('decision_task') == (data.get('prior_capture_diagnosis') or {}).get('task')
            or not isinstance(reads, dict) or not isinstance(paths, list) or not paths
            or any(not isinstance(path, str) or path not in reads
                   or type(reads[path].get('lines')) is not int or reads[path]['lines'] <= 0
                   or reads[path]['lines'] != reads[path].get('total_lines') for path in paths)
            or proof.get('read_contract') != 'complete-lines-v2'
            or proof.get('baseline_edits_allowed') is not False):
        raise ValueError('second test revision requires new technical replan')
    return '2'


def schedule(private, context, spec, contract, managed):
    child_depth = next_revision_depth(context, managed,
        os.environ.get('DELIVERY_KIT_TEST_REVISION_DEPTH', '0'))
    selected = validate(child_spec(context, spec, managed), contract)
    root = Path(private) / 'test-revision-recovery'
    root.mkdir(parents=True, exist_ok=True)
    path = root / (context['issue_id'] + '.json')
    spec_path = root / (selected['label'] + '.run.json')
    if path.exists():
        intent = json.loads(path.read_text())
        if intent['spec'] != selected or intent['parent_issue'] != context['issue_id']:
            raise ValueError('test revision recovery identity drift')
    else:
        check_model_budget()
        from prepare_issue_base import verified_main
        if verified_main() != context['base_sha']:
            raise ValueError('test revision original main base moved')
        intent = {'parent_issue': context['issue_id'], 'spec': selected, 'stage': 'intent'}
        save_receipt(path, intent)
        save_receipt(spec_path, selected)
    if json.loads(spec_path.read_text()) != selected:
        raise ValueError('test revision spec drift')
    env = {**os.environ, 'DELIVERY_KIT_RUN_SPEC': str(spec_path),
           'DELIVERY_KIT_TEST_FIRST': '1', 'DELIVERY_KIT_TEST_REVISION_PARENT': context['issue_id'],
           'DELIVERY_KIT_TEST_REVISION_DEPTH': child_depth}
    env.pop('DELIVERY_KIT_EXISTING_ISSUE_ID', None)
    env.pop('DELIVERY_KIT_EXPECTED_PLAN_SHA', None)
    child_context_path = Path(private) / ('portable-context-' + selected['label'] + '.json')
    if not child_context_path.exists():
        subprocess.run([sys.executable, str(ROOT / 'start_portable.py')], cwd=ROOT,
                       env=env, check=True)
    child = json.loads(child_context_path.read_text())
    if (child['base_sha'] != context['base_sha']
            or child['contract_sha256'] != context['contract_sha256']
            or child.get('label') != selected['label']
            or child.get('run_spec_sha256') != hashlib.sha256(json.dumps(selected,
                sort_keys=True, separators=(',', ':')).encode()).hexdigest()):
        raise ValueError('test revision child changed scope or base')
    if intent.get('child_issue') not in (None, child['issue_id']):
        raise ValueError('test revision child identity drift')
    intent.update(child_issue=child['issue_id'], label=selected['label'])
    from start_eval import cli
    metadata = cli('metadata', 'list', context['issue_id'])
    linked = metadata.get('test_revision_child_issue')
    if linked not in (None, child['issue_id']):
        raise ValueError('parent linked to a different test revision')
    if linked is None:
        cli('metadata', 'set', context['issue_id'], '--key', 'test_revision_child_issue',
            '--value', child['issue_id'], '--type', 'string')
    child_status = Path(private) / 'autonomy-status' / (selected['label'] + '.json')
    progress = json.loads(child_status.read_text()) if child_status.exists() else {}
    from portable_supervisor import COMPLETE, STOP
    if progress.get('stage') in STOP:
        from pre_red_supervision import qualified
        if qualified(progress,child):
            # Wake only supervision of the already existing native incident.
            # Preserve the blocked receipt; the controller will re-read it.
            progress={**progress,'stage':'qualified_supervision_reentry'}
    if progress.get('stage') in COMPLETE:
        if progress['stage'] == 'recovered_by_test_revision':
            descendant_path = root / (child['issue_id'] + '.json')
            if descendant_path.is_symlink():
                raise ValueError('unsafe descendant recovery')
            descendant = json.loads(descendant_path.read_text())
            leaf_path = Path(descendant.get('child_receipt', ''))
            if (descendant.get('stage') != 'recovered_by_test_revision'
                    or leaf_path.parent != Path(private) / 'release-receipts'
                    or leaf_path.is_symlink()):
                raise ValueError('unproven descendant recovery receipt')
            leaf_receipt = json.loads(leaf_path.read_text())
            reconcile_ancestors(private, leaf_receipt['label'], cli)
            result = json.loads(path.read_text())
            if result.get('stage') != 'recovered_by_test_revision':
                raise ValueError('ancestor recovery projection incomplete')
            return result
        receipt_path = Path(private) / 'release-receipts' / (selected['label'] + '.json')
        receipt = json.loads(receipt_path.read_text())
        if (receipt.get('stage') != 'deployed_qa_passed'
                or receipt.get('browser_qa', {}).get('status') != 'passed'):
            raise ValueError('child delivery evidence incomplete')
        intent.update(stage='recovered_by_test_revision', child_receipt=str(receipt_path),
                      merge_sha=receipt['merge_sha'], pr_url=receipt['pr_url'])
        intent['parent_board'] = publish_recovered_parent(cli, context, child, receipt)
    elif progress.get('stage') in STOP:
        intent.update(stage='test_revision_child_blocked', child_status=progress)
    else:
        pid = intent.get('pid')
        process = subprocess.run(['ps', '-p', str(pid or 0), '-o', 'command='],
                                 text=True, capture_output=True)
        running = (process.returncode == 0 and str(ROOT / 'portable_supervisor.py') in process.stdout
                   and '--managed-label ' + selected['label'] in process.stdout)
        if not running:
            with (root / (selected['label'] + '.log')).open('a') as log:
                worker = subprocess.Popen([sys.executable, '-u', str(ROOT / 'portable_supervisor.py'),
                    '--managed-label', selected['label']],
                    cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    start_new_session=True)
            intent['pid'] = worker.pid
        intent['stage'] = 'test_revision_child_running'
    save_receipt(path, intent)
    return intent
