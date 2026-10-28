"""Isolated native review of real Red evidence, using the actual SDK/tools.

Preparation makes no model calls. Running the review uses the authorized relay;
no product installation/card is copied, changed or approved. No automatic retry.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from qualify_hermes_s1 import prepare
from qualify_hermes_s2 import observe
from fabriquinha.artifacts import Store
from fabriquinha.board import Board
from fabriquinha.config import Project
from fabriquinha.effects import write_json
from fabriquinha.executor import Runner
from fabriquinha.hermes import Sandbox, run_activity
from fabriquinha.kanban_lane import native
from fabriquinha.quality import Quality


def setup(root, upstream, image):
    if root.exists():
        raise ValueError('fresh isolated qualification root required')
    root.mkdir(parents=True, mode=0o700)
    home = prepare(root, upstream)
    kb, kbc, _ = native()
    with kbc.connect_closing():
        pass
    from hermes_cli.profiles import create_profile
    for actor in ('review-author', 'review-lead'):
        create_profile(actor, no_skills=True, description='Isolated native review qualification')
        write_json(home / 'profiles' / actor / 'config.yaml', dict(
            model=dict(streaming=False, context_length=131072),
            auxiliary=dict(title_generation=dict(enabled=False)),
            tools=dict(tool_search=dict(enabled='off')),
            terminal=dict(backend='fabriquinha', cwd='/workspace')))
    config = dict(version=1, namespace='delivery-kit-native-review',
                  repository='https://github.com/example/qualification', branch='release/proof',
                  validation_image=image, tests_dir='tests',
                  reviewers={'review-author': 'review-lead'}, qualification=True)
    write_json(root / 'project.json', config)
    project = Project.parse(config)
    store = Store(root / 'private')
    board = Board(project)
    quality = Quality(project, store, Runner(project, store), board)
    work = root / 'work'
    (work / 'tests').mkdir(parents=True)
    (work / 'app.py').write_text('VALUE = 1\n')
    (work / 'tests/test_baseline.py').write_text('import unittest, app\nclass Baseline(unittest.TestCase):\n def test_integer(self): self.assertIsInstance(app.VALUE, int)\n')
    baseline = store.capture(work)
    (work / 'tests/test_new.py').write_text('import unittest, app\nclass Feature(unittest.TestCase):\n def test_two(self): self.assertEqual(app.VALUE, 2)\n')
    snapshot = store.capture(work)
    with kbc.connect_closing() as conn:
        task = kb.create_task(conn, title='Isolated review: integer VALUE becomes exactly two',
            body=json.dumps(dict(version=1, kind='tests', release='native-red-review', inputs=dict(baseline=baseline))),
            assignee='review-author', workspace_kind='dir', workspace_path=str(work), completion_contract='local-only')
        claimed = kb.claim_task(conn, task)
    author = board.current(task, claimed.current_run_id)
    red = observe(lambda: quality.red(author, baseline, snapshot))
    quality.handoff(author, 'Real Red, awaiting independent test review', dict(red=red))
    with kbc.connect_closing() as conn:
        claimed = kb.claim_review_task(conn, task)
    reviewer = board.current(task, claimed.current_run_id)
    value = dict(task=task, run=reviewer.number, red=red, snapshot=snapshot,
                 model_calls=0, delivery_approval=False)
    write_json(root / 'prepared.json', value)
    return value


def review(root, upstream, installation):
    intent = root / 'review-intent.json'
    if intent.exists():
        raise ValueError('existing review intent: inspect evidence, never repeat automatically')
    home = prepare(root, upstream)
    saved = json.loads((root / 'prepared.json').read_bytes())
    project = Project.parse(json.loads((root / 'project.json').read_bytes()))
    board = Board(project)
    run = board.current(saved['task'], saved['run'])
    os.environ.update(HERMES_HOME=str(home / 'profiles' / run.actor), HERMES_DISABLE_LAZY_INSTALLS='1')
    route = json.loads((installation / 'route.json').read_bytes())
    store = Store(root / 'private')
    quality = Quality(project, store, Runner(project, store), board)
    sandbox = Sandbox(project, store, board, run)
    write_json(intent, dict(binding=run.binding(), model=route['model'], delivery_approval=False))
    result = run_activity(sandbox, quality, route,
        'Review the existing tests against this isolated requirement: app.VALUE remains an integer and becomes exactly 2. '
        'Inspect the immutable files and recorded evidence, then use the real review operation. '
        'This is test review, not product implementation or release approval.',
        run_seconds=300, output_limit=16384)
    kb, kbc, _ = native()
    with kbc.connect_closing() as conn:
        task = kb.get_task(conn, run.task)
        state = task.status
    unchanged = store.capture(root / 'work') == saved['snapshot']
    passed = result['transition']['status'] == 'completed' and state == 'done' and unchanged
    output = dict(passed=passed, result=result, native_state=state,
                  author_snapshot_preserved=unchanged, delivery_approval=False,
                  scope='isolated expected-Red test review; not S6 or autonomous delivery')
    write_json(root / 'result.json', output)
    return output


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['prepare', 'review'])
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--upstream', type=Path, required=True)
    p.add_argument('--image')
    p.add_argument('--installation', type=Path)
    a = p.parse_args()
    if a.mode == 'prepare' and not a.image or a.mode == 'review' and not a.installation:
        p.error('prepare requires image; review requires installation')
    output = setup(a.root.resolve(), a.upstream.resolve(), a.image) if a.mode == 'prepare' else review(a.root.resolve(), a.upstream.resolve(), a.installation.resolve())
    print(json.dumps(output, indent=2))
