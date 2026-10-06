"""Protected exact-SHA predecessor merge; restart-safe observation, no QA claims."""
import argparse
import json
import tempfile
from pathlib import Path

import publish_u3_predecessors as predecessor
from release_eval import save_receipt

common = predecessor.common
RECEIPT = common.ROOT / '.local-port2/release-receipts/U3-PREDECESSORS-INTEGRATION.json'


class CIWaiting(ValueError):
    pass


def api(path, *args):
    return json.loads(common.run('gh', 'api', 'repos/' + common.REPOSITORY + '/' + path, *args))


def protection_ok(protection):
    checks = protection.get('required_status_checks') or {}
    names = set(checks.get('contexts', [])) | {v['context'] for v in checks.get('checks', [])}
    if not checks.get('strict') or 'ci' not in names or protection.get('enforce_admins', {}).get('enabled') is not True:
        raise ValueError('strict CI and enforced branch protection required')


def exact_ci(checks, sha):
    matches = [c for c in checks.get('check_runs', []) if c.get('name') == 'ci']
    if not matches or (len(matches) == 1 and matches[0].get('head_sha') == sha
                       and matches[0].get('status') in ('queued', 'in_progress')):
        raise CIWaiting('exact-SHA CI not complete')
    if (len(matches) != 1 or matches[0].get('head_sha') != sha
            or matches[0].get('status') != 'completed' or matches[0].get('conclusion') != 'success'):
        raise ValueError('one successful exact-SHA CI required')
    return dict(head_sha=sha, check_run_id=matches[0]['id'], url=matches[0]['html_url'])


def verify_pr(pr, published):
    if (pr.get('number') != published['pr_number']
            or pr.get('head', {}).get('sha') != published['head_sha']
            or pr.get('head', {}).get('ref') != predecessor.BRANCH
            or pr.get('base', {}).get('sha') not in ({published['base_sha'], pr.get('merge_commit_sha')}
                                                    if pr.get('merged') else {published['base_sha']})
            or pr.get('base', {}).get('ref') != 'main'
            or pr.get('head', {}).get('repo', {}).get('full_name') != common.REPOSITORY
            or pr.get('base', {}).get('repo', {}).get('full_name') != common.REPOSITORY):
        raise ValueError('exact same-repository predecessor PR required')


def verify_merged(repo, base, head, merged):
    if common.git(repo, 'rev-parse', merged + '^').decode().strip() != base:
        raise ValueError('squash merge parent drift')
    if common.tracked(repo, head) != common.tracked(repo, merged):
        raise ValueError('merged tree differs from reviewed PR')
    return common.git(repo, 'rev-parse', merged + '^{tree}').decode().strip()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--merge', action='store_true'); args = parser.parse_args()
    if predecessor.RECEIPT.is_symlink(): raise ValueError('regular publication receipt required')
    published = json.loads(predecessor.RECEIPT.read_text())
    bundle = predecessor.load_bundle()
    if (published.get('stage') != 'pr_open' or published.get('repository') != common.REPOSITORY
            or published['manifest_sha256'] != bundle['manifest_sha256']
            or published['proof_sha256'] != common.digest(bundle['proofs'])
            or published['base_sha'] != bundle['base_sha']):
        raise ValueError('current independently reviewed publication required')
    protection = api('branches/main/protection'); protection_ok(protection)
    number = published['pr_number']; head = published['head_sha']; base = published['base_sha']
    pr = api('pulls/' + str(number)); verify_pr(pr, published)
    head_ci = exact_ci(api('commits/' + head + '/check-runs'), head)
    with tempfile.TemporaryDirectory(prefix='u3-merge-snapshot-') as tmp:
        snapshot = Path(tmp); common.export_snapshot(bundle, snapshot)
        content = predecessor.preflight(common.REPO, bundle, snapshot)
        predecessor.verify_commit(common.REPO, head, base, content)
    if not pr.get('merged'):
        if pr.get('state') != 'open' or common.remote_base(common.REPO) != base:
            raise ValueError('open PR on exact original main required')
        if not args.merge:
            print(json.dumps(dict(stage='merge_preconditions_passed', head_sha=head))); return
        receipt = dict(schema='u3-predecessor-integration-v1', stage='merge_intent',
            repository=common.REPOSITORY, pr_number=number, original_git_base=base,
            head_sha=head, root=bundle['root'], predecessor_manifest_sha256=bundle['manifest_sha256'],
            proof_sha256=published['proof_sha256'], head_ci=head_ci,
            protection_sha256=common.digest(protection), delivery_approval=False, deploy_authorized=False)
        save_receipt(RECEIPT, receipt)  # persist before the remote side effect
        if predecessor.load_bundle() != bundle or api('branches/main/protection') != protection:
            raise ValueError('review or protection drift before merge')
        verify_pr(api('pulls/' + str(number)), published)
        exact_ci(api('commits/' + head + '/check-runs'), head)
        result = api('pulls/' + str(number) + '/merge', '--method', 'PUT', '-f', 'sha=' + head, '-f', 'merge_method=squash')
        if result.get('merged') is not True: raise ValueError('protected merge was not accepted')
        pr = api('pulls/' + str(number)); verify_pr(pr, published)
    else:
        if not RECEIPT.is_file() or RECEIPT.is_symlink(): raise ValueError('durable merge intent required')
        receipt = json.loads(RECEIPT.read_text())
        if (receipt['head_sha'] != head or receipt['original_git_base'] != base
                or receipt['proof_sha256'] != published['proof_sha256']):
            raise ValueError('merge intent lineage drift')
    merged = pr.get('merge_commit_sha')
    if not pr.get('merged') or not merged or common.remote_base(common.REPO) != merged:
        raise ValueError('exact observed merged main required')
    if api('branches/main/protection') != protection: raise ValueError('branch protection changed')
    common.git(common.REPO, 'fetch', 'origin', merged)
    tree = verify_merged(common.REPO, base, head, merged)
    receipt.update(stage='waiting_main_ci', merged_sha=merged, tree_sha=tree, protection_preserved=True)
    save_receipt(RECEIPT, receipt)
    try:
        main_ci = exact_ci(api('commits/' + merged + '/check-runs'), merged)
    except CIWaiting:
        print(json.dumps(receipt)); return
    except ValueError:
        receipt.update(stage='blocked_main_ci', owner='cto', next_action='Diagnose exact merged-SHA CI; do not publish coverage')
        save_receipt(RECEIPT, receipt); print(json.dumps(receipt)); return
    receipt.update(stage='predecessors_integrated', main_ci=main_ci)
    save_receipt(RECEIPT, receipt)
    print(json.dumps(receipt))


if __name__ == '__main__': main()
