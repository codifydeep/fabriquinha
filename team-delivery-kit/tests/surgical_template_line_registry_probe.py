"""Real installed V6 registry, native binding and proxy canary; no model calls."""
import hashlib,json,os,sys
from pathlib import Path

source=b'import unittest\nCONTROL="unchanged"\nNODE_HARNESS_TEMPLATE=r"""\nconst path = %(source_path)s;\nasync function drive(){\n const before="pending";\n const after_ok = {text: before};\n}\n"""\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n'
target=Path('/workspace/test_template_lines.py');target.write_bytes(source);target.chmod(0o666)
cfg=dict(path=str(target),expected_sha256=hashlib.sha256(source).hexdigest(),protocol='typed_template_lines_v6')
os.environ.update(DELIVERY_EXECUTION_MODE='implementation',DELIVERY_SURGICAL_TEST_JSON=json.dumps(cfg),HERMES_HOME='/tmp/hermes-template-lines')
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
 assert set(tool['parameters']['properties']['edits']['items']['required'])=={'start_line','end_line','new'}
args=dict(path=str(target),expected_sha256=cfg['expected_sha256'],edits=[dict(start_line=7,end_line=7,new=' const after_ok = {text: "terminal"};\n')])
assert invoke('surgical_test_edit',args).get('error')
for name,request in [('write_file',dict(path=str(target),content='bad')),('patch',dict(path=str(target),old_string='pending',new_string='bad')),
                     ('terminal',dict(command='true')),('python',dict(code='pass'))]:
 assert invoke(name,request).get('error')
assert json.loads(handle(args)).get('error') and target.read_bytes()==source
target_read=invoke('read_file',dict(path=str(target),offset=1,limit=100))
for edits in ([dict(start_line=2,end_line=2,new='CONTROL="changed"\n')],
              [dict(start_line=11,end_line=11,new=' def test_ok(self): pass\n')],
              [dict(start_line=7,end_line=7,new=' const after_ok = ;\n')],
              [dict(start_line=6,end_line=7,new=''),dict(start_line=7,end_line=8,new='')]):
 assert invoke('surgical_test_edit',{**args,'edits':edits}).get('error') and target.read_bytes()==source
assert invoke('surgical_test_edit',{**args,'template_name':'OTHER'}).get('error')
body=dict(model=MODEL,messages=[],tools=[t for t in acp if t['function']['name'] in ('read_file','write_file','surgical_test_edit')])
import broker as controller,native,template_author_executor
from unittest.mock import patch
controller.STATE=Path('/tmp/template-line-binding');controller.STATE.mkdir()
issue='00000000-0000-0000-0000-000000000001';actor='00000000-0000-0000-0000-000000000002';taskid='00000000-0000-0000-0000-000000000003'
settings=dict(workspace_id='00000000-0000-0000-0000-000000000004',agents={actor:'implementation'})
(controller.STATE/'native.json').write_text(json.dumps(settings))
task=dict(id=taskid,agent_id=actor,issue_id=issue,wakeup_id='fixture-wake',status='running',handoff_note='Bounded template line correction.')
route=dict(enabled=True,author=actor,test_first=True,test_first_files=['test_template_lines.py'])
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
os.environ['BROKER_TEST_ARTIFACT_GATE']='1'
with patch.object(native,'task_record',return_value=task):
 binding=native.task_binding(settings,taskid,actor)
 assert 'status' not in binding and binding['task_id']==taskid
 assert template_author_executor.worker_config(controller,'fixture-request',issue)['surgical']==cfg
 frame=controller.native_task_prompt(dict(method='session/prompt',params=dict(prompt=[])),'implementation',dict(id=issue,title='Fixture harness',description='Preserve all tests.'),binding)
 text=frame['params']['prompt'][0]['text']
 assert 'DELIVERY_SURGICAL_TEST_V6:'+str(target)+':'+cfg['expected_sha256'] in text
 body['messages']=[dict(role='user',content=text)]
Path('/workspace/app.py').write_text('VALUE = 1\n')
for i,path in enumerate(['/workspace/app.py',str(target)]):
 read=target_read if path==str(target) else invoke('read_file',dict(path=path,offset=1,limit=100))
 assert read.get('content') and read.get('total_lines')
 body['messages'] += [dict(role='assistant',tool_calls=[dict(id=str(i),function=dict(name='read_file',arguments=json.dumps(dict(path=path,offset=1,limit=100))))]),dict(role='tool',tool_call_id=str(i),content=json.dumps(read))]
selected=validate_request(body);assert selected['tool_choice']['function']['name']=='surgical_test_edit'
def response(arguments):return json.dumps(dict(choices=[dict(message=dict(tool_calls=[dict(function=dict(name='surgical_test_edit',arguments=json.dumps(arguments)))]),finish_reason='tool_calls')])).encode()
validate(selected,response(args),'application/json')
for bad in ({**args,'template_name':'OTHER'},{**args,'edits':[dict(old='before',new='terminal')]}):
 try:validate(selected,response(bad),'application/json')
 except ArtifactResponseRejected:pass
 else:raise AssertionError('ungranted template selector or legacy payload accepted')
result=invoke('surgical_test_edit',args)
assert result.get('verified') and result.get('test_bodies_preserved') and result.get('delivery_approval') is False
changed=target.read_bytes();assert invoke('surgical_test_edit',args).get('error') and target.read_bytes()==changed
os.environ.pop('DELIVERY_SURGICAL_TEST_JSON');assert json.loads(handle(args)).get('error')
proof=dict(schema='surgical-template-line-registry-probe-v6',status='passed',model_calls=0,uid=os.getuid(),network='none',delivery_approval=False)
for flag in ('actual_registry','actual_default_selection','actual_acp_selection','full_proxy_request_validation','native_binding_prompt','readless_edit_denied','generic_write_and_terminal_denied','python_denied','direct_handler_fenced','outside_template_change_preserves_bytes','test_weakening_preserves_bytes','invalid_syntax_preserves_bytes','stale_edit_denied','template_selector_denied','fixed_node_check','line_range_atomic_rejection','legacy_payload_denied'):proof[flag]=True
proof['credentials_absent']=not Path('/secret').exists() and not Path('/var/run/docker.sock').exists()
print(json.dumps(proof))
