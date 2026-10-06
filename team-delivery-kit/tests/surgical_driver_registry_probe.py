"""Actual Hermes registry/ACP canary in a disposable, offline tmpfs fixture.

Run as root with only SETUID/SETGID, then drop privileges before tool calls.
No product snapshot, model request, Docker socket or credential is mounted.
"""
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, '/opt/hermes')
source = b'''import unittest
DRIVER_PREAMBLE = "unchanged"
DRIVER_BODY = "Promise.resolve().then(() => {"
class Tests(unittest.TestCase):
    def test_existing(self):
        self.assertEqual(1, 1)
'''
target = Path('/workspace/test_probe.py')
target.write_bytes(source)
target.chmod(0o666)
size_target=Path('/workspace/test_size_probe.py')
balanced=source.replace(b'Promise.resolve().then(() => {',b'Promise.resolve().then(() => {});')
size_source=balanced+b'#'+b'x'*(32600-len(balanced)-2)+b'\n'
size_target.write_bytes(size_source)
size_target.chmod(0o666)
digest = hashlib.sha256(source).hexdigest()
config = {'path': str(target), 'expected_sha256': digest, 'protocol': 'typed_driver_v3'}
os.environ.update(DELIVERY_EXECUTION_MODE='implementation',
                  DELIVERY_SURGICAL_TEST_JSON=json.dumps(config), HERMES_HOME='/tmp/hermes-canary')
os.setgroups([])
os.setgid(10000)
os.setuid(10000)
from tools.registry import registry, discover_builtin_tools
discover_builtin_tools()
from model_tools import get_tool_definitions
from acp_adapter.session import _expand_acp_enabled_toolsets
actual = get_tool_definitions(quiet_mode=True)
acp = get_tool_definitions(enabled_toolsets=_expand_acp_enabled_toolsets(['hermes-acp']), quiet_mode=True)
assert 'surgical_test_edit' in {t['function']['name'] for t in actual}
assert 'surgical_test_edit' in {t['function']['name'] for t in acp}
definitions = [t for t in acp if t['function']['name'] in ('read_file', 'write_file', 'surgical_test_edit')]
args = {'path': str(target), 'expected_sha256': digest, 'edits': [
    {'old': 'Promise.resolve().then(() => {', 'new': 'Promise.resolve().then(() => {});'}]}

def invoke(name, value):
    return json.loads(registry.dispatch(name, value))

assert invoke('surgical_test_edit', args).get('error')
assert invoke('write_file', {'path': str(target), 'content': 'bad'}).get('error')
assert invoke('terminal', {'command': 'true'}).get('error')
assert target.read_bytes() == source
read = invoke('read_file', {'path': str(target), 'offset': 1, 'limit': 50})
assert isinstance(read.get('content'), str) and read.get('total_lines') == 6
from review_tool_policy import controlled
from acp_adapter.tools import _format_generic_structured_result
for old,new,reason,count in [('unittest','other','ambiguous',2),
        ('missing_fragment','other','missing',0),
        ('Promise.resolve().then(() => {','Promise.resolve().then(() => {','unchanged',1)]:
    candidate={**args,'edits':[{'old':old,'new':new}]}
    feedback=invoke('surgical_test_edit',candidate)
    assert feedback['fragment_diagnostic']['index']==1
    assert feedback['fragment_diagnostic']['match_count']==count
    assert feedback['fragment_diagnostic']['reason']==reason
    assert target.read_bytes()==source
    visible=_format_generic_structured_result('surgical_test_edit',json.dumps(feedback))
    assert 'fragment_index=1' in visible and 'match_count='+str(count) in visible
    assert old not in visible
cases = [
    ({'old': 'Promise.resolve().then(() => {', 'new': 'Promise.resolve().then(() => {{'}, 'driver_syntax_invalid'),
    ({'old': 'unchanged', 'new': 'changed'}, 'outside_driver_scope_changed'),
    ({'old': 'self.assertEqual(1, 1)', 'new': 'pass'}, 'test_bodies_changed'),
]
for edit, category in cases:
    candidate = {**args, 'edits': [edit]}
    result = invoke('surgical_test_edit', candidate)
    assert result['category'] == category, result
    assert target.read_bytes() == source
    assert json.loads(controlled('surgical_test_edit', candidate))['category'] == category
    visible = _format_generic_structured_result('surgical_test_edit', json.dumps(result))
    assert category in visible

# These protocol fixtures test proxy selection, not real model calls/read receipts.
from model_proxy import validate_request, MODEL
from artifact_response_contract import validate, ArtifactResponseRejected
body = {'model': MODEL, 'messages': [{'role': 'user', 'content':
    'DELIVERY_TEST_ARTIFACT_V1:' + str(target) + '\nDELIVERY_TEST_SOURCE_V1:/workspace/app.py\n'
    'DELIVERY_SURGICAL_TEST_V3:' + str(target) + ':' + digest + '\n'}], 'tools': definitions}
for index, path in enumerate(['/workspace/app.py', str(target)]):
    body['messages'] += [{'role': 'assistant', 'tool_calls': [{'id': str(index), 'function': {
        'name': 'read_file', 'arguments': json.dumps({'path': path, 'offset': 1, 'limit': 50})}}]},
        {'role': 'tool', 'tool_call_id': str(index), 'content': json.dumps({'content': '1|source', 'total_lines': 1})}]
body = validate_request(body)
assert body['tool_choice']['function']['name'] == 'surgical_test_edit'

def response(value):
    return json.dumps({'choices': [{'message': {'tool_calls': [{'function': {
        'name': 'surgical_test_edit', 'arguments': json.dumps(value)}}]}, 'finish_reason': 'tool_calls'}]}).encode()

validate(body, response(args), 'application/json')
for changes, category in [({'path': '/workspace/app.py'}, 'surgical_path_mismatch'),
                          ({'expected_sha256': '0' * 64}, 'surgical_hash_mismatch'),
                          ({'edits': []}, 'surgical_edits_invalid')]:
    try:
        validate(body, response({**args, **changes}), 'application/json')
    except ArtifactResponseRejected as error:
        assert error.category == category
    else:
        raise AssertionError('invalid response accepted')
result = invoke('surgical_test_edit', args)
assert result.get('verified') and result.get('test_bodies_preserved') and result.get('delivery_approval') is False
assert target.read_bytes() != source
accepted = target.read_bytes()
assert invoke('surgical_test_edit', args).get('error')
assert target.read_bytes() == accepted
from tools.surgical_tool import handle
os.environ.pop('DELIVERY_SURGICAL_TEST_JSON')
assert json.loads(handle(args)).get('error')
size_digest=hashlib.sha256(size_source).hexdigest()
os.environ['DELIVERY_SURGICAL_TEST_JSON']=json.dumps({'path':str(size_target),
    'expected_sha256':size_digest,'protocol':'typed_driver_v3'})
invoke('read_file',{'path':str(size_target),'offset':1,'limit':50})
size_args={'path':str(size_target),'expected_sha256':size_digest,'edits':[
    {'old':'Promise.resolve().then(() => {});','new':'Promise.resolve().then(() => {});'+(' '*200)}]}
size_result=invoke('surgical_test_edit',size_args)
assert size_result['category']=='file_size_exceeded',size_result
assert 'compact_driver_comments' in size_result['next_operation']
assert size_target.read_bytes()==size_source
print(json.dumps({'schema': 'surgical-driver-registry-probe-v3', 'status': 'passed',
    'actual_registry': True, 'actual_default_selection': True, 'actual_acp_selection': True,
    'proxy_protocol_fixture': True, 'readless_edit_denied': True,
    'generic_write_and_terminal_denied': True, 'direct_handler_fenced': True,
    'invalid_syntax_preserves_bytes': True, 'outside_driver_change_preserves_bytes': True,
    'test_weakening_preserves_bytes': True, 'stale_edit_denied': True,
    'fixed_node_check': True, 'uid': os.getuid(), 'network': 'none',
    'credentials_absent': not Path('/secret').exists() and not Path('/var/run/docker.sock').exists(),
    'file_size_feedback_preserves_bytes':True,'fragment_identity_feedback_preserves_bytes':True,
    'fragment_identity_feedback_acp_visible':True,'delivery_approval': False}))
