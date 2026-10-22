"""Fixed Green handler canary, not agent work or a functional Green receipt."""
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path[:0]=['/opt/hermes','/']
from tools.registry import registry,discover_builtin_tools

assert os.getuid()==10000
discover_builtin_tools()
protected=['/workspace/AGENTS.md','/workspace/tests/test_old.py','/workspace/tests/test_new.py']
before={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in protected}
for name,args in [('terminal',dict(command='touch /tmp/must-not-execute')),
        ('python',dict(code="open('/workspace/tests/test_new.py','w').write('bad')")),
        ('patch',dict(path='/workspace/app.py',content='bad')),
        ('write_file',dict(path='/workspace/tests/test_new.py',content='bad')),
        ('write_file',dict(path='/workspace/tests/test_old.py',content='bad')),
        ('write_file',dict(path='/workspace/AGENTS.md',content='bad')),
        ('read_file',dict(path='/previous/manifest.json')),('read_file',dict(path='/tmp/key'))]:
    result=json.loads(registry.dispatch(name,args))
    assert result.get('error')=='operation_forbidden_in_implementation_v2',result
for name,args in [('terminal',dict(command='touch /tmp/must-not-execute')),
        ('write_file',dict(path='/workspace/tests/test_new.py',content='bad'))]:
    entry=registry.get_entry(name);assert entry is not None
    result=json.loads(entry.handler(args))
    assert result.get('error')=='operation_forbidden_in_implementation_v2',result
assert not Path('/tmp/must-not-execute').exists()
for path in protected[1:]:
    result=json.loads(registry.dispatch('read_file',dict(path=path,offset=1,limit=200)))
    assert not result.get('error') and 'unittest' in result['content'],result
content='VALUE=8\n'
result=json.loads(registry.dispatch('write_file',dict(path='/workspace/app.py',content=content)))
assert not result.get('error'),result
assert Path('/workspace/app.py').read_text()==content
assert before=={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in protected}
assert not Path('/var/run/docker.sock').exists() and not Path('/previous').exists()
print(json.dumps(dict(operation='implementation_actual_registry_qualification_v2',status='passed',
    direct_handler_denied=True,product_write=True,frozen_tests_unchanged=True,protected_sha256=before,
    model_calls=0,native_qualification=False,green_approval=False,delivery_approval=False)))
