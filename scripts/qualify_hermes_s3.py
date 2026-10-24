"""Native TDD -> private Git/PR simulator -> real integrated suite. No real GitHub CI."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
from fixtures.github_transport import FakeGitHub
from fabriquinha.effects import Pending
from fabriquinha.kanban_lane import native
from fabriquinha.publication import GitHub, Publication, Repository
from fabriquinha.deployment import Deployment
from fabriquinha.executor import docker
from qualify_hermes_s2 import qualify, observe


def integrate(project, store, board, quality, implementation, review, frozen):
    folder = store.root.parent/'github-fixture'
    folder.mkdir(mode=0o700)
    remote, seed = folder/'remote.git', folder/'seed'
    remote.mkdir()
    baseline = store.receipt(frozen, kind='tests_frozen')['payload']['baseline']
    store.checkout(baseline, seed)

    def git(path, *args):
        return subprocess.run(['git','-c','core.hooksPath=/dev/null','-C',str(path),*args],
                              capture_output=True, text=True, check=True, timeout=30).stdout

    git(remote,'init','--bare','--initial-branch=main')
    git(seed,'init','--initial-branch=main')
    git(seed,'add','.')
    git(seed,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
        '-c','commit.gpgsign=false','commit','-m','Infrastructure fixture baseline')
    git(seed,'remote','add','origin',str(remote))
    git(seed,'push','origin','HEAD:refs/heads/'+project.branch)
    kb, kbc, _ = native()
    with kbc.connect_closing() as conn:
        task = kb.create_task(conn, title='S3 integration simulator; not a release',
            body=json.dumps(dict(version=1,kind='integration',release='s2-fixture',
                inputs={'delivery':'parent:'+implementation+':delivery'})),
            assignee='s2-author', parents=[implementation], completion_contract=project.repository.removeprefix('https://github.com/'))
        claimed = kb.claim_task(conn,task)
        assert claimed is not None
    run = board.current(task,claimed.current_run_id)
    repo = Repository(project,store,remote=remote)
    github = FakeGitHub(repo,native=True,assignee=run.actor)

    def publisher():
        return Publication(project,store,board,Repository(project,store,remote=remote),github)

    github.lose_create = True
    try:
        publisher().publish(run,review)
    except Pending:
        pass
    else:
        raise AssertionError('lost PR response was not observed as pending')
    github.lose_merge = True
    try:
        publisher().publish(run,review)
    except Pending:
        pass
    else:
        raise AssertionError('lost merge response was not observed as pending')
    published = publisher().publish(run,review)
    publication = store.receipt(published,kind='publication')['payload']
    # Native policy and exact-merge SHA checks also receive misleading inputs.
    refused = []
    for fault in ('old_head','missing_required_policy','partial_check_pages','wrong_app'):
        def api(endpoint,**kwargs):
            value = github.api(endpoint,**kwargs)
            if endpoint == 'graphql' and fault in {'missing_required_policy','wrong_app'}:
                required = value['data']['repository']['pullRequest']['baseRef']['branchProtectionRule']['requiredStatusChecks']
                if fault == 'missing_required_policy':
                    required.clear()
                else:
                    required[0]['app'] = {'databaseId':99}
            if '/commits/'+publication['merge_sha']+'/check-runs?' in endpoint:
                if fault == 'old_head':
                    value[0]['check_runs'][0]['head_sha'] = publication['head_sha']
                if fault == 'partial_check_pages':
                    value[0]['total_count'] = 2
            return value
        try:
            with patch('hermes_cli.kanban_pr_acceptance._api',api):
                gate = GitHub(project,run.actor).accept(publication['pr'],publication['merge_sha'])
                assert not gate['ok'], fault
        except ValueError:
            assert fault == 'partial_check_pages'
        refused.append(fault)
    integrated = observe(lambda: publisher().validate_integrated(run,published,quality))
    value = store.receipt(integrated,kind='integrated')['payload']
    assert github.calls == dict(create=1,merge=1)
    assert publication['head_sha'] != publication['merge_sha'] == value['commit']
    assert publication['snapshot'] == value['snapshot']
    assert value['ci']['source_pr_head_sha'] == publication['head_sha']
    deployment=None
    if project.browser_image:
        delivery=Deployment(project,store,board,quality.runner)
        baseline=observe(lambda:delivery.artifact(run,integrated,repo,baseline=True))
        candidate=observe(lambda:delivery.artifact(run,integrated,repo))
        rollout=observe(lambda:delivery.rollout(run,candidate,baseline))
        board.review(run,'Independent deployed browser QA after real rollback and restoration',
                     {'rollout':rollout,'integrated':integrated,'published_pr':publication['pr']})
        with kbc.connect_closing() as conn:
            claimed=kb.claim_review_task(conn,task)
            assert claimed is not None
        qa_run=board.current(task,claimed.current_run_id)
        release=observe(lambda:delivery.qa(qa_run,rollout))
        proof=store.receipt(release,kind='release_evidence')['payload']
        deployment=dict(candidate=candidate,baseline=baseline,rollout=rollout,release_evidence=release,
            image=proof['image'],commit=proof['commit'],url=proof['url'],checks=proof['checks'],
            real_compose=True,real_browser=True,real_rollback=True,delivery_approval=False)
        with patch('hermes_cli.kanban_pr_acceptance._api',github.api):
            board.finish_review(qa_run,'Synthetic S3 infrastructure proof; not product homologation',
                {'published_pr':publication['pr'],'integrated':integrated,'release_evidence':release})
    with patch('hermes_cli.kanban_pr_acceptance._api',github.api):
        with kbc.connect_closing() as conn:
            if deployment is None:
                assert kb.complete_task(conn,task,summary='PR/CI simulator and real integrated suite; not homologated',
                    expected_run_id=run.number, metadata={'published_pr':publication['pr'],'integrated':integrated})
            event = conn.execute('SELECT payload FROM task_events WHERE task_id=? AND kind=? ORDER BY id DESC LIMIT 1',
                                 (task,'pr_acceptance')).fetchone()
            assert json.loads(event[0])['ok']
    assert not docker('ps','-aq','--filter','label=com.docker.compose.project='+project.namespace+'-tests').strip()
    return dict(qualification=True, real_git=True, github_effects_simulated=True,
        native_required_checks_processed=github.api_calls, complete_integrated_suite=True,
        lost_create_ack_did_not_duplicate=True,lost_merge_ack_did_not_duplicate=True,
        merge_sha_differs_from_head=True, misleading_ci_refused=refused, publication=published,integrated=integrated,
        deployment=deployment,real_github_ci=False,delivery_approval=False,model_calls=0)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--image',required=True)
    parser.add_argument('--browser-image')
    parser.add_argument('--namespace',default='delivery-kit-hermes-s2')
    args=parser.parse_args()
    qualify(args.root.resolve(),args.upstream.resolve(),args.image,after_review=integrate,
            browser_image=args.browser_image,namespace=args.namespace)
