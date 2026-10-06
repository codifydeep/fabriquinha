"""Offline, root-owned tmpfs fixture; no product delivery or live model calls."""
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,'/opt/hermes')
source=b'import pytest\n\ndef test_value():\n    assert 1 == 2\n'
target=Path('/workspace/test_probe.py')
target.write_bytes(source);target.chmod(0o666)
digest=hashlib.sha256(source).hexdigest()
config={'path':str(target),'expected_sha256':digest,'protocol':'typed_v2'}
os.environ.update(DELIVERY_EXECUTION_MODE='implementation',DELIVERY_SURGICAL_TEST_JSON=json.dumps(config))
os.setgroups([]);os.setgid(10000);os.setuid(10000)
from tools.registry import registry,discover_builtin_tools
discover_builtin_tools()
definitions=registry.get_definitions({'read_file','write_file','surgical_test_edit'},quiet=True)
assert {t['function']['name'] for t in definitions}=={'read_file','write_file','surgical_test_edit'}
from model_tools import get_tool_definitions
actual=get_tool_definitions(quiet_mode=True)
assert 'surgical_test_edit' in {t['function']['name'] for t in actual}
from acp_adapter.session import _expand_acp_enabled_toolsets
acp=get_tool_definitions(enabled_toolsets=_expand_acp_enabled_toolsets(['hermes-acp']),quiet_mode=True)
assert 'surgical_test_edit' in {t['function']['name'] for t in acp}
definitions=[t for t in acp if t['function']['name'] in ('read_file','write_file','surgical_test_edit')]
args={'path':str(target),'expected_sha256':digest,'edits':[
    {'old':'import pytest','new':'import unittest'},
    {'old':'def test_value():\n    assert 1 == 2','new':'class Probe(unittest.TestCase):\n    def test_value(self):\n        assert 1 == 2'}]}
def invoke(name,value):return json.loads(registry.dispatch(name,value))
assert invoke('surgical_test_edit',args).get('error')
assert invoke('write_file',{'path':str(target),'content':'bad'}).get('error')
assert invoke('terminal',{'command':'true'}).get('error')
read=invoke('read_file',{'path':str(target),'offset':1,'limit':50})
assert isinstance(read.get('content'),str) and read.get('total_lines')==4
bad={**args,'edits':[args['edits'][0]]}
error=invoke('surgical_test_edit',bad)
assert error['category']=='unittest_discovery_required' and error['next_operation']=='wrap_in_unittest_testcase'
assert target.read_bytes()==source
from acp_adapter.tools import _format_generic_structured_result
visible=_format_generic_structured_result('surgical_test_edit',json.dumps(error))
assert 'unittest_discovery_required' in visible and 'wrap_in_unittest_testcase' in visible
from review_tool_policy import controlled
assert json.loads(controlled('surgical_test_edit',{**args,'edits':[{'old':'def test_value():','new':'def helper():'}]}))['category']=='test_methods_missing'
assert target.read_bytes()==source
from model_proxy import validate_request,MODEL
from artifact_response_contract import validate,ArtifactResponseRejected
body={'messages':[{'role':'user','content':
    'DELIVERY_TEST_ARTIFACT_V1:'+str(target)+'\nDELIVERY_TEST_SOURCE_V1:/workspace/app.py\n'
    'DELIVERY_SURGICAL_TEST_V2:'+str(target)+':'+digest+'\n'}], 'tools':definitions}
for index,path in enumerate(['/workspace/app.py',str(target)]):
    body['messages'] += [{'role':'assistant','tool_calls':[{'id':str(index),'function':{
        'name':'read_file','arguments':json.dumps({'path':path,'offset':1,'limit':50})}}]},
        {'role':'tool','tool_call_id':str(index),'content':json.dumps({'content':'1|source','total_lines':1})}]
body['model']=MODEL
body=validate_request(body)
assert body['tool_choice']['function']['name']=='surgical_test_edit'
def response(value):return json.dumps({'choices':[{'message':{'tool_calls':[{'function':{
    'name':'surgical_test_edit','arguments':json.dumps(value)}}]},'finish_reason':'tool_calls'}]}).encode()
validate(body,response(args),'application/json')
for changes,category in [({'path':'/workspace/app.py'},'surgical_path_mismatch'),
                        ({'expected_sha256':'0'*64},'surgical_hash_mismatch'),
                        ({'edits':[]},'surgical_edits_invalid')]:
    try:validate(body,response({**args,**changes}),'application/json')
    except ArtifactResponseRejected as error:assert error.category==category
    else:raise AssertionError('invalid candidate accepted')
result=invoke('surgical_test_edit',args)
assert result.get('verified') and result.get('test_bodies_preserved') and result.get('delivery_approval') is False
assert invoke('surgical_test_edit',args).get('error')
from tools.surgical_tool import handle
os.environ.pop('DELIVERY_SURGICAL_TEST_JSON')
assert json.loads(handle(args)).get('error')
print(json.dumps({'schema':'surgical-typed-registry-probe-v2','status':'passed',
    'actual_registry':True,'actual_default_selection':True,'actual_acp_selection':True,
    'full_proxy_request_validation':True,'response_gate_qualified':True,'readless_edit_denied':True,
    'legacy_write_denied':True,'stale_edit_denied':True,'preserved_bodies':True,
    'structured_feedback_visible':True,'invalid_candidate_preserved':True,
    'network':'none','credentials_absent':not Path('/secret').exists() and not Path('/var/run/docker.sock').exists(),
    'delivery_approval':False,'fixture_removed':False}))
