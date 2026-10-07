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
target_read=invoke('read_file',dict(path=str(target),offset=1,limit=100))
for old,new in [('CONTROL="unchanged"','CONTROL="changed"'),('self.assertTrue(True)','pass'),
                ('const after_ok = {text: before};','const after_ok = {text: ;')]:
 bad={**args,'edits':[dict(old=old,new=new)]}
 assert invoke('surgical_test_edit',bad).get('error') and target.read_bytes()==source
body=dict(model=MODEL,messages=[dict(role='user',content='DELIVERY_TEST_ARTIFACT_V1:'+str(target)+'\nDELIVERY_TEST_SOURCE_V1:/workspace/app.py\nDELIVERY_SURGICAL_TEST_V5:'+str(target)+':'+cfg['expected_sha256']+'\n')],
          tools=[t for t in acp if t['function']['name'] in ('read_file','write_file','surgical_test_edit')])
# Exercise the installed prompt boundary with the actual native.task_binding
# function, not a hand-written full task record. Only native I/O is a fixture.
import broker as controller,native
from unittest.mock import patch
controller.STATE=Path('/tmp/template-binding-probe');controller.STATE.mkdir()
issue='00000000-0000-0000-0000-000000000001';actor='00000000-0000-0000-0000-000000000002';taskid='00000000-0000-0000-0000-000000000003'
settings=dict(workspace_id='00000000-0000-0000-0000-000000000004',agents={actor:'implementation'})
(controller.STATE/'native.json').write_text(json.dumps(settings))
task=dict(id=taskid,agent_id=actor,issue_id=issue,wakeup_id='fixture-wake',status='running',handoff_note='Bounded template correction.')
route=dict(enabled=True,author=actor,test_first=True,test_first_files=['test_template_canary.py'])
state=dict(executor=dict(status='waiting',wakeup_id=task['wakeup_id'],worker_image='sha256:'+'a'*64,surgical=cfg))
with controller.db() as con:
 con.execute('CREATE TABLE delivery_routes(issue_id TEXT PRIMARY KEY,config TEXT)')
 con.execute('INSERT INTO delivery_routes VALUES (?,?)',(issue,json.dumps(route)))
 con.execute('CREATE TABLE issue_editables(issue_id TEXT,path TEXT)')
 con.executemany('INSERT INTO issue_editables VALUES (?,?)',[(issue,str(target)),(issue,'/workspace/app.py')])
 con.execute('CREATE TABLE test_first_red(issue_id TEXT,task_id TEXT,receipt TEXT)')
 con.execute('CREATE TABLE calibration_failure_plans(source_task TEXT,config TEXT,state TEXT)')
 con.execute('INSERT INTO calibration_failure_plans VALUES (?,?,?)',('previous',json.dumps(dict(issue_id=issue,source_task='previous',author=actor)),json.dumps(state)))
 con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT)')
 con.execute('INSERT INTO native_bindings VALUES (?,?,?)',('fixture-request',taskid,actor))
import template_author_executor
os.environ['BROKER_TEST_ARTIFACT_GATE']='1'
with patch.object(native,'task_record',return_value=task):
 binding=native.task_binding(settings,taskid,actor)
 assert 'status' not in binding and binding['task_id']==taskid
 grant=template_author_executor.worker_config(controller,'fixture-request',issue)
 assert grant['surgical']==cfg
 frame=controller.native_task_prompt(dict(method='session/prompt',params=dict(prompt=[])),'implementation',dict(id=issue,title='Fixture harness',description='Preserve all tests.'),binding)
 text=frame['params']['prompt'][0]['text']
 assert 'DELIVERY_SURGICAL_TEST_V5:'+str(target)+':'+cfg['expected_sha256'] in text
 body['messages'][0]['content']=text
Path('/workspace/app.py').write_text('VALUE = 1\n')
for i,path in enumerate(['/workspace/app.py',str(target)]):
 read=target_read if path==str(target) else invoke('read_file',dict(path=path,offset=1,limit=100))
 assert read.get('content') and read.get('total_lines'),{'keys':list(read),'error':read.get('error'),'path':path}
 body['messages'] += [dict(role='assistant',tool_calls=[dict(id=str(i),function=dict(name='read_file',arguments=json.dumps(dict(path=path,offset=1,limit=100))))]),
                      dict(role='tool',tool_call_id=str(i),content=json.dumps(read))]
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
 actual_registry=True,actual_default_selection=True,actual_acp_selection=True,full_proxy_request_validation=True,native_binding_prompt=True,
 readless_edit_denied=True,generic_write_and_terminal_denied=True,python_denied=True,direct_handler_fenced=True,
 outside_template_change_preserves_bytes=True,test_weakening_preserves_bytes=True,invalid_syntax_preserves_bytes=True,
 stale_edit_denied=True,template_selector_denied=True,fixed_node_check=True,uid=os.getuid(),network='none',
 credentials_absent=not Path('/secret').exists() and not Path('/var/run/docker.sock').exists(),delivery_approval=False)))
