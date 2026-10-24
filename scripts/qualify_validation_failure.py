"""Physical timeout/restart/retirement proof; synthetic infrastructure, not delivery."""
import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.effects import EffectBlocked, Pending, write_json
from fabriquinha.executor import Runner, docker


def qualify(root, image):
    if root.exists():
        raise ValueError('fresh isolated timeout proof directory required')
    root.mkdir(parents=True, mode=0o700)
    workspace = root/'workspace'
    (workspace/'tests').mkdir(parents=True)
    (workspace/'tests/test_timeout.py').write_text(
        'import time, unittest\nclass Hung(unittest.TestCase):\n'
        ' def test_hung(self): time.sleep(60)\n')
    project = Project.parse(dict(version=1, namespace='delivery-kit-hermes-timeout',
        repository='https://github.com/example/qualification', branch='release/qualification',
        validation_image=image, tests_dir='tests', reviewers={'fixture':'reviewer'},
        qualification=True, timeout_seconds=1))
    store = Store(root/'private')
    snapshot = store.capture(workspace)
    run = Run('infrastructure-probe', 1, 'fixture', 'implementation', False,
              'fixture', 'timeout-proof', project.fingerprint())
    runner = Runner(project, store)
    while True:
        try:
            runner.run(run, snapshot, 'green')
        except Pending:
            time.sleep(.1)
            continue
        except EffectBlocked:
            break
        raise AssertionError('timeout job became successful')
    results = list((store.root/'jobs').glob('*/result.json'))
    assert len(results) == 1
    import json
    saved = json.loads(results[0].read_bytes())
    receipt = store.receipt(saved['receipt'], kind='suite_job')
    assert receipt['payload']['infrastructure_error'] == 'validation job exceeded its persistent runtime'
    assert (results[0].parent/'retired-metadata.json').exists()
    assert (results[0].parent/'output.json').exists()
    try:
        Runner(project, store).run(run, snapshot, 'green')
    except EffectBlocked:
        pass
    else:
        raise AssertionError('restarted controller accepted expired job')
    assert not docker('ps', '-aq', '--filter', 'label=com.docker.compose.project='+project.namespace+'-tests').strip()
    checks = dict(real_timeout=True, private_failure_evidence=True, exact_container_retired=True,
                  restarted_controller_rejects_same_failed_job=True, model_calls=0, delivery_approval=False)
    write_json(root/'receipt.json', checks)
    print(json.dumps(checks, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    qualify(args.root.resolve(), args.image)
