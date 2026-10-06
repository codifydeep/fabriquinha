"""Real isolated handler/registry qualification; no model or product execution."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,'/source/tests')
try:from test_c10_status_atomic import COMPLETE
except ImportError:from status_fixture import COMPLETE
lines=['// frozen\n']*679
lines[0:4]=['import unittest\n','DRIVER_PREAMBLE="frozen"\n','DRIVER_BODY=r"""\n','function drive(){\n']
lines[533:537]=['// C10STATUS - placeholder checkpoint\n','return flush().then(function(){\n','});\n','}\n']
lines[676:679]=['"""\n','class T(unittest.TestCase):\n',' def test_ok(self): self.assertTrue(True)\n']
source=''.join(lines).encode();target=Path('/workspace/test_status.py');target.write_bytes(source);target.chmod(0o666)
config={'path':str(target),'expected_sha256':hashlib.sha256(source).hexdigest(),
    'protocol':'typed_driver_lines_v4','atomic_contract':'c10-status-observations-v1'}
os.environ.update(DELIVERY_EXECUTION_MODE='implementation',DELIVERY_SURGICAL_TEST_JSON=json.dumps(config),HERMES_HOME='/tmp/status-probe')
os.setgroups([]);os.setgid(10000);os.setuid(10000);sys.path.insert(0,'/opt/hermes')
from tools.registry import registry,discover_builtin_tools
discover_builtin_tools()
from tools.surgical_tool import handle,schema_override
schema=schema_override();edits=schema['parameters']['properties']['edits']
assert edits['maxItems']==1 and edits['items']['properties']['start_line']['enum']==[534]
assert edits['items']['properties']['end_line']['enum']==[536]
def invoke(name,args):return json.loads(registry.dispatch(name,args))
base={'path':str(target),'expected_sha256':config['expected_sha256']}
for offset in (1,201,401,601):invoke('read_file',{'path':str(target),'offset':offset,'limit':200})
partial={**base,'edits':[{'start_line':i,'end_line':i,'new':'click(x);'} for i in (534,535,536)]}
assert invoke('surgical_test_edit',partial)['category']=='status_atomic_shape_required'
assert json.loads(handle(partial))['category']=='identical_rejected_proposal'
assert target.read_bytes()==source
incomplete={**base,'edits':[{'start_line':534,'end_line':536,'new':"click(byId['filter-open']);\nclick(byId['filter-completed']);\n"}]}
assert invoke('surgical_test_edit',incomplete)['category']=='status_observations_incomplete'
assert target.read_bytes()==source
import subprocess
fresh=subprocess.run([sys.executable,'-c',
    'import sys,json;sys.path.insert(0,"/opt/hermes");from surgical_test_edit import edit_file,rejection_feedback;'
    'a=json.load(sys.stdin);envelope={k:a[k] for k in ("expected_sha256","edits")};'
    '\ntry: edit_file(a["path"],envelope,observed_read=True,required_uid=0,driver_only=True,line_ranges=True,atomic_status=True,rejection_ledger="/tmp/delivery-surgical-rejections.json")'
    '\nexcept ValueError as e: print(json.dumps(rejection_feedback(e)))'],
    input=json.dumps(incomplete),text=True,capture_output=True,timeout=10,check=True)
assert json.loads(fresh.stdout)['category']=='identical_rejected_proposal' and target.read_bytes()==source
assert invoke('terminal',{'command':'true'}).get('error')
assert invoke('write_file',{'path':str(target),'content':'bad'}).get('error')
complete={**base,'edits':[{'start_line':534,'end_line':536,'new':COMPLETE}]}
result=invoke('surgical_test_edit',complete)
assert result.get('verified') and result.get('test_bodies_preserved') and result.get('delivery_approval') is False
accepted=target.read_bytes();assert accepted!=source
assert accepted.splitlines()[:533]==source.splitlines()[:533]
assert accepted.splitlines()[533+len(COMPLETE.splitlines()):]==source.splitlines()[536:]
assert invoke('surgical_test_edit',complete).get('error') and target.read_bytes()==accepted
print(json.dumps({'schema':'surgical-status-atomic-probe-v1','status':'passed','uid':os.getuid(),
    'network':'none','model_calls':0,'credentials_absent':not Path('/var/run/docker.sock').exists() and not Path('/secret').exists(),
    'partial_before_write_denied':True,'incomplete_observations_denied':True,'direct_handler_fenced':True,
    'fresh_process_before_write_denied':True,'whole_multiline_accepted':True,'narrow_schema':True,
    'outside_window_preserved':True,'stale_edit_denied':True,'delivery_approval':False}))
