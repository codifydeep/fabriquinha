"""Real Hermes Kanban + Docker qualification. Deterministic, zero model calls.

Run only against a fresh private root. Never use an existing Hermes home.
Upstream is an external pinned checkout, not vendored or modified by this script.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from fabriquinha.kanban_lane import Lane, UPSTREAM_COMMIT, docker, native, save


def prepare(root, upstream):
    if subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip() != UPSTREAM_COMMIT:
        raise ValueError('wrong upstream commit')
    if subprocess.check_output(['git', '-C', str(upstream), 'status', '--porcelain'], text=True).strip():
        raise ValueError('upstream has local patches')
    sys.path.insert(0, str(upstream))
    home = root / 'home'
    os.environ.update(HERMES_HOME=str(home), HERMES_KANBAN_DB=str(home / 'kanban.db'),
                      HERMES_KANBAN_BOARD='default', PYTHONDONTWRITEBYTECODE='1',
                      PYTHONPATH=os.pathsep.join([str(ROOT / 'src'), str(upstream)]))
    return home


def wait(predicate, *, seconds=35):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if value := predicate():
            return value
        time.sleep(0.1)
    raise TimeoutError('S1 bounded observation expired')


def dashboard(upstream):
    path = upstream / 'plugins/kanban/dashboard/plugin_api.py'
    spec = importlib.util.spec_from_file_location('hermes_s1_dashboard', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def qualify(root, upstream, image):
    if root.exists():
        raise ValueError('use a fresh private S1 root')
    root.mkdir(parents=True, mode=0o700)
    home = prepare(root, upstream)
    kb, kbc, dispatch = native()
    with kbc.connect_closing():
        pass
    from hermes_cli.profiles import create_profile
    for name in ('s1-author', 's1-reviewer', 's1-other'):
        create_profile(name, description='Deterministic isolated S1 fixture', no_skills=True)
    api = dashboard(upstream)
    api.get_board(tenant=None, include_archived=False, board=None,
                  workflow_template_id=None, current_step_key=None)
    config = root / 'settings.json'
    save(config, dict(image=image))
    lane = Lane(config)
    results = {}

    def task(title, *, body='normal', assignee='s1-author', parents=(), retries=2, contract=None):
        workspace = root / 'work' / title
        workspace.mkdir(parents=True, mode=0o777)
        workspace.chmod(0o777)
        with kbc.connect_closing() as conn:
            return kb.create_task(conn, title=title, body=body, assignee=assignee,
                workspace_kind='dir', workspace_path=str(workspace), parents=parents,
                max_retries=retries, max_runtime_seconds=30, completion_contract=contract)

    def status(ident):
        with kbc.connect_closing() as conn:
            return kb.get_task(conn, ident)

    def drive(ident):
        lane.tick()
        for source in (first, ident):
            if status(source).status == 'blocked':
                raise RuntimeError(status(source).last_failure_error)
        return status(ident).status == 'done'

    first = task('review-cycle')
    child = task('dependent', body='leaf', parents=[first])
    assert status(child).status == 'todo'
    wait(lambda: drive(child), seconds=75)
    with kbc.connect_closing() as conn:
        runs = [dict(row) for row in conn.execute('SELECT id,profile,outcome FROM task_runs '
                                                'WHERE task_id=? ORDER BY id', (first,))]
    assert [r['profile'] for r in runs] == ['s1-author', 's1-reviewer', 's1-author', 's1-reviewer'], runs
    assert [r['outcome'] for r in runs] == ['review_requested', 'changes_requested', 'review_requested', 'completed'], runs
    assert (root / 'work/review-cycle/product.txt').read_bytes() == b'version two\n'
    results['native_review_rework_dependency'] = True
    stale_card = task('stale-result-control', body='leaf')
    with kbc.connect_closing() as conn:
        original = kb.claim_task(conn, stale_card)
        assert kb.request_review(conn, stale_card, reviewer='s1-reviewer', summary='S1 control',
                                 expected_run_id=original.current_run_id)
        current = kb.claim_review_task(conn, stale_card)
        assert current.current_run_id != original.current_run_id
        assert not kb.complete_task(conn, stale_card, summary='old result', expected_run_id=original.current_run_id)
        assert kb.get_task(conn, stale_card).status == 'running'
        assert kb.complete_task(conn, stale_card, summary='S1 control cleanup', expected_run_id=current.current_run_id)
    results['stale_result_rejected'] = True

    crash = task('crash-recovery', body='crash-once')
    wait(lambda: drive(crash), seconds=75)
    with kbc.connect_closing() as conn:
        outcomes = [r[0] for r in conn.execute('SELECT outcome FROM task_runs WHERE task_id=? ORDER BY id', (crash,))]
    assert 'crashed' in outcomes, outcomes
    results['worker_crash_preserved_write_recovered'] = True

    restart = task('dispatcher-restart', body='leaf')
    subprocess.run([sys.executable, str(Path(__file__).resolve()), '--tick', '--root', str(root),
                    '--upstream', str(upstream)], check=True, timeout=15)
    assert status(restart).status == 'running', 'worker must outlive the dispatcher process'
    subprocess.run([sys.executable, str(Path(__file__).resolve()), '--tick', '--root', str(root),
                    '--upstream', str(upstream)], check=True, timeout=15)
    wait(lambda: status(restart).status == 'done')
    with kbc.connect_closing() as conn:
        assert conn.execute('SELECT count(*) FROM task_runs WHERE task_id=?', (restart,)).fetchone()[0] == 1
    lane = Lane(config)  # Reconnect without any controller in-memory state.
    results['dispatcher_process_exit_worker_survives'] = True

    held = [task('hold-a', body='hold', retries=1),
            task('hold-a2', body='hold', retries=1),
            task('hold-b', body='hold', assignee='s1-other', retries=1)]
    tick = lane.tick()
    assert len(tick.spawned) == 2 and tick.skipped_per_profile_capped
    assert sorted(status(t).status for t in held) == ['ready', 'running', 'running']
    assert not lane.tick().spawned
    results['two_workers_one_per_profile'] = True
    for ident in (held[0], held[2]):
        run = status(ident).current_run_id
        sandbox = root / 'runs' / str(run) / 'sandbox.json'
        wait(lambda: sandbox.exists())
        cid = json.loads(sandbox.read_text())['container']
        row = json.loads(docker('inspect', cid))[0]
        assert row['Config']['Labels']['com.docker.compose.project'] == 'delivery-kit-hermes-s1-tests'
        docker('kill', cid)
    def reaped():
        for proc in lane.children:
            proc.poll()
        with kbc.connect_closing() as conn:
            dispatch.dispatch_once(conn, spawn_fn=lane.spawn, max_spawn=0, max_in_progress=2,
                max_in_progress_per_profile=1)
        return all(status(t).status != 'running' for t in held)
    wait(reaped)

    # The real PR completion gate must reject absent PR/check evidence on all
    # native surfaces; this is not an invented publication boolean in our lane.
    gated = task('missing-pr-proof', body='leaf', contract='codifydeep/descartavel2')
    with kbc.connect_closing() as conn:
        assert not kb.complete_task(conn, gated, summary='attempt without PR')
    def gate_events():
        with kbc.connect_closing() as conn:
            return [json.loads(r[0]) for r in conn.execute('SELECT payload FROM task_events '
                'WHERE task_id=? AND kind=? ORDER BY id', (gated, 'pr_acceptance'))]
    assert len(gate_events()) == 1
    from hermes_cli.kanban import run_slash
    cli_output = run_slash('complete ' + gated + ' --result "no evidence"')
    results['cli_pr_gate_rejected'] = status(gated).status != 'done' and bool(cli_output)
    assert len(gate_events()) == 2, cli_output
    try:
        api.update_task(gated, api.UpdateTaskBody(status='done', summary='no PR'), board=None)
        raise AssertionError('dashboard accepted missing PR evidence')
    except api.HTTPException:
        results['dashboard_pr_gate_rejected'] = True
    assert len(gate_events()) == 3
    from tools.kanban_tools import _handle_complete
    tool = json.loads(_handle_complete(dict(task_id=gated, summary='no PR')))
    assert tool.get('error') or tool.get('success') is False, tool
    assert len(gate_events()) == 4, tool
    assert all(event['classification'] == 'missing' and event['ok'] is False for event in gate_events())
    results['tool_pr_gate_rejected'] = True
    assert status(gated).status != 'done'
    board = api.get_board(tenant=None, include_archived=False, board=None,
                          workflow_template_id=None, current_step_key=None)
    save(root / 'dashboard-board.json', board)
    assert first in json.dumps(board) and child in json.dumps(board)
    results['real_dashboard_api_same_board'] = True

    workers = [json.loads(p.read_text()) for p in (root / 'runs').glob('*/worker.json')]
    assert workers and all(all(w['isolation'].values()) for w in workers)
    reviews = [w for w in workers if 'review_write_denied' in w['isolation']]
    assert reviews and all(w['isolation']['review_write_denied'] for w in reviews)
    results['real_container_isolation_and_readonly_review'] = True
    for child_proc in lane.children:
        child_proc.wait(timeout=10)
    remaining = docker('ps', '-aq', '--filter', 'label=com.docker.compose.project=delivery-kit-hermes-s1-tests').strip()
    assert not remaining, 'probe containers remain; inspect before retrying'
    results['all_probe_containers_retired'] = True
    assert all(results.values()), results
    receipt = dict(schema_version=1, upstream_commit=UPSTREAM_COMMIT, upstream_patches=0,
        checks=results, model_calls=0, synthetic_workers=True, migration=False,
        delivery_approval=False, production_gateway_integration=False)
    save(root / 'receipt.json', receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--upstream', type=Path, required=True)
    parser.add_argument('--image', default='sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e')
    parser.add_argument('--tick', action='store_true')
    args = parser.parse_args()
    if args.tick:
        prepare(args.root.resolve(), args.upstream.resolve())
        Lane(args.root / 'settings.json').tick()
    else:
        qualify(args.root.resolve(), args.upstream.resolve(), args.image)
