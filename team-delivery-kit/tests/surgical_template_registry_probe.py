"""Real installed registry and direct-handler canary; zero model calls."""
import hashlib,json,os,sys
from pathlib import Path

source=b'import unittest\nCONTROL="unchanged"\nNODE_HARNESS_TEMPLATE=r"""\nconst path = %(source_path)s;\nasync function drive(){\n const before="pending";\n const after_ok = {text: before};\n}\n"""\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n'
target=Path('/workspace/test_template_canary.py');target.write_bytes(source);target.chmod(0o666)
cfg=dict(path=str(target),expected_sha256=hashlib.sha256(source).hexdigest(),protocol='typed_template_v5')
os.environ.update(DELIVERY_EXECUTION_MODE='implementation',DELIVERY_SURGICAL_TEST_JSON=json.dumps(cfg),HERMES_HOME='/tmp/hermes-template-canary')
os.setgroups([]);os.setgid(10000);os.setuid(10000);sys.path.insert(0,'/opt/hermes')
from tools.registry import registry,discover_builtin_tools
discover_builtin_tools()
from tools.surgical_tool import handle
from model_tools import get_tool_definitions
from acp_adapter.session import _expand_acp_enabled_toolsets
from model_proxy import validate_request,MODEL
from artifact_response_contract import validate,ArtifactResponseRejected

def invoke(name,args):return json.loads(registry.dispatch(name,args))
default=get_tool_definitions(quiet_mode=True)
acp=get_tool_definitions(enabled_toolsets=_expand_acp_enabled_toolsets(['hermes-acp']),quiet_mode=True)
for definitions in (default,acp):
 tool=next(t['function'] for t in definitions if t['function']['name']=='surgical_test_edit')
 assert set(tool['parameters']['properties'])=={'path','expected_sha256','edits'}
args=dict(path=str(target),expected_sha256=cfg['expected_sha256'],edits=[dict(old='const after_ok = {text: before};',new='const after_ok = {text: "terminal"};')])
assert invoke('surgical_test_edit',args).get('error')
for name,request in [('write_file',dict(path=str(target),content='bad')),('patch',dict(path=str(target),old_string='pending',new_string='bad')),
                     ('terminal',dict(command='true')),('python',dict(code='pass'))]:
 assert invoke(name,request).get('error')
assert json.loads(handle(args)).get('error') and target.read_bytes()==source
invoke('read_file',dict(path=str(target),offset=1,limit=100))
for old,new in [('CONTROL="unchanged"','CONTROL="changed"'),('self.assertTrue(True)','pass'),
                ('const after_ok = {text: before};','const after_ok = {text: ;')]:
 bad={**args,'edits':[dict(old=old,new=new)]}
 assert invoke('surgical_test_edit',bad).get('error') and target.read_bytes()==source
body=dict(model=MODEL,messages=[dict(role='user',content='DELIVERY_TEST_ARTIFACT_V1:'+str(target)+'\nDELIVERY_TEST_SOURCE_V1:/workspace/app.py\nDELIVERY_SURGICAL_TEST_V5:'+str(target)+':'+cfg['expected_sha256']+'\n')],
          tools=[t for t in acp if t['function']['name'] in ('read_file','write_file','surgical_test_edit')])
for i,path in enumerate(['/workspace/app.py',str(target)]):
 body['messages'] += [dict(role='assistant',tool_calls=[dict(id=str(i),function=dict(name='read_file',arguments=json.dumps(dict(path=path,offset=1,limit=100))))]),
                      dict(role='tool',tool_call_id=str(i),content=json.dumps(dict(content='1|source',total_lines=1)))]
selected=validate_request(body);assert selected['tool_choice']['function']['name']=='surgical_test_edit'
def response(arguments):return json.dumps(dict(choices=[dict(message=dict(tool_calls=[dict(function=dict(name='surgical_test_edit',arguments=json.dumps(arguments)))]),finish_reason='tool_calls')])).encode()
validate(selected,response(args),'application/json')
try:validate(selected,response({**args,'template_name':'OTHER'}),'application/json')
except ArtifactResponseRejected:pass
else:raise AssertionError('ungranted template selector accepted')
result=invoke('surgical_test_edit',args)
assert result.get('verified') and result.get('test_bodies_preserved') and result.get('delivery_approval') is False
changed=target.read_bytes();assert invoke('surgical_test_edit',args).get('error') and target.read_bytes()==changed
os.environ.pop('DELIVERY_SURGICAL_TEST_JSON');assert json.loads(handle(args)).get('error')
print(json.dumps(dict(schema='surgical-template-registry-probe-v5',status='passed',model_calls=0,
 actual_registry=True,actual_default_selection=True,actual_acp_selection=True,full_proxy_request_validation=True,
 readless_edit_denied=True,generic_write_and_terminal_denied=True,python_denied=True,direct_handler_fenced=True,
 outside_template_change_preserves_bytes=True,test_weakening_preserves_bytes=True,invalid_syntax_preserves_bytes=True,
 stale_edit_denied=True,template_selector_denied=True,fixed_node_check=True,uid=os.getuid(),network='none',
 credentials_absent=not Path('/secret').exists() and not Path('/var/run/docker.sock').exists(),delivery_approval=False)))
