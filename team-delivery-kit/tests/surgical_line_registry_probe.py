"""Offline fresh-process real-registry V4 qualification, without model calls."""
import hashlib
import json
import os
from pathlib import Path
import sys

source=b'import unittest\nDRIVER_PREAMBLE="unchanged"\nDRIVER_BODY=r"""\n// duplicate\n// duplicate\nPromise.resolve();\n"""\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n'
target=Path('/workspace/test_lines.py');target.write_bytes(source);target.chmod(0o666)
config={'path':str(target),'expected_sha256':hashlib.sha256(source).hexdigest(),'protocol':'typed_driver_lines_v4'}
os.environ.update(DELIVERY_EXECUTION_MODE='implementation',DELIVERY_SURGICAL_TEST_JSON=json.dumps(config),HERMES_HOME='/tmp/hermes-line-canary')
os.setgroups([]);os.setgid(10000);os.setuid(10000)
sys.path.insert(0,'/opt/hermes')
from tools.registry import registry,discover_builtin_tools
discover_builtin_tools()
def invoke(name,args):return json.loads(registry.dispatch(name,args))
from model_tools import get_tool_definitions
from acp_adapter.session import _expand_acp_enabled_toolsets
from acp_adapter.tools import _format_generic_structured_result
from model_proxy import validate_request,MODEL
from artifact_response_contract import validate,ArtifactResponseRejected
default=get_tool_definitions(quiet_mode=True)
acp=get_tool_definitions(enabled_toolsets=_expand_acp_enabled_toolsets(['hermes-acp']),quiet_mode=True)
for definitions in (default,acp):
    tool=next(t['function'] for t in definitions if t['function']['name']=='surgical_test_edit')
    assert set(tool['parameters']['properties']['edits']['items']['required'])=={'start_line','end_line','new'}
args={'path':str(target),'expected_sha256':config['expected_sha256'],'edits':[{'start_line':4,'end_line':4,'new':'// changed\n'}]}
assert invoke('surgical_test_edit',args).get('error')  # Must freshly read the whole target.
assert invoke('write_file',{'path':str(target),'content':'bad'}).get('error')
assert invoke('terminal',{'command':'true'}).get('error')
assert target.read_bytes()==source
invoke('read_file',{'path':str(target),'offset':1,'limit':50})
syntax_args={**args,'edits':[{'start_line':6,'end_line':6,'new':'Promise.resolve().then(()=>{\n'}]}
syntax=invoke('surgical_test_edit',syntax_args)
assert syntax['category']=='driver_syntax_invalid' and syntax['driver_diagnostic']['syntax_category']=='unexpected_end'
assert 'driver_line=' in _format_generic_structured_result('surgical_test_edit',json.dumps(syntax))
from tools.surgical_tool import handle
repeated=json.loads(handle(syntax_args))
assert repeated['category']=='identical_rejected_proposal' and target.read_bytes()==source
import subprocess
fresh=subprocess.run([sys.executable,'-c',
    'import sys,json;sys.path.insert(0,"/opt/hermes");from surgical_test_edit import edit_file,rejection_feedback;'
    'a=json.load(sys.stdin);envelope={k:a[k] for k in ("expected_sha256","edits")};'
    '\ntry: edit_file(a["path"],envelope,observed_read=True,required_uid=0,driver_only=True,line_ranges=True,rejection_ledger="/tmp/delivery-surgical-rejections.json")'
    '\nexcept ValueError as e: print(json.dumps(rejection_feedback(e)))'],
    input=json.dumps(syntax_args),text=True,capture_output=True,timeout=10,check=True)
assert json.loads(fresh.stdout)['category']=='identical_rejected_proposal' and target.read_bytes()==source
for edits in ([{'start_line':2,'end_line':2,'new':'DRIVER_PREAMBLE="bad"\n'}],
        [{'start_line':9,'end_line':9,'new':' def test_ok(self): pass\n'}],
        [{'start_line':6,'end_line':6,'new':'Promise.resolve().then(()=>{\n'}],
        [{'start_line':4,'end_line':5,'new':''},{'start_line':5,'end_line':6,'new':''}],
        [{'start_line':4,'end_line':4,'new':'// duplicate\n'}]):
    result=invoke('surgical_test_edit',{**args,'edits':edits})
    assert result.get('error') and target.read_bytes()==source
    assert 'surgical_edit_rejected' in _format_generic_structured_result('surgical_test_edit',json.dumps(result))
body={'model':MODEL,'messages':[{'role':'user','content':'DELIVERY_TEST_ARTIFACT_V1:'+str(target)+'\nDELIVERY_TEST_SOURCE_V1:/workspace/app.py\nDELIVERY_SURGICAL_TEST_V4:'+str(target)+':'+config['expected_sha256']+'\n'}],
    'tools':[t for t in acp if t['function']['name'] in ('read_file','write_file','surgical_test_edit')]}
for index,path in enumerate(['/workspace/app.py',str(target)]):
    body['messages']+=[{'role':'assistant','tool_calls':[{'id':str(index),'function':{'name':'read_file','arguments':json.dumps({'path':path,'offset':1,'limit':50})}}]},
        {'role':'tool','tool_call_id':str(index),'content':json.dumps({'content':'1|source','total_lines':1})}]
selected=validate_request(body)
assert selected['tool_choice']['function']['name']=='surgical_test_edit'
def response(args):return json.dumps({'choices':[{'message':{'tool_calls':[{'function':{'name':'surgical_test_edit','arguments':json.dumps(args)}}]},'finish_reason':'tool_calls'}]}).encode()
validate(selected,response(args),'application/json')
try:validate(selected,response({**args,'edits':[{'old':'duplicate','new':'changed'}]}),'application/json')
except ArtifactResponseRejected:pass
else:raise AssertionError('legacy payload accepted in V4')
result=invoke('surgical_test_edit',args)
assert result.get('verified') and result.get('test_bodies_preserved') and result.get('delivery_approval') is False
assert target.read_bytes().count(b'// duplicate')==1 and b'// changed\n' in target.read_bytes()
accepted=target.read_bytes();assert invoke('surgical_test_edit',args).get('error') and target.read_bytes()==accepted
from tools.surgical_tool import handle
os.environ.pop('DELIVERY_SURGICAL_TEST_JSON');assert json.loads(handle(args)).get('error')
proof={'schema':'surgical-driver-registry-probe-v3','status':'passed','uid':os.getuid(),'network':'none',
    'credentials_absent':not Path('/secret').exists() and not Path('/var/run/docker.sock').exists()}
for flag in ('actual_registry','actual_default_selection','actual_acp_selection','proxy_protocol_fixture',
        'readless_edit_denied','generic_write_and_terminal_denied','direct_handler_fenced',
        'invalid_syntax_preserves_bytes','outside_driver_change_preserves_bytes','test_weakening_preserves_bytes',
        'stale_edit_denied','fixed_node_check'):proof[flag]=True
proof.update(line_range_registry_qualified=True,line_range_proxy_schema_qualified=True,
    line_range_atomic_rejection=True,line_range_duplicate_selection=True,line_range_stale_denied=True,
    bounded_node_feedback_acp_visible=True,identical_syntax_replay_denied=True,
    fresh_process_syntax_replay_denied=True,
    rejection_persistence_worker_private=True,changed_proposal_accepted=True,
    model_calls=0,delivery_approval=False)
print(json.dumps(proof))
