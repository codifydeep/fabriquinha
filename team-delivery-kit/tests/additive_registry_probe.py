"""Actual tool registry/handler fence; synthetic fixture, no paid/model calls."""
import hashlib,json,os
from pathlib import Path
root=Path('/workspace');root.mkdir(exist_ok=True)
source=root/'source.py';source.write_text('VALUE = 1\n');source.chmod(0o444)
target=root/'test_c01.py'
config={'path':str(target),'criterion':'C01','sources':{str(source):{'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}}}
os.environ.update(DELIVERY_EXECUTION_MODE='implementation',DELIVERY_ADDITIVE_TEST_JSON=json.dumps(config),HERMES_HOME='/tmp/additive-probe')
os.setgroups([]);os.setgid(10000);os.setuid(10000)
import sys;sys.path.insert(0,'/opt/hermes')
from tools.registry import registry,discover_builtin_tools
discover_builtin_tools()
from review_tool_policy import controlled
code='import unittest\nclass Control(unittest.TestCase):\n    def test_c01_query_clearing_control(self):\n        self.assertTrue(True)\n'
def call(tool,args):return json.loads(registry.dispatch(tool,args))
assert call('write_file',{'path':str(target),'content':code}).get('error') and not target.exists()
assert not call('read_file',{'path':str(source),'offset':1,'limit':200}).get('error')
assert call('write_file',{'path':str(source),'content':code}).get('error')
assert json.loads(controlled('terminal',{'command':'true'})).get('error')
assert call('patch',{'path':str(source),'old_string':'1','new_string':'2'}).get('error')
assert call('write_file',{'path':str(target),'content':'// promise only'}).get('error') and not target.exists()
assert call('write_file',{'path':str(target),'content':code})['verified'] is True
assert call('write_file',{'path':str(target),'content':code}).get('error')
assert source.read_text()=='VALUE = 1\n' and target.read_text()==code
print(json.dumps({'schema':'additive-registry-probe-v1','status':'passed','uid':os.getuid(),'network':'none','model_calls':0,
    'readless_denied':True,'existing_file_write_denied':True,'direct_terminal_denied':True,'patch_denied':True,
    'invalid_code_denied':True,'new_test_created':True,'overwrite_denied':True,'source_unchanged':True,
    'fixture_only':True,'delivery_approval':False}))
