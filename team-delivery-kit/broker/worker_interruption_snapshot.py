"""Fixed diagnostic copy after pre-tool interruption; never a new Red receipt."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
try:
    from host_restart_snapshot import preserve as preserve_baseline
except ImportError:
    from broker.host_restart_snapshot import preserve as preserve_baseline


def preserve(base, workspace, snapshot, frozen_hashes):
    base, workspace, snapshot = map(Path, (base, workspace, snapshot))
    contract = json.loads((base / 'contract.json').read_text())
    if not isinstance(frozen_hashes, dict) or not frozen_hashes:
        raise ValueError('existing frozen tests required')
    for name, expected in frozen_hashes.items():
        path = PurePosixPath(name)
        if (not isinstance(name, str) or str(path) != name or path.is_absolute()
                or '..' in path.parts or name not in contract['editable_files']
                or not re.fullmatch(r'[a-f0-9]{64}', expected)):
            raise ValueError('invalid frozen test identity')
        file = workspace / name
        if (file.is_symlink() or any(p.is_symlink() for p in list(file.parents)[:len(path.parts)-1])
                or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != expected):
            raise ValueError('frozen test changed after interruption')
    proof = preserve_baseline(base, workspace, snapshot)
    for name, expected in frozen_hashes.items():
        if hashlib.sha256((snapshot / name).read_bytes()).hexdigest() != expected:
            raise ValueError('copied frozen test drift')
    return dict(proof, frozen_tests_unchanged=True, frozen_test_hashes=frozen_hashes,
                diagnostic_only=True, operation='pre_tool_worker_interruption_snapshot_v1')


if __name__ == '__main__':
    print(json.dumps(preserve('/base', '/workspace', '/snapshot',
                             json.loads(os.environ['DELIVERY_FROZEN_HASHES_JSON']))))
