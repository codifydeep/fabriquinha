"""Actual Hermes registry and direct handlers; no ACP/model request or RPC."""
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path[:0]=['/opt/hermes','/']
from tools.registry import registry,discover_builtin_tools

assert os.getuid()==10000
discover_builtin_tools()
protected=['/workspace/app.py','/workspace/tests/test_old.py']
before={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in protected}
for name,args in [('terminal',dict(command='touch /tmp/must-not-execute')),
        ('python',dict(code="open('/workspace/app.py','w').write('bad')")),
        ('write_file',dict(path='/workspace/app.py',content='bad')),
        ('write_file',dict(path='/workspace/tests/test_old.py',content='bad')),
        ('read_file',dict(path='/tmp/key'))]:
    rejected=json.loads(registry.dispatch(name,args))
    assert rejected.get('error')=='operation_forbidden_in_tests_only_v2',rejected
entry=registry.get_entry('terminal')
assert entry is not None
rejected=json.loads(entry.handler(dict(command='touch /tmp/must-not-execute')))
assert rejected.get('error')=='operation_forbidden_in_tests_only_v2'
assert not Path('/tmp/must-not-execute').exists()
result=json.loads(registry.dispatch('read_file',dict(path='/workspace/app.py',offset=1,limit=200)))
assert not result.get('error') and 'VALUE=0' in result['content'],result
content='import unittest\nimport app\nclass New(unittest.TestCase):\n def test_new(self):self.assertEqual(app.VALUE,1)\n'
result=json.loads(registry.dispatch('write_file',dict(path='/workspace/tests/test_new.py',content=content)))
assert not result.get('error'),result
assert Path('/workspace/tests/test_new.py').read_text()==content
assert before=={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in protected}
print(json.dumps(dict(operation='tests_only_actual_registry_qualification_v2',status='passed',
    direct_handler_denied=True,protected_sha256=before,model_calls=0,delivery_approval=False)))
