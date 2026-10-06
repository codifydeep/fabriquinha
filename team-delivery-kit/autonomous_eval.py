"""Sandbox-only, resumable Multica issue -> protected PR -> local QA.

Multica owns agent scheduling. This process only reconciles trusted GitHub and
Docker side effects after an exact independent approval. It is deliberately
restricted to the public disposable calculator repository and a fixed allowlist.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

import deploy_eval
import release_eval
from broker.base_gate import FILES, verify_base_compatible
from evalctl import PRIVATE
from start_eval import cli, ensure_started


REPO = deploy_eval.REPO
REPOSITORY = release_eval.REPOSITORY
RECEIPTS = release_eval.RECEIPTS
LABEL = 'EVAL-15'
FEATURE = 'negate'
REQUIRED_TESTS = {'test_negate_positive', 'test_negate_negative'}
SLOT = 5
WAIT_SECONDS = 10
STATUS = PRIVATE / 'autonomy-status' / (LABEL + '.json')
CONFIGS = {
    'EVAL-15': ('negate', {'test_negate_positive', 'test_negate_negative'}, 5),
    'EVAL-16': ('absolute', {'test_absolute_positive', 'test_absolute_negative'}, 6),
    'EVAL-18': ('double', {'test_double_positive', 'test_double_negative'}, 7),
    'EVAL-19': ('double', {'test_double_positive', 'test_double_negative'}, 7),
    'EVAL-20': ('double', {'test_double_positive', 'test_double_negative'}, 7),
    'PORT-1': ('cube', {'test_cube_positive', 'test_cube_negative'}, 8),
    'PORT-2': ('negate', {'test_negate_positive', 'test_negate_negative'}, 9),
    'PORT-3': ('negate', {'test_negate_positive', 'test_negate_negative'}, 9),
}


class WaitingApproval(Exception):
    pass


class InjectedCrash(Exception):
    pass


def git(*args, data=None, env=None):
    return subprocess.check_output(['git', '-C', str(REPO), *args], input=data,
                                   env=env).decode().strip()


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def json_command(*args):
    return json.loads(command(*args))


def persist(path, receipt, stage):
    receipt['stage'] = stage
    receipt['updated_at'] = time.time()
    release_eval.save_receipt(path, receipt)
    if os.environ.get('EVAL_INJECT_AFTER') == stage:
        raise InjectedCrash('injected crash after ' + stage)


def publish_status(stage, issue_id, **details):
    STATUS.parent.mkdir(mode=0o700, exist_ok=True)
    if STATUS.parent.is_symlink():
        raise ValueError('unsafe autonomy status directory')
    release_eval.save_receipt(STATUS, {
        'identifier': LABEL, 'issue_id': issue_id, 'stage': stage,
        'updated_at': time.time(), **details})


def approved(issue_id):
    try:
        return release_eval.approved_submission(issue_id)
    except ValueError as error:
        if str(error) in ('expected one approved exact revision', 'no completed implementation'):
            reviewer_id = json.loads((PRIVATE / 'reviewer.json').read_text())['agent_id']
            reviews = [run for run in cli('runs', issue_id)
                       if run.get('agent_id') == reviewer_id]
            latest = max(reviews, key=lambda run: (run.get('created_at') or '', run['id'])) if reviews else None
            if latest is None:
                raise WaitingApproval(str(error)) from None
            query = ('import json,sqlite3,sys; '
                     'c=sqlite3.connect("file:/broker-state/leases.sqlite?mode=ro",uri=True); '
                     'r=c.execute("SELECT reason,status FROM review_incidents '
                     'WHERE review_task_id=?",(sys.argv[1],)).fetchone(); '
                     'h=c.execute("SELECT error_type,attempts FROM change_handoff_failures '
                     'WHERE review_task_id=?",(sys.argv[1],)).fetchone(); '
                     'print(json.dumps({"incident":r,"handoff":h}))')
            # The broker may not yet have an incident; an exhausted retry is a
            # durable technical block, never an invitation to wait forever.
            state = json.loads(subprocess.check_output(
                ['docker', 'exec', release_eval.BROKER, 'python3', '-c', query, latest['id']],
                text=True))
            incident = state['incident']
            handoff = state['handoff']
            if incident and incident[1] in ('escalation_required', 'infrastructure_model_limit'):
                raise ValueError('review escalation: ' + incident[0]) from None
            if handoff and handoff[1] >= 2:
                raise ValueError('change handoff escalation: ' + handoff[0]) from None
            raise WaitingApproval(str(error)) from None
        raise


def snapshot_preflight(delivery, base):
    with tempfile.TemporaryDirectory(prefix='delivery-kit-approved-') as directory:
        path = Path(directory)
        release_eval.export_snapshot(delivery, path)
        if git('rev-parse', 'main') == base:
            result = verify_base_compatible(REPO, base, path, current_ref='main')
        else:
            # After a protected merge, base compatibility was already frozen in
            # the receipt; still rehash every byte against that approval.
            manifest = (path / 'manifest.json').read_bytes()
            import hashlib
            if hashlib.sha256(manifest).hexdigest() != delivery['manifest_sha256']:
                raise ValueError('approved manifest changed')
            result = {'manifest_sha256': delivery['manifest_sha256']}
        if result['manifest_sha256'] != delivery['manifest_sha256']:
            raise ValueError('approved snapshot hash changed')
        return {name: (path / name).read_bytes() for name in FILES}, result


def verify_commit(head, base, files):
    if git('rev-parse', head + '^') != base:
        raise ValueError('reviewed branch parent changed')
    if set(git('diff', '--name-only', base, head).splitlines()) != {'calc.py', 'test_calc.py'}:
        raise ValueError('unexpected reviewed branch diff')
    for name, content in files.items():
        if subprocess.check_output(['git', '-C', str(REPO), 'show', head + ':' + name]) != content:
            raise ValueError('reviewed branch bytes differ from snapshot')


def ensure_branch(branch, base, files):
    ref = 'refs/heads/' + branch
    local = subprocess.run(['git', '-C', str(REPO), 'rev-parse', '--verify', ref],
                           text=True, capture_output=True)
    if local.returncode == 0:
        head = local.stdout.strip()
    else:
        remote = git('ls-remote', 'origin', ref)
        if remote:
            head = remote.split()[0]
            subprocess.run(['git', '-C', str(REPO), 'fetch', 'origin', head], check=True)
            git('update-ref', ref, head, '0' * 40)
        else:
            if git('rev-parse', 'main') != base:
                raise ValueError('main moved before branch creation')
            with tempfile.TemporaryDirectory(prefix='delivery-kit-index-') as directory:
                index = str(Path(directory) / 'index')
                env = {**os.environ, 'GIT_INDEX_FILE': index}
                git('read-tree', base, env=env)
                for name, content in files.items():
                    blob = git('hash-object', '-w', '--stdin', data=content)
                    git('update-index', '--add', '--cacheinfo', f'100644,{blob},{name}', env=env)
                tree = git('write-tree', env=env)
            head = git('commit-tree', tree, '-p', base, '-m', LABEL + ': reviewed ' + FEATURE + ' delivery')
            git('update-ref', ref, head, '0' * 40)
    verify_commit(head, base, files)
    remote = git('ls-remote', 'origin', ref)
    if remote and remote.split()[0] != head:
        raise ValueError('remote reviewed branch moved')
    if not remote:
        subprocess.run(['git', '-C', str(REPO), 'push', 'origin', ref + ':' + ref], check=True)
    return head


def ensure_pr(branch, head, base, delivery):
    prs = json_command('gh', 'pr', 'list', '-R', REPOSITORY, '--state', 'all',
                       '--head', branch, '--json',
                       'number,state,headRefOid,baseRefOid,mergeCommit,url')
    if len(prs) > 1:
        raise ValueError('duplicate release PRs')
    if not prs:
        body = ('Approved frozen delivery.\nSource task: ' + delivery['source_task']
                + '\nIndependent review: ' + delivery['review_task']
                + '\nManifest SHA-256: ' + delivery['manifest_sha256']
                + '\nRequired tests: ' + ', '.join(sorted(REQUIRED_TESTS)) + '. '
                'Protected CI and same-commit local QA are required.')
        command('gh', 'pr', 'create', '-R', REPOSITORY, '--base', 'main', '--head', branch,
                '--title', LABEL + ': reviewed ' + FEATURE + ' feature', '--body', body)
        prs = json_command('gh', 'pr', 'list', '-R', REPOSITORY, '--state', 'all',
                           '--head', branch, '--json',
                           'number,state,headRefOid,baseRefOid,mergeCommit,url')
    if len(prs) != 1 or prs[0]['headRefOid'] != head or prs[0]['baseRefOid'] != base \
            or prs[0]['state'] not in ('OPEN', 'MERGED'):
        raise ValueError('release PR identity changed')
    return prs[0]


def ensure_merged(pr, head, base, issue_id, delivery, files):
    if pr['state'] == 'OPEN':
        release_eval.wait_pr_ci(pr['number'], head, base)
        if approved(issue_id) != delivery:
            raise ValueError('approval changed before merge')
        if git('rev-parse', 'main') != base:
            raise ValueError('main moved before merge')
        release_eval.wait_pr_ci(pr['number'], head, base, timeout=10)
        subprocess.run(['gh', 'pr', 'merge', str(pr['number']), '-R', REPOSITORY,
                        '--squash'], check=True)
    merged = json_command('gh', 'pr', 'view', str(pr['number']), '-R', REPOSITORY,
                          '--json', 'state,mergeCommit,headRefOid,baseRefOid')
    if merged['state'] != 'MERGED' or merged['headRefOid'] != head \
            or merged['baseRefOid'] != base or not merged['mergeCommit']:
        raise ValueError('protected merge identity mismatch')
    sha = merged['mergeCommit']['oid']
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('invalid merge SHA')
    # A squash changes commit identity but must not change reviewed bytes.
    subprocess.run(['git', '-C', str(REPO), 'fetch', 'origin', 'main'], check=True)
    if subprocess.run(['git', '-C', str(REPO), 'merge-base', '--is-ancestor',
                       sha, 'origin/main']).returncode != 0:
        raise ValueError('merged commit is not in remote main history')
    if git('branch', '--show-current') != 'main':
        raise ValueError('local checkout is not main')
    if git('rev-parse', 'main') != sha:
        subprocess.run(['git', '-C', str(REPO), 'merge', '--ff-only', 'origin/main'], check=True)
    for name, content in files.items():
        if subprocess.check_output(['git', '-C', str(REPO), 'show', sha + ':' + name]) != content:
            raise ValueError('merged bytes differ from approved snapshot')
    return sha


def wait_exact_main_ci(sha, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        runs = json_command('gh', 'api',
                            'repos/' + REPOSITORY + '/actions/runs?head_sha=' + sha)
        matches = [run for run in runs.get('workflow_runs', [])
                   if run.get('head_sha') == sha and run.get('event') == 'push'
                   and run.get('path') == '.github/workflows/ci.yml'
                   and run.get('conclusion') == 'success']
        if matches:
            return matches[0]['html_url']
        time.sleep(5)
    raise TimeoutError('automatic CI missing on exact historical main SHA')


def ensure_deployed(sha):
    name = deploy_eval.SLOTS[SLOT][0]
    existing = subprocess.run(['docker', 'inspect', name], capture_output=True)
    if existing.returncode == 0:
        return deploy_eval.verify_existing(SLOT, sha)
    result = json_command(sys.executable, str(Path(__file__).parent / 'deploy_eval.py'),
                          '--slot', str(SLOT))
    if result.get('source_sha') != sha or result.get('feature_qa') != FEATURE \
            or result.get('qa_status') != 'passed' or result.get('post_deploy_qa_cases', 0) < len(deploy_eval.qa_cases(SLOT)):
        raise ValueError('post-deploy QA identity mismatch')
    return deploy_eval.verify_existing(SLOT, sha)


def publish_board_receipt(issue_id, receipt):
    sha = receipt['merge_sha']
    # A normal operator comment wakes the assigned agent even after the release
    # has reached done. Metadata is durable, visible on the issue and does not
    # enqueue an unnecessary post-delivery implementation run.
    fields = {
        'delivery_receipt_sha': sha,
        'delivery_manifest_sha256': receipt['delivery']['manifest_sha256'],
        'delivery_pr_url': receipt['pr_url'],
        'delivery_main_ci_url': receipt['main_ci_run'],
        'delivery_qa_url': receipt['deployment']['url'],
        'delivery_qa_cases': str(receipt['deployment']['post_deploy_qa_cases']),
    }
    existing = cli('metadata', 'list', issue_id)
    if not isinstance(existing, dict):
        raise ValueError('invalid issue metadata')
    for key, value in fields.items():
        if key in existing and existing[key] != value:
            raise ValueError('delivery receipt metadata changed: ' + key)
        if key not in existing:
            cli('metadata', 'set', issue_id, '--key', key,
                '--value', value, '--type', 'string')
    issue = cli('get', issue_id)
    if issue.get('status') != 'done':
        if issue.get('status') not in ('todo', 'in_progress', 'in_review'):
            raise ValueError('unexpected issue status before delivery')
        result = cli('status', issue_id, 'done', '--no-start')
        if result.get('status') != 'done':
            raise ValueError('board did not confirm done')
    return {'status': 'done', 'receipt_sha': sha, 'storage': 'issue_metadata'}


def reconcile(context):
    issue_id, base = context['issue_id'], context['base_sha']
    path = RECEIPTS / (LABEL + '.json')
    if path.exists():
        receipt = json.loads(path.read_text())
        if receipt.get('issue_id') != issue_id or receipt.get('base_sha') != base \
                or receipt.get('identifier') != LABEL:
            raise ValueError('release receipt identity mismatch')
    else:
        receipt = {'issue_id': issue_id, 'base_sha': base, 'identifier': LABEL,
                   'branch': 'codex/' + LABEL.lower() + '-reviewed'}
    delivery = approved(issue_id)
    if receipt.get('delivery') and receipt['delivery'] != delivery:
        raise ValueError('approved delivery changed')
    receipt['delivery'] = delivery
    files, preflight = snapshot_preflight(delivery, base)
    if 'new_tests' in preflight and not REQUIRED_TESTS <= set(preflight['new_tests']):
        raise ValueError('required tests absent from approved snapshot')
    if not receipt.get('stage'):
        persist(path, receipt, 'preflight_passed')
    branch = receipt['branch']
    head = ensure_branch(branch, base, files)
    if receipt.get('head_sha') and receipt['head_sha'] != head:
        raise ValueError('reviewed branch moved')
    receipt['head_sha'] = head
    if receipt['stage'] == 'preflight_passed':
        persist(path, receipt, 'branch_pushed')
    pr = ensure_pr(branch, head, base, delivery)
    if receipt.get('pr_url') and receipt['pr_url'] != pr['url']:
        raise ValueError('release PR changed')
    receipt.update(pr_number=pr['number'], pr_url=pr['url'])
    if receipt['stage'] == 'branch_pushed':
        persist(path, receipt, 'pr_open')
    sha = ensure_merged(pr, head, base, issue_id, delivery, files)
    if receipt.get('merge_sha') and receipt['merge_sha'] != sha:
        raise ValueError('merge SHA changed')
    receipt['merge_sha'] = sha
    if receipt['stage'] == 'pr_open':
        persist(path, receipt, 'merged')
    receipt['main_ci_run'] = wait_exact_main_ci(sha)
    if receipt['stage'] == 'merged':
        persist(path, receipt, 'main_ci_green')
    receipt['deployment'] = ensure_deployed(sha)
    if receipt['stage'] != 'deployed_qa_passed':
        persist(path, receipt, 'deployed_qa_passed')
    receipt['board'] = publish_board_receipt(issue_id, receipt)
    release_eval.save_receipt(path, receipt)
    return receipt


def run_once(context):
    return reconcile(context)


def main():
    global LABEL, FEATURE, REQUIRED_TESTS, SLOT, STATUS
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', default=LABEL)
    parser.add_argument('--feature')
    args = parser.parse_args()
    if args.label not in CONFIGS:
        raise ValueError('unsupported sandbox release identifier')
    expected_feature, tests, slot = CONFIGS[args.label]
    if args.feature is not None and args.feature != expected_feature:
        raise ValueError('feature does not match fixed release contract')
    LABEL, FEATURE, REQUIRED_TESTS, SLOT = args.label, expected_feature, tests, slot
    STATUS = PRIVATE / 'autonomy-status' / (LABEL + '.json')
    context = ensure_started(LABEL, FEATURE)
    publish_status('dispatched', context['issue_id'], owner='implementer',
                   next_action='produce TDD implementation and independent review')
    failures = {}
    while True:
        try:
            receipt = run_once(context)
            publish_status('deployed_qa_passed', context['issue_id'],
                           owner='controller', pr_url=receipt['pr_url'],
                           merge_sha=receipt['merge_sha'],
                           qa_url=receipt['deployment']['url'])
            print(json.dumps({'stage': receipt['stage'], 'pr_url': receipt['pr_url'],
                              'merge_sha': receipt['merge_sha'],
                              'qa_url': receipt['deployment']['url']}), flush=True)
            return
        except WaitingApproval:
            publish_status('waiting_approval', context['issue_id'],
                           owner='implementer/reviewer',
                           next_action='complete implementation and independent review')
            time.sleep(WAIT_SECONDS)
        except InjectedCrash:
            raise
        except Exception as error:
            category = type(error).__name__ + ':' + str(error)[:180]
            failures[category] = failures.get(category, 0) + 1
            if failures[category] >= 2:
                publish_status('escalation_required', context['issue_id'],
                               owner='techlead', category=category,
                               next_action='diagnose external state before retry')
                print(json.dumps({'stage': 'escalation_required', 'issue_id': context['issue_id'],
                                  'owner': 'techlead', 'category': category,
                                  'next_action': 'diagnose recorded external state; do not repeat unchanged action'}),
                      flush=True)
                return
            time.sleep(WAIT_SECONDS)


if __name__ == '__main__':
    main()
