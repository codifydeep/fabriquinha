"""Narrow, operator-started EVAL issue → reviewed PR → CI → local QA bridge.

This pilot selects an operator-owned repository configuration. It does not
accept repository, branch, command or Docker image input from an agent.
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

from bootstrap_multica import PRIVATE
from broker.base_gate import FILES, verify_base_compatible
from deploy_eval import REPO, trusted_source
from project_selection import current
from evalctl import PROJECT
from controller_broker_image import installed_image


BROKER = PROJECT + '-execution-broker-1'
REPOSITORY = current()['repository']
RECEIPTS = PRIVATE / 'release-receipts'


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def json_command(*args):
    return json.loads(command(*args))


def save_receipt(path, receipt):
    path.parent.mkdir(mode=0o700, exist_ok=True)
    if path.parent.is_symlink():
        raise ValueError('unsafe receipt directory')
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    temp = Path(temporary)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(receipt, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def approved_submission(issue_id, implementer_registry='implementer.json',
                        reviewer_registry='reviewer.json'):
    workspace = json.loads((PRIVATE / 'workspace.json').read_text())['id']
    author_identity = json.loads((PRIVATE / implementer_registry).read_text())
    reviewer_identity = json.loads((PRIVATE / reviewer_registry).read_text())
    if any(identity.get('workspace_id') != workspace for identity in (author_identity, reviewer_identity)):
        raise ValueError('review registry workspace mismatch')
    implementer, reviewer = author_identity['agent_id'], reviewer_identity['agent_id']
    # Use the existing authenticated runtime, as every durable handoff does.
    # A second locally cached operator PAT must not strand an approved delivery.
    runs = json_command('docker', 'exec', PROJECT + '-runtime-1', 'multica',
                        'issue', 'runs', issue_id, '--output', 'json')
    if not isinstance(runs, list) or not runs or any(
            run.get('issue_id') != issue_id or run.get('workspace_id') != workspace for run in runs):
        raise ValueError('invalid issue runs')
    implementations = [run for run in runs if run.get('agent_id') == implementer]
    if not implementations:
        raise ValueError('no completed implementation')
    latest = max(implementations, key=lambda run: (run.get('created_at') or run.get('completed_at') or '', run['id']))
    if latest.get('status') != 'completed':
        raise ValueError('no completed implementation')
    reviews = [run for run in runs if run.get('agent_id') == reviewer
               and run.get('status') == 'completed']
    query = (
        'import json,sqlite3,sys; '
        'c=sqlite3.connect("file:/broker-state/leases.sqlite?mode=ro",uri=True); '
        'r=c.execute("SELECT r.review_task_id,r.source_task_id,r.reviewer_agent_id,'
        'r.manifest_sha256,r.status,s.volume,s.status,n.agent_id '
        'FROM reviews r JOIN snapshots s ON s.task_id=r.source_task_id '
        'JOIN native_bindings n ON n.task_id=r.source_task_id '
        'WHERE r.review_task_id=?",(sys.argv[1],)).fetchone(); print(json.dumps(r))'
    )
    approved = []
    for run in reviews:
        row = json_command('docker', 'exec', BROKER, 'python3', '-c', query, run['id'])
        if row and row[4] == 'approved' and row[1] == latest['id']:
            approved.append(row)
    if len(approved) == 2:
        from scoped_approval_selection import select, query_with
        approved = [select(issue_id, approved,
                           lambda issue, source: query_with(command, BROKER, issue, source))]
    if len(approved) != 1:
        raise ValueError('expected one approved exact revision')
    review_task, source_task, reviewer_id, manifest, status, volume, frozen_status, author_id = approved[0]
    if (source_task != latest['id'] or reviewer_id != reviewer or author_id != implementer
            or reviewer_id == author_id or frozen_status != 'complete'
            or not re.fullmatch(r'[0-9a-f]{64}', manifest)):
        raise ValueError('review is stale or not independent')
    return {'source_task': source_task, 'review_task': review_task,
            'author': author_id, 'reviewer': reviewer_id,
            'manifest_sha256': manifest, 'volume': volume}


def export_snapshot(delivery, target):
    volume = delivery['volume']
    if volume != PROJECT + '-snapshot-' + delivery['source_task']:
        raise ValueError('snapshot volume name mismatch')
    details = json_command('docker', 'volume', 'inspect', volume)
    if len(details) != 1 or details[0].get('Labels', {}).get('delivery-kit.owner') != PROJECT + '-broker-v1' or details[0].get('Labels', {}).get('delivery-kit.source-task') != delivery['source_task']:
        raise ValueError('snapshot volume identity mismatch')
    from snapshot_export_lifecycle import export
    export(volume,target,PRIVATE,instance=PROJECT)


def wait_pr_ci(number, head, base, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pr = json_command('gh', 'pr', 'view', str(number), '-R', REPOSITORY,
                          '--json', 'state,headRefOid,baseRefOid,mergeStateStatus,statusCheckRollup,url')
        if pr['state'] != 'OPEN' or pr['headRefOid'] != head or pr['baseRefOid'] != base:
            raise ValueError('PR identity or base moved')
        checks = [check for check in pr.get('statusCheckRollup', []) if check.get('name') == 'ci']
        if any(check.get('conclusion') not in ('SUCCESS', '') for check in checks):
            raise ValueError('required CI failed')
        if len(checks) == 1 and checks[0].get('conclusion') == 'SUCCESS' and pr['mergeStateStatus'] == 'CLEAN':
            return pr
        time.sleep(5)
    raise TimeoutError('required CI did not pass in time')


def wait_main_ci(sha, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            current, url = trusted_source()
            if current != sha:
                raise ValueError('main moved after merge')
            return url
        except ValueError as error:
            if 'successful automatic CI missing' not in str(error):
                raise
        time.sleep(5)
    raise TimeoutError('automatic main CI did not pass in time')


def main(issue_id, identifier, expected_base):
    if not re.fullmatch(r'[0-9a-f-]{36}', issue_id) or not re.fullmatch(r'EVAL-[0-9]+', identifier):
        raise ValueError('invalid evaluation identity')
    if identifier != 'EVAL-14' or issue_id != '01a0e947-5866-7ed6-a003-8c8af661289b':
        raise ValueError('this bridge invocation is fixed to approved EVAL-14')
    receipt_path = RECEIPTS / (identifier + '.json')
    if receipt_path.exists():
        raise ValueError('release receipt already exists; reconcile before retry')
    base, _ = trusted_source()
    if base != expected_base:
        raise ValueError('expected base moved')
    delivery = approved_submission(issue_id)
    branch = 'codex/' + identifier.lower() + '-reviewed'
    with tempfile.TemporaryDirectory(prefix='delivery-kit-eval-snapshot-') as scratch:
        snapshot = Path(scratch)
        export_snapshot(delivery, snapshot)
        preflight = verify_base_compatible(REPO, base, snapshot)
        if preflight['manifest_sha256'] != delivery['manifest_sha256']:
            raise ValueError('broker approval does not cover snapshot manifest')
        if not {'test_cube_positive', 'test_cube_negative'} <= set(preflight['new_tests']):
            raise ValueError('cube acceptance tests missing from reviewed snapshot')
        receipt = {'issue_id': issue_id, 'identifier': identifier, 'base_sha': base,
                   'branch': branch, **delivery, 'new_tests': preflight['new_tests'],
                   'stage': 'preflight_passed'}
        save_receipt(receipt_path, receipt)
        print(json.dumps({'stage': receipt['stage'], 'new_tests': receipt['new_tests']}), flush=True)
        if command('git', '-C', str(REPO), 'branch', '--show-current') != 'main':
            raise ValueError('checkout not on main')
        subprocess.run(['git', '-C', str(REPO), 'switch', '-c', branch], check=True)
        for name in FILES:
            (REPO / name).write_bytes((snapshot / name).read_bytes())
        changed = set(command('git', '-C', str(REPO), 'diff', '--name-only').splitlines())
        if changed != {'calc.py', 'test_calc.py'}:
            raise ValueError('unexpected changed files')
        subprocess.run(['git', '-C', str(REPO), 'add', *FILES], check=True)
        subprocess.run(['git', '-C', str(REPO), 'commit', '-m', identifier + ': reviewed cube delivery'], check=True)
        head = command('git', '-C', str(REPO), 'rev-parse', 'HEAD')
        for name in FILES:
            if subprocess.check_output(['git', '-C', str(REPO), 'show', head + ':' + name]) != (snapshot / name).read_bytes():
                raise ValueError('commit differs from reviewed snapshot')
        receipt.update(stage='committed', head_sha=head)
        save_receipt(receipt_path, receipt)
        subprocess.run(['git', '-C', str(REPO), 'push', '-u', 'origin', branch], check=True)
        url = command('gh', 'pr', 'create', '-R', REPOSITORY, '--base', 'main', '--head', branch,
                      '--title', identifier + ': reviewed calculator feature',
                      '--body', 'Autonomous evaluation delivery. Source task: ' + delivery['source_task']
                      + '\nIndependent review: ' + delivery['review_task']
                      + '\nFrozen manifest SHA-256: ' + delivery['manifest_sha256']
                      + '\nController preflight preserved all base tests. CI and merge remain required.')
        pr_number = int(url.rsplit('/', 1)[-1])
        receipt.update(stage='pr_open', pr_number=pr_number, pr_url=url)
        save_receipt(receipt_path, receipt)
        print(json.dumps({'stage': receipt['stage'], 'pr_url': url, 'head_sha': head}), flush=True)
        wait_pr_ci(pr_number, head, base)
        # Revalidate the approval, artifact bytes, PR head and base immediately before merge.
        if approved_submission(issue_id) != delivery:
            raise ValueError('approval changed before merge')
        verify_base_compatible(REPO, base, snapshot, current_ref='main')
        pr = wait_pr_ci(pr_number, head, base, timeout=10)
        if pr['headRefOid'] != command('git', '-C', str(REPO), 'rev-parse', 'HEAD'):
            raise ValueError('local PR head moved')
        receipt['stage'] = 'ci_green'
        save_receipt(receipt_path, receipt)
        subprocess.run(['gh', 'pr', 'merge', str(pr_number), '-R', REPOSITORY, '--squash'], check=True)
        merged = json_command('gh', 'pr', 'view', str(pr_number), '-R', REPOSITORY,
                              '--json', 'state,mergeCommit,mergedAt')
        if merged['state'] != 'MERGED':
            raise ValueError('merge not confirmed')
        merge_sha = merged['mergeCommit']['oid']
        receipt.update(stage='merged', merge_sha=merge_sha)
        save_receipt(receipt_path, receipt)
        print(json.dumps({'stage': receipt['stage'], 'merge_sha': merge_sha}), flush=True)
        subprocess.run(['git', '-C', str(REPO), 'switch', 'main'], check=True)
        subprocess.run(['git', '-C', str(REPO), 'pull', '--ff-only'], check=True)
        if command('git', '-C', str(REPO), 'rev-parse', 'HEAD') != merge_sha:
            raise ValueError('post-merge checkout mismatch')
        for name in FILES:
            if subprocess.check_output(['git', '-C', str(REPO), 'show', merge_sha + ':' + name]) != (snapshot / name).read_bytes():
                raise ValueError('merged commit differs from reviewed snapshot')
        receipt['main_ci_run'] = wait_main_ci(merge_sha)
        deployed = json_command(sys.executable, str(Path(__file__).resolve().parent / 'deploy_eval.py'), '--slot', '4')
        if (deployed['source_sha'] != merge_sha or deployed['qa_status'] != 'passed'
                or deployed['feature_qa'] != 'cube' or deployed['post_deploy_qa_cases'] < 7):
            raise ValueError('post-deploy receipt does not match merge')
        receipt.update(stage='deployed_qa_passed', deployment=deployed)
        save_receipt(receipt_path, receipt)
        print(json.dumps({'stage': receipt['stage'], 'pr_url': url,
                          'merge_sha': merge_sha, 'qa_url': deployed['url']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--issue-id', required=True)
    parser.add_argument('--identifier', required=True)
    parser.add_argument('--expected-base', required=True)
    args = parser.parse_args()
    main(args.issue_id, args.identifier, args.expected_base)
