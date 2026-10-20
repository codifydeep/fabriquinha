"""Real Hermes registry/formatter canary; controller transport is a fixture.

Only run in the disposable, unprivileged, no-network test container. This does
not prove native authorization or execute product tests. No model is called.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import Mock

target=Path('/workspace/test_feedback.py')
source=b'PREFIX="unchanged"\nNODE_HARNESS=r"""\nconst value = 1;\n"""\nclass Checks:\n def test_existing(self):\n  self.assertEqual(1, 2)\n'
target.write_bytes(source)
target.chmod(0o666)
# Match real controller provisioning: root creates the allowed file; all tool
# discovery/dispatch below runs after irreversibly dropping to the worker UID.
assert target.stat().st_uid==0
os.setgroups([]);os.setgid(10000);os.setuid(10000)
assert os.getuid()==10000 and 'CapEff:\t0000000000000000' in Path('/proc/self/status').read_text()
cfg=dict(request_id='11111111-1111-4111-8111-111111111111',task_id='22222222-2222-4222-8222-222222222222',
    capability='a'*64,test_path=target.name,previous_manifest_sha256='b'*64,feedback_sha256='c'*64,
    expected=dict(initial_expected=1,poll_minimum=3,stale_expected='Newest matching: #11'))
os.environ.update(DELIVERY_EXECUTION_MODE='implementation',DELIVERY_AUTHOR_FEEDBACK_JSON=json.dumps(cfg),
    DELIVERY_MODEL_EXECUTION_ID=cfg['request_id'],HERMES_HOME='/tmp/hermes-feedback-canary',HOME='/tmp',
    HERMES_WRITE_SAFE_ROOT='/workspace',HERMES_FENCED_INPLACE_WRITES='1')
sys.path.insert(0,'/opt/hermes')
import author_feedback_client as client
import review_tool_policy
import literal_feedback_wire as wire
import patch_receipt_contract
assert client.__file__=='/opt/hermes/author_feedback_client.py'
assert review_tool_policy.__file__=='/opt/hermes/review_tool_policy.py'
calls=[]
def response(request,**kwargs):
    assert request.full_url==client.ENDPOINT
    current=hashlib.sha256(target.read_bytes()).hexdigest()
    assert json.loads(request.data)==dict(candidate_sha256=current)
    calls.append(current)
    value=dict(operation='literal_author_feedback_v1',candidate_sha256=current,
        feedback_sha256='c'*64,previous_manifest_sha256='b'*64,test_path=cfg['test_path'],expected=cfg['expected'],
        reports={name:dict(initial_requests=1,poll_requests=2,stale_guard_text='Newest matching: #11' if name=='guarded' else 'Newest matching: #4')
            for name in ('guarded','unguarded')},capture=dict(field='poll_requests',literal='NODE_HARNESS',literal_line=177,
                assignment='snap.poll_requests = latestCount();'),failed_fields=['poll_requests'],checks_passed=False,
        outside_literal_bytes_preserved=True,candidate_bytes_stable_during_measurement=True,
        evidence_scope='current_file_fixed_diagnostic_only',non_target_verification='not_performed_in_feedback',
        model_calls=0,next_action='fixture only',request_id=cfg['request_id'],task_id=cfg['task_id'],
        validation_job_key='d'*64,validation_contract_sha256='e'*64,**{k:False for k in wire.FALSE_FLAGS})
    result=Mock();result.status=200;result.read.return_value=json.dumps(value).encode()
    result.__enter__=Mock(return_value=result);result.__exit__=Mock(return_value=False);return result
opener=Mock();opener.open.side_effect=response
client.urllib.request.build_opener=lambda *args:opener
from tools.registry import registry,discover_builtin_tools
discover_builtin_tools()
from acp_adapter.tools import _format_edit_result
def invoke(name,args):return json.loads(registry.dispatch(name,args))
edit=dict(path=str(target),old_string='const value = 1;',new_string='const value = 2;')
assert invoke('patch',edit).get('error') and target.read_bytes()==source
for name,args in (('terminal',dict(command='id')),('write_file',dict(path=str(target),content='bad'))):
    assert invoke(name,args).get('error')
    entry=registry.get_entry(name)
    if entry:assert json.loads(entry.handler(args)).get('error')
assert target.read_bytes()==source and not calls
read=invoke('read_file',dict(path=str(target),offset=1,limit=200));assert not read.get('error')
invalid=dict(path=str(target),old_string='self.assertEqual(1, 2)',new_string='self.assertTrue(True)')
assert invoke('patch',invalid).get('error') and target.read_bytes()==source
entry=registry.get_entry('patch')
assert json.loads(entry.handler(invalid)).get('error') and target.read_bytes()==source
result=invoke('patch',edit)
assert result.get('success') is True and target.read_bytes()==source.replace(b'const value = 1;',b'const value = 2;'),json.dumps(
    dict(result={k:result.get(k) for k in ('success','error')},read_keys=sorted(read),
        observed_pages={k:len(v) for k,v in client.PAGES.items()}))
assert result['_author_feedback_v1']['checks_passed'] is False and len(calls)==1
formatted=json.loads(_format_edit_result('patch',json.dumps(result),edit))
assert formatted['changed'] is True and formatted['author_feedback']['checks_passed'] is False
assert 'BEFORE snap.poll_requests' in formatted['author_feedback']['instruction']
assert cfg['capability'] not in json.dumps(formatted)
saved=target.read_bytes();again=dict(edit,old_string='const value = 2;',new_string='const value = 3;')
assert invoke('patch',again).get('error') and target.read_bytes()==saved
virtual=invoke('read_file',dict(path=client.VIRTUAL_PATH,offset=1,limit=200))
assert json.loads(virtual['content'])['candidate_sha256']==hashlib.sha256(saved).hexdigest()
assert len(calls)==2
os.environ['DELIVERY_EXECUTION_MODE']='planning'
assert invoke('patch',again).get('error') and target.read_bytes()==saved
print(json.dumps(dict(operation='author_feedback_real_registry_canary_v1',status='passed',uid=os.getuid(),network='none',
    source_sha256={name:hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in
        (('client',client),('policy',review_tool_policy),('wire',wire),('formatter',patch_receipt_contract))},
    real_registry=True,direct_handler_fenced=True,readless_patch_denied=True,assertion_edit_denied=True,
    shell_and_generic_write_denied=True,literal_edit_preserves_outside_bytes=True,
    current_hash_returned=True,feedback_visible_in_acp_formatter=True,fresh_read_required_after_patch=True,
    virtual_feedback_observation=True,wrong_mode_denied=True,controller_transport_stubbed=True,
    model_calls=0,native_execution=False,full_regression_suite_executed=False,delivery_approval=False)))
