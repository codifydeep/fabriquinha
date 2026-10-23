"""Fixed operator probe of a revision seed/handler, never native model work."""
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path[:0]=['/opt/hermes','/']
from tools.registry import registry,discover_builtin_tools

assert os.getuid()==10000
discover_builtin_tools()
path='/workspace/tests/test_new.py'
raw=Path(path).read_bytes()
assert raw and hashlib.sha256(raw).hexdigest()==os.environ['QUALITY_REVISION_EXPECTED_SHA256']
protected=['/workspace/AGENTS.md','/workspace/app.py','/workspace/tests/test_old.py']
before={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in protected}
for name,args in [('terminal',dict(command='touch /tmp/must-not-execute')),
        ('write_file',dict(path='/workspace/app.py',content='bad')),
        ('write_file',dict(path='/workspace/tests/test_old.py',content='bad')),
        ('read_file',dict(path='/previous/manifest.json'))]:
    result=json.loads(registry.dispatch(name,args))
    assert result.get('error')=='operation_forbidden_in_tests_only_v2',result
for p in protected:
    try:Path(p).write_bytes(b'forbidden')
    except PermissionError:pass
    else:raise AssertionError('protected file was writable')
content=raw.decode()+'\n# Fixed operator revision probe, not agent work.\n'
result=json.loads(registry.dispatch('write_file',dict(path=path,content=content)))
assert not result.get('error'),result
assert Path(path).read_text()==content
assert before=={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in protected}
assert not Path('/var/run/docker.sock').exists() and not Path('/previous').exists()
print(json.dumps(dict(status='passed',seed_sha256=hashlib.sha256(raw).hexdigest(),
    corrected_sha256=hashlib.sha256(content.encode()).hexdigest(),protected_unchanged=True,
    model_calls=0,delivery_approval=False)))
