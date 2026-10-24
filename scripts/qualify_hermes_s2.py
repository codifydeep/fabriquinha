"""S2 real Docker/HTTP TDD qualification, with deterministic activity fixtures.

Native claims/decisions are exercised by this trusted test driver. No LLM,
GitHub writes, product approval, gateway migration or delivery claim.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from qualify_hermes_s1 import prepare
from fabriquinha.artifacts import Store
from fabriquinha.board import Board
from fabriquinha.config import Project
from fabriquinha.effects import Pending, write_json
from fabriquinha.executor import Runner, docker, phase_mounts
from fabriquinha.kanban_lane import native
from fabriquinha.quality import Quality


def observe(call):
    """Reobserve the same operation; never respawn on a missing acknowledgement."""
    while True:
        try:
            return call()
        except Pending:
            time.sleep(0.1)


def qualify(root, upstream, image):
    if root.exists():
        raise ValueError('fresh isolated S2 root required')
    root.mkdir(parents=True, mode=0o700)
    prepare(root, upstream)
    kb, kbc, _ = native()
    with kbc.connect_closing():
        pass
    from hermes_cli.profiles import create_profile
    for name in ('s2-author', 's2-lead'):
        create_profile(name, no_skills=True, description='Deterministic S2 qualification')
    project = Project.parse(dict(version=1, namespace='delivery-kit-hermes-s2',
        repository='https://github.com/example/qualification', branch='release/qualification',
        validation_image=image, tests_dir='tests', reviewers={'s2-author':'s2-lead'}, qualification=True))
    store = Store(root/'private')
    board = Board(project)
    runner = Runner(project, store)
    quality = Quality(project, store, runner, board)
    fixture = ROOT/'tests/fixtures/delivery'
    author_work = root/'test-author'
    shutil.copytree(fixture/'base', author_work)
    for path in [author_work, author_work/'tests']:
        path.chmod(0o777)
    for path in author_work.rglob('*.py'):
        path.chmod(0o666)
    baseline = store.capture(author_work)
    implementation_work = root/'implementation'
    implementation_work.mkdir(mode=0o777)
    implementation_work.chmod(0o777)
    checks = {}

    def task(kind, workspace, *, parents=(), inputs=None):
        body = dict(version=1, kind=kind, release='s2-fixture', inputs=inputs or {})
        with kbc.connect_closing() as conn:
            return kb.create_task(conn, title='S2 '+kind, body=json.dumps(body), assignee='s2-author',
                workspace_kind='dir', workspace_path=str(workspace), parents=parents,
                completion_contract='local-only')

    def claim(ident, *, review=False):
        with kbc.connect_closing() as conn:
            kb.recompute_ready(conn)
            task = (kb.claim_review_task if review else kb.claim_task)(conn, ident)
            if task is None:
                raise ValueError('native phase is not claimable')
        return board.current(ident, task.current_run_id)

    def rejected(call):
        try:
            call()
        except ValueError:
            return True
        raise AssertionError('unsafe quality operation was accepted')

    def activity(run, workspace, phase, *, bad_tests=False):
        board.ensure(run)
        name = project.namespace+'-activity-'+str(run.number)
        sys.path.insert(0, str(ROOT/'team-delivery-kit'))
        from docker_grouping import args as grouping
        paths = [p for p in store.manifest(baseline) if p.startswith('tests/')]
        command = ['create', '--name', name, *grouping('activity', project.namespace),
            '--network', 'none', '--read-only', '--user', '65534:65534',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
            '--memory', '128m', '--pids-limit', '64', '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m',
            *phase_mounts(workspace, 'tests', phase, baseline_tests=paths),
            '--mount', f'type=bind,src={fixture},dst=/fixture,readonly',
            '--mount', f'type=bind,src={ROOT/"scripts/hermes_s2_activity.py"},dst=/activity.py,readonly',
            'sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e',
            'python', '-B', '/activity.py', phase, 'bad-tests' if bad_tests else 'normal']
        cid = docker(*command).strip()
        folder = root/'activities'/str(run.number)
        try:
            info = json.loads(docker('inspect', cid))[0]
            write_json(folder/'sandbox.json', dict(container=cid, image=info['Image'], mounts=info['Mounts'],
                readonly=info['HostConfig']['ReadonlyRootfs'], network=info['HostConfig']['NetworkMode']))
            output = docker('start', '-a', cid)
            write_json(folder/'output.json', dict(output=output))
            result = json.loads(output)
            assert all(result['checks'].values()), result
            return result
        finally:
            state = json.loads(docker('inspect', cid))[0]
            assert not state['State']['Running']
            write_json(folder/'retirement.json', dict(id=cid, state=state['State']))
            docker('rm', cid)

    tests = task('tests', author_work)
    implementation = task('implementation', implementation_work, parents=[tests],
                          inputs={'tests':'parent:'+tests+':tests'})
    with kbc.connect_closing() as conn:
        assert kb.claim_task(conn, implementation) is None
    author = claim(tests)
    feedback = activity(author, author_work, 'tests', bad_tests=True)
    assert feedback['local_feedback_exit'] == 1
    first = store.capture(author_work)
    red1 = observe(lambda: quality.red(author, baseline, first))
    checks['red_has_real_new_assertion_and_passing_baseline'] = True
    board.review(author, 'Review the new test contract', {'red':red1})
    reviewer = claim(tests, review=True)
    decision = dict(decision='changes', reason='The acceptance says Hello, not Hi',
                    findings=[dict(path='tests/test_greeting.py', line=25, detail='Use the approved greeting text')])
    change = quality.tests_review(reviewer, red1, decision)
    board.finish_review(reviewer, decision['reason'], {'review':change}, changes=True)
    with kbc.connect_closing() as conn:
        event = conn.execute('SELECT payload FROM task_events WHERE task_id=? AND kind=? '
                             'ORDER BY id DESC LIMIT 1', (tests,'changes_requested')).fetchone()
        assert json.loads(json.loads(event[0])['reason'])['evidence']['review'] == change
    checks['change_request_retains_exact_review_evidence'] = True
    author = claim(tests)
    assert author.actor == 's2-author'
    feedback = activity(author, author_work, 'tests')
    assert feedback['local_feedback_exit'] == 1
    candidate = store.capture(author_work)
    red2 = observe(lambda: quality.red(author, baseline, candidate))
    board.review(author, 'Review corrected test contract', {'red':red2})
    reviewer = claim(tests, review=True)
    approved = dict(decision='approve', reason='New test expresses the HTTP acceptance and preserves health', findings=[])
    checks['stale_test_review_rejected'] = rejected(lambda: quality.tests_review(reviewer, red1, approved))
    frozen = quality.tests_review(reviewer, red2, approved)
    board.finish_review(reviewer, approved['reason'], {'tests':frozen})
    checks['changes_returned_to_original_author_then_frozen'] = True
    store.checkout(candidate, implementation_work)
    implementing = claim(implementation)
    assert board.input(implementing, 'tests') == frozen
    checks['dependency_resolves_durable_frozen_test_input'] = True
    feedback = activity(implementing, implementation_work, 'implementation')
    assert feedback['local_feedback_exit'] == 0
    checks['author_feedback_loop_and_os_test_freeze'] = True
    snapshot = store.capture(implementation_work)
    green = observe(lambda: quality.green(implementing, frozen, snapshot))
    checks['green_runs_complete_frozen_suite'] = True
    checks['author_cannot_approve_delivery'] = rejected(lambda:
        quality.delivery_review(implementing, green, 'invalid', approved))

    tampered = root/'tampered'
    store.checkout(snapshot, tampered)
    (tampered/'tests/test_greeting.py').write_text('import unittest\n@unittest.skip("bad")\nclass Hidden(unittest.TestCase):\n def test_hidden(self): pass\n')
    weakened = store.capture(tampered)
    checks['test_skip_and_replacement_rejected'] = rejected(lambda: quality.green(implementing, frozen, weakened))
    mutant_work = root/'mutant'
    store.checkout(snapshot, mutant_work)
    shutil.copyfile(fixture/'base/app.py', mutant_work/'app.py')
    mutant = store.capture(mutant_work)
    controls = observe(lambda: quality.controls(implementing, green, [mutant]))
    checks['post_green_negative_runs_full_suite_and_detects_regression'] = True
    board.review(implementing, 'Review immutable delivery', {'green':green, 'controls':controls})
    reviewer = claim(implementation, review=True)
    activity(reviewer, store.tree(snapshot), 'review')
    receipt = observe(lambda: quality.delivery_review(reviewer, green, controls, approved))
    board.finish_review(reviewer, 'S2 fixture delivery reviewed; not homologated', {'delivery':receipt})
    checks['independent_readonly_review_revalidates_exact_delivery'] = True
    assert store.receipt(receipt)['payload']['delivery_approval'] is False
    assert all(checks.values())
    assert not docker('ps', '-aq', '--filter', 'label=com.docker.compose.project='+project.namespace+'-tests').strip()
    result = dict(version=1, checks=checks, synthetic_workers=True, native_manual_claim_fixture=True,
                  model_calls=0, migration=False, delivery_approval=False, delivery_review=receipt,
                  next_stage='PR/CI and exact-commit deploy/QA/rollback')
    write_json(root/'receipt.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--upstream', type=Path, required=True)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    qualify(args.root.resolve(), args.upstream.resolve(), args.image)
