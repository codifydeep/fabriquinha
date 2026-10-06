"""Fixed disposable U3 coverage PR publisher. No merge or deployment operation.

Uses controller-observed receipts and an immutable snapshot, not worker input.
Git plumbing preserves the caller's worktree and unrelated untracked files.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

from broker.maintenance_snapshot_validate import manifest
from controller_broker_image import installed_image
from release_eval import save_receipt

ROOT = Path(__file__).resolve().parent
REPOSITORY = 'codifydeep/descartavel2'
REPO = ROOT / 'sandbox-github2'
PROJECT = 'delivery-kit-port2'
BRANCH = 'codex/u3-existing-behavior-coverage'
TESTS = {'tests/test_incremental_u3.py', 'tests/test_u3_c01_controls.py', 'tests/test_u3_c02_controls.py'}
RECEIPT = ROOT / '.local-port2/release-receipts/U3-COVERAGE.json'


class PublicationBlocked(ValueError):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
        super().__init__(diagnostic['category'])


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def run(*args, data=None, env=None):
    return subprocess.check_output(args, input=data, env=env)


def git(repo, *args, data=None, env=None):
    return run('git', '-C', str(repo), *args, data=data, env=env)


def load_bundle():
    script = '''import broker as b,json,u3_coverage_integration as i,native,handoff_runtime
with b.LOCK:
 c,s=i.saved(b)
 if s['stage']!='integration_review_approved':raise ValueError('current integration review required')
 settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
 current,classification=i.verify(b,settings,fx)
 if current!=c['intake'] or classification['task_id']!=c['classification_task']:raise ValueError('lineage drift')
 if i.contract(current,current['proof'],c['reviewer'])!=c['contract']:raise ValueError('contract drift')
 t=native.task_record(settings,s['receipt']['task_id'],c['reviewer'])
 receipt=i.review_receipt(c,s,t,fx.decision(t),fx.read_evidence(t))
 if receipt!=s['receipt']:raise ValueError('review receipt drift')
 seed=c['intake']['seed'];i.controls.owned(b,seed['snapshot'],seed['task_id'])
 print(json.dumps(dict(schema='u3-coverage-publication-input-v1',contract=c['contract'],receipt=receipt,
  issue_id=c['issue_id'],identifier=c['identifier'],source_task=seed['task_id'],volume=seed['snapshot']['volume'])))
'''
    return json.loads(run('docker', 'exec', '-e', 'PYTHONPATH=/', PROJECT + '-execution-broker-1', 'python', '-c', script))


def validate_bundle(bundle):
    c, r = bundle['contract'], bundle['receipt']
    if (bundle.get('schema') != 'u3-coverage-publication-input-v1'
            or c.get('schema') != 'u3-coverage-integration-v1'
            or c.get('classification') != 'existing_behavior_coverage_only'
            or set(c.get('new_test_sha256', {})) != TESTS
            or c.get('previous_files_unchanged') is not True
            or c.get('product_admission_authorized') is not False
            or c.get('author') == c.get('reviewer')
            or r.get('schema') != 'u3-coverage-integration-review-v1'
            or r.get('contract_sha256') != digest(c)
            or r.get('integration_review_approved') is not True
            or r.get('reviewer') != c['reviewer']
            or r.get('manifest_sha256') != c.get('manifest_sha256')
            or r.get('decision', {}).get('action') != 'approve_test_revision'
            or r.get('decision', {}).get('manifest_sha256') != c.get('manifest_sha256')
            or r.get('decision', {}).get('optional_files') != []):
        raise ValueError('exact independent coverage publication receipt required')
    for value in (c['manifest_sha256'], c['base_manifest_sha256'], *c['new_test_sha256'].values()):
        if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
            raise ValueError('immutable publication digest required')
    if not re.fullmatch('[a-f0-9]{40}', c.get('base_sha', '')):
        raise ValueError('exact Git base required')
    for item in (c, r):
        for field in ('historical_tdd_red', 'delivery_approval', 'merge_authorized', 'deploy_authorized'):
            if item.get(field) is not False:
                raise ValueError('coverage publication cannot authorize delivery or historical Red')
    return c


def export_snapshot(bundle, target):
    volume = bundle['volume']
    if volume != PROJECT + '-snapshot-' + bundle['source_task']:
        raise ValueError('exact approved snapshot volume required')
    details = json.loads(run('docker', 'volume', 'inspect', volume))
    if (len(details) != 1 or details[0].get('Labels', {}).get('delivery-kit.owner') != PROJECT + '-broker-v1'
            or details[0].get('Labels', {}).get('delivery-kit.source-task') != bundle['source_task']):
        raise ValueError('snapshot ownership drift')
    name = PROJECT + '-coverage-export-' + uuid.uuid4().hex[:12]
    run('docker', 'create', '--name', name, '--label', 'com.docker.compose.project=' + PROJECT,
        '--label', 'com.docker.compose.service=coverage-export', '--network', 'none', '--read-only',
        '--user', '10000:10000', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--mount', 'type=volume,source=' + volume + ',target=/delivery,readonly',
        '--entrypoint', '/bin/true', installed_image(PROJECT))
    try:
        run('docker', 'cp', name + ':/delivery/.', str(target))
    finally:
        run('docker', 'rm', name)  # never force, never touch other containers


def tracked(repo, base):
    entries = git(repo, 'ls-tree', '-r', '-z', base).split(b'\0')
    files = {}
    for entry in entries:
        if not entry:
            continue
        metadata, path = entry.split(b'\t', 1)
        mode, kind, blob = metadata.decode().split()
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise ValueError('regular Git files only')
        files[path.decode()] = (mode, blob)
    return files


def preflight(repo, bundle, snapshot, *, target_base=None):
    c = validate_bundle(bundle)
    raw, metadata = manifest(snapshot)
    if hashlib.sha256(raw).hexdigest() != c['manifest_sha256']:
        raise ValueError('snapshot differs from approved review')
    base = target_base or c['base_sha']
    old = tracked(repo, base)
    # Runtime snapshots omit repository-only metadata, e.g. CI workflows.
    # Those files are never imported from a snapshot: preserve the original
    # Git tree and verify every original blob/mode again after commit creation.
    content = {name: (Path(snapshot) / name).read_bytes() for name in metadata}
    extra = sorted(set(metadata) - set(old) - TESTS)
    changed = sorted(name for name in old.keys() & content.keys()
                     if git(repo, 'cat-file', 'blob', old[name][1]) != content[name])
    if extra or changed or set(old) & TESTS or not TESTS <= set(metadata):
        raise PublicationBlocked(dict(category='snapshot_not_coverage_only_against_git_base',
            phase='publication_preflight', base_sha=base, manifest_sha256=c['manifest_sha256'],
            extra_files=extra, changed_previous_files=changed,
            original_git_files_omitted_from_runtime_snapshot=sorted(set(old)-set(metadata)),
            owner='cto', next_action='Resolve unpublished predecessor checkpoints before coverage-only PR; '
                'do not expand the approved delta or relabel feature work as coverage',
            merge_authorized=False, deploy_authorized=False))
    for name, (_, blob) in old.items():
        if name in content and git(repo, 'cat-file', 'blob', blob) != content[name]:
            raise ValueError('original product or previous test changed: ' + name)
    for name in TESTS:
        if hashlib.sha256(content[name]).hexdigest() != c['new_test_sha256'][name]:
            raise ValueError('approved additive test changed: ' + name)
    return content


def verify_commit(repo, head, base, content):
    if git(repo, 'rev-parse', head + '^').decode().strip() != base:
        raise ValueError('coverage commit parent drift')
    changed = git(repo, 'diff', '--name-status', base, head).decode().splitlines()
    if set(changed) != {'A\t' + name for name in TESTS}:
        raise ValueError('only three additive tests may change')
    old_modes = tracked(repo, base)
    after = tracked(repo, head)
    if set(after) != set(old_modes) | TESTS:
        raise ValueError('coverage commit inventory drift')
    for name, (mode, blob) in after.items():
        if mode != (old_modes[name][0] if name in old_modes else '100644'):
            raise ValueError('file mode changed: ' + name)
        if name in old_modes and blob != old_modes[name][1]:
            raise ValueError('original Git blob changed: ' + name)
        if name in content and git(repo, 'cat-file', 'blob', blob) != content[name]:
            raise ValueError('commit differs from reviewed snapshot: ' + name)


def ensure_commit(repo, base, content):
    ref = 'refs/heads/' + BRANCH
    prior = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--verify', ref], capture_output=True, text=True)
    if prior.returncode == 0:
        head = prior.stdout.strip()
    else:
        remote = git(repo, 'ls-remote', 'origin', ref).decode().strip()
        if remote:
            head = remote.split()[0]
            git(repo, 'fetch', 'origin', head)
        else:
            with tempfile.TemporaryDirectory(prefix='u3-coverage-index-') as tmp:
                env = {**os.environ, 'GIT_INDEX_FILE': str(Path(tmp) / 'index')}
                git(repo, 'read-tree', base, env=env)
                for name in sorted(TESTS):
                    blob = git(repo, 'hash-object', '-w', '--stdin', data=content[name]).decode().strip()
                    git(repo, 'update-index', '--add', '--cacheinfo', '100644,' + blob + ',' + name, env=env)
                tree = git(repo, 'write-tree', env=env).decode().strip()
            head = git(repo, 'commit-tree', tree, '-p', base, '-m', 'U3: add reviewed coverage for existing behavior').decode().strip()
        verify_commit(repo, head, base, content)
        git(repo, 'update-ref', ref, head, '0' * 40)
    verify_commit(repo, head, base, content)
    return head


def remote_base(repo):
    origin = git(repo, 'remote', 'get-url', 'origin').decode().strip()
    if origin not in ('https://github.com/' + REPOSITORY + '.git', 'git@github.com:' + REPOSITORY + '.git'):
        raise ValueError('fixed disposable repository required')
    rows = git(repo, 'ls-remote', 'origin', 'refs/heads/main').decode().splitlines()
    if len(rows) != 1:
        raise ValueError('unique remote main required')
    return rows[0].split()[0]


def publication_base(bundle):
    """New Git binding; original review contract remains immutable."""
    c = validate_bundle(bundle)
    current = remote_base(REPO)
    if current == c['base_sha']:
        return current, None
    import integrate_u3_predecessors as integration
    import publish_u3_predecessors as predecessor
    path = integration.RECEIPT
    if path.is_symlink() or not path.is_file():
        raise ValueError('verified predecessor integration receipt required')
    receipt = json.loads(path.read_text())
    prior = predecessor.load_bundle()
    if (receipt.get('stage') != 'predecessors_integrated' or receipt.get('repository') != REPOSITORY
            or receipt.get('original_git_base') != c['base_sha'] or receipt.get('root') != c['root']
            or receipt.get('merged_sha') != current or prior['base_sha'] != c['base_sha']
            or prior['root'] != c['root'] or receipt.get('proof_sha256') != digest(prior['proofs'])
            or receipt.get('predecessor_manifest_sha256') != prior['manifest_sha256']):
        raise ValueError('current integrated predecessor lineage required')
    pr = integration.api('pulls/' + str(receipt['pr_number']))
    published = json.loads(predecessor.RECEIPT.read_text())
    integration.verify_pr(pr, published)
    if not pr.get('merged') or pr.get('merge_commit_sha') != current:
        raise ValueError('exact observed predecessor merge required')
    protection = integration.api('branches/main/protection'); integration.protection_ok(protection)
    if digest(protection) != receipt['protection_sha256']:
        raise ValueError('predecessor protection drift')
    main_ci = integration.exact_ci(integration.api('commits/' + current + '/check-runs'), current)
    tree = integration.verify_merged(REPO, c['base_sha'], receipt['head_sha'], current)
    if tree != receipt.get('tree_sha'):
        raise ValueError('integrated predecessor tree drift')
    return current, dict(schema='u3-coverage-git-binding-v1', original_contract_sha256=digest(c),
        original_git_base=c['base_sha'], target_base=current, tree_sha=tree,
        predecessor_manifest_sha256=prior['manifest_sha256'], predecessor_pr=receipt['pr_number'],
        main_ci=main_ci, historical_tdd_red=False, merge_authorized=False, deploy_authorized=False)


def publish(bundle, head, *, target_base=None):
    c = bundle['contract']
    base = target_base or c['base_sha']
    if publication_base(bundle)[0] != base or load_bundle() != bundle:
        raise ValueError('source or review moved before publication')
    git(REPO, 'push', 'origin', head + ':refs/heads/' + BRANCH)
    prs = json.loads(run('gh', 'pr', 'list', '-R', REPOSITORY, '--state', 'all', '--head', BRANCH,
        '--json', 'number,state,headRefOid,baseRefOid,url'))
    if not prs:
        body = ('Coverage-only integration of existing behavior; no product implementation changes.\n'
            'Issue: ' + bundle['identifier'] + '\nAuthor execution: ' + bundle['source_task']
            + '\nIndependent preintegration review: ' + bundle['receipt']['task_id']
            + '\nManifest SHA-256: ' + c['manifest_sha256'] + '\nOriginal provenance SHA: ' + c['base_sha']
            + '\nIntegrated PR base SHA: ' + base
            + '\nOnly three new test files; all previous files preserved byte-for-byte. '
            'Controller verified 255 baseline tests and 261 candidate tests. '
            'No historical feature Red claimed. CI, independent delivery review and deploy/QA remain required. '
            'No merge or homologation performed by this publisher.')
        run('gh', 'pr', 'create', '-R', REPOSITORY, '--base', 'main', '--head', BRANCH,
            '--title', 'U3: reviewed regression coverage for existing behavior', '--body', body)
        prs = json.loads(run('gh', 'pr', 'list', '-R', REPOSITORY, '--state', 'all', '--head', BRANCH,
            '--json', 'number,state,headRefOid,baseRefOid,url'))
    if (len(prs) != 1 or prs[0]['state'] != 'OPEN' or prs[0]['headRefOid'] != head
            or prs[0]['baseRefOid'] != base):
        raise ValueError('exact open coverage PR required')
    return prs[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    bundle = load_bundle()
    c = validate_bundle(bundle)
    base, binding = publication_base(bundle)
    with tempfile.TemporaryDirectory(prefix='u3-coverage-snapshot-') as tmp:
        snapshot = Path(tmp)
        export_snapshot(bundle, snapshot)
        try:
            content = preflight(REPO, bundle, snapshot, target_base=base)
        except PublicationBlocked as error:
            blocked = dict(schema='u3-coverage-pr-v1', repository=REPOSITORY, stage='blocked',
                issue_id=bundle['issue_id'], review_task=bundle['receipt']['task_id'],
                diagnostic=error.diagnostic, historical_tdd_red=False, delivery_approval=False,
                merge_authorized=False, deploy_authorized=False)
            save_receipt(RECEIPT, blocked)
            print(json.dumps(blocked))
            return
        if not args.publish:
            print(json.dumps(dict(stage='preflight_passed', manifest_sha256=c['manifest_sha256'], new_files=sorted(TESTS))))
            return
        head = ensure_commit(REPO, base, content)
        receipt = dict(schema='u3-coverage-pr-v1', repository=REPOSITORY, branch=BRANCH,
            head_sha=head, base_sha=base, original_git_base=c['base_sha'], git_binding=binding,
            manifest_sha256=c['manifest_sha256'],
            review_task=bundle['receipt']['task_id'], review_receipt_sha256=digest(bundle['receipt']),
            source_task=bundle['source_task'], stage='committed', historical_tdd_red=False,
            merge_authorized=False, deploy_authorized=False, delivery_approval=False)
        save_receipt(RECEIPT, receipt)
        pr = publish(bundle, head, target_base=base)
        receipt.update(stage='pr_open', pr_number=pr['number'], pr_url=pr['url'])
        save_receipt(RECEIPT, receipt)
        print(json.dumps(receipt))


if __name__ == '__main__':
    main()
