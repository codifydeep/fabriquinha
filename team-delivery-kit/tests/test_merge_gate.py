import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('merge_gate', ROOT / 'broker/merge_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class LocalMergeGateTests(unittest.TestCase):
    def test_stale_review_ci_and_moved_head_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            repo, snapshot = Path(directory) / 'repo', Path(directory) / 'snapshot'
            repo.mkdir(); snapshot.mkdir()
            fixture = ROOT / 'tests/fixtures/tdd'
            manifest = {'files': {}}
            for name in gate.FILES:
                content = (fixture / name).read_bytes()
                (repo / name).write_bytes(content)
                (snapshot / name).write_bytes(content)
                manifest['files'][name] = {'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}
            encoded = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
            (snapshot / 'manifest.json').write_bytes(encoded)
            def run(*args):
                return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.DEVNULL).decode().strip()
            run('init', '-q'); run('config', 'user.email', 'eval@example.invalid'); run('config', 'user.name', 'Eval')
            run('add', '.'); run('commit', '-qm', 'reviewed fixture')
            head = run('rev-parse', 'HEAD')
            source = 'corrected-source'
            review = {'status': 'approved', 'source_task_id': source,
                      'head_sha': head,
                      'manifest_sha256': hashlib.sha256(encoded).hexdigest()}
            ci = {'head_sha': head, 'status': 'success', 'review_manifest_sha256': review['manifest_sha256'], 'tests': 3}
            self.assertEqual(gate.verify_local_merge_preconditions(repo, head, source, review, ci, snapshot)['head_sha'], head)
            with self.assertRaisesRegex(ValueError, 'review does not cover'):
                gate.verify_local_merge_preconditions(repo, head, source, {**review, 'source_task_id': 'old-source'}, ci, snapshot)
            with self.assertRaisesRegex(ValueError, 'review does not cover'):
                gate.verify_local_merge_preconditions(repo, head, source, {**review, 'head_sha': '0'*40}, ci, snapshot)
            with self.assertRaisesRegex(ValueError, 'CI does not cover'):
                gate.verify_local_merge_preconditions(repo, head, source, review, {**ci, 'head_sha': '0'*40}, snapshot)
            with self.assertRaisesRegex(ValueError, 'CI does not cover'):
                gate.verify_local_merge_preconditions(repo, head, source, review, {**ci, 'status': 'failed'}, snapshot)
            (repo / 'calc.py').write_text((repo / 'calc.py').read_text() + '\n# changed after review\n')
            run('add', '.'); run('commit', '-qm', 'move PR head')
            new_head = run('rev-parse', 'HEAD')
            with self.assertRaisesRegex(ValueError, 'PR head moved'):
                gate.verify_local_merge_preconditions(repo, head, source, review, ci, snapshot)
            with self.assertRaisesRegex(ValueError, 'PR commit differs'):
                gate.verify_local_merge_preconditions(repo, new_head, source, {**review, 'head_sha': new_head},
                                                      {**ci, 'head_sha': new_head}, snapshot)
            (repo / 'unreviewed.txt').write_text('surprise')
            run('add', '.'); run('commit', '-qm', 'add unreviewed file')
            with self.assertRaisesRegex(ValueError, 'unreviewed files'):
                gate.verify_local_merge_preconditions(repo, run('rev-parse', 'HEAD'), source,
                                                      {**review, 'head_sha': run('rev-parse', 'HEAD')},
                                                      {**ci, 'head_sha': run('rev-parse', 'HEAD')}, snapshot)
