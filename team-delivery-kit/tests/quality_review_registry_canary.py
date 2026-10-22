"""Actual Hermes review handlers and read-only mount, without ACP/model calls."""
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path[:0] = ['/opt/hermes', '/']
from tools.registry import registry, discover_builtin_tools

assert os.getuid() == 10000
discover_builtin_tools()
paths = json.loads(os.environ['DELIVERY_QUALITY_PHASE_JSON'])['read_paths']
before = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths}
read_pairs=[]
for index,path in enumerate(paths):
    args=dict(path=path,offset=1,limit=100)
    raw=registry.dispatch('read_file',args)
    result = json.loads(raw)
    assert not result.get('error') and isinstance(result.get('content'), str), result
    read_pairs.extend([dict(type='tool_use',tool='read_file',call_id='canary-'+str(index),input=args),
        dict(type='tool_result',tool='read_file',call_id='canary-'+str(index),output=raw)])
for name, args in [('write_file', dict(path=paths[-1], content='weaken tests')),
        ('patch', dict(path=paths[0], patch='bad')), ('terminal', dict(command='touch /tmp/must-not-execute')),
        ('python', dict(code="open('/delivery/app.py','w').write('bad')")),
        ('read_file', dict(path='/tmp/key', offset=1, limit=100)),
        ('read_file', dict(path=paths[0], offset=1, limit=101))]:
    rejected = json.loads(registry.dispatch(name, args))
    assert rejected.get('error') == 'operation_forbidden_in_test_review_v2', rejected
for name, args in [('terminal', dict(command='touch /tmp/must-not-execute')),
        ('write_file', dict(path=paths[-1], content='weaken tests'))]:
    entry = registry.get_entry(name)
    assert entry is not None
    rejected = json.loads(entry.handler(args))
    assert rejected.get('error') == 'operation_forbidden_in_test_review_v2', rejected
assert not Path('/tmp/must-not-execute').exists()
for path in paths:
    # Try chmod before a raw write: initial file mode alone is not isolation.
    try:
        os.chmod(path, 0o666)
        Path(path).write_text('bypass handler')
        raise AssertionError('review mount was writable')
    except (PermissionError, OSError):
        pass
assert before == {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths}
assert not Path('/var/run/docker.sock').exists()
print(json.dumps(dict(operation='test_review_actual_registry_qualification_v2', status='passed',
    direct_handler_denied=True, readonly_mount=True, snapshot_unchanged=True,
    protected_sha256=before,read_pairs=read_pairs,reads_origin='fixed_operator_canary_not_native_stream',
    model_calls=0, delivery_approval=False)))
