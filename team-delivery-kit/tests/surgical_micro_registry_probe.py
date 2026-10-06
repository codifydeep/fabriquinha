"""Actual native registry/direct handler qualification; no model or product run."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,'/source/tests')
try:from test_c10_micro_drain import fixture
except ImportError:from micro_fixture import fixture
import c10_micro_drain as micro
source=fixture();target=Path('/workspace/test_micro.py');target.write_bytes(source);target.chmod(0o666)
config={'path':str(target),'expected_sha256':hashlib.sha256(source).hexdigest(),
    'protocol':'typed_driver_lines_v4','drain_resolver':'resolveNewest'}
os.environ.update(DELIVERY_EXECUTION_MODE='implementation',DELIVERY_SURGICAL_TEST_JSON=json.dumps(config),HERMES_HOME='/tmp/micro-probe')
os.setgroups([]);os.setgid(10000);os.setuid(10000);sys.path.insert(0,'/opt/hermes')
from tools.registry import registry,discover_builtin_tools
discover_builtin_tools()
from tools.surgical_tool import handle,schema_override
schema=schema_override();props=schema['parameters']['properties']['edits']['items']['properties']
assert props['start_line']['enum']==[551] and props['end_line']['enum']==[551]
assert props['new']['enum']==[micro.recipe('resolveNewest')]
def invoke(name,args):return json.loads(registry.dispatch(name,args))
base={'path':str(target),'expected_sha256':config['expected_sha256']}
valid={**base,'edits':[{'start_line':551,'end_line':551,'new':micro.recipe('resolveNewest')}]}
assert invoke('surgical_test_edit',valid).get('error') and target.read_bytes()==source
for offset in (1,201,401,601):invoke('read_file',{'path':str(target),'offset':offset,'limit':200})
bad={**base,'edits':[{'start_line':551,'end_line':551,'new':'// describe the operation\n'}]}
assert invoke('surgical_test_edit',bad)['category']=='micro_recipe_required' and target.read_bytes()==source
outside={**base,'edits':[{'start_line':550,'end_line':551,'new':micro.recipe('resolveNewest')}]}
assert json.loads(handle(outside))['category']=='micro_recipe_required' and target.read_bytes()==source
assert invoke('terminal',{'command':'true'}).get('error')
assert invoke('write_file',{'path':str(target),'content':'bad'}).get('error')
# Actual installed proxy argument compiler must retain the same narrow schema.
from surgical_test_edit import marker_config,typed_schema
marker={'messages':[{'role':'user','content':'DELIVERY_SURGICAL_TEST_V4:'+str(target)+':'+config['expected_sha256']+'\nDELIVERY_STATUS_DRAIN_V1:resolveNewest'}]}
assert typed_schema(marker_config(marker))==schema
result=invoke('surgical_test_edit',valid)
assert result.get('verified') and result.get('test_bodies_preserved') and result.get('delivery_approval') is False
accepted=target.read_bytes();assert micro.verify(source,accepted,'resolveNewest')
assert invoke('surgical_test_edit',valid).get('error') and target.read_bytes()==accepted
print(json.dumps({'schema':'surgical-micro-drain-probe-v1','status':'passed','uid':os.getuid(),
    'network':'none','model_calls':0,'readless_edit_denied':True,'comment_before_write_denied':True,
    'outside_before_write_denied':True,'direct_handler_fenced':True,'generic_write_and_terminal_denied':True,
    'exact_recipe_applied':True,'all_other_bytes_preserved':True,'stale_edit_denied':True,
    'proxy_marker_schema_preserved':True,'credentials_absent':not Path('/var/run/docker.sock').exists()
    and not Path('/secret').exists(),'delivery_approval':False}))
