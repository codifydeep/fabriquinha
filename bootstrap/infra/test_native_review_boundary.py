import json
import os
from unittest.mock import patch
import model_tools
from tools.registry import registry
import review_boundary

assert review_boundary.__file__=='/opt/hermes/review_boundary.py'
with patch.object(review_boundary,'worker_state',return_value=dict(mode='review',task='t_one')):
    for tool in ['terminal','write_file','patch','execute_code','tool_call','kanban_unblock']:
        result=model_tools.handle_function_call(tool,{})
        assert json.loads(result)['error']=='operation_forbidden',(tool,result)
        result=registry.dispatch(tool,{})
        assert json.loads(result)['error']=='operation_forbidden',(tool,result)
    assert json.loads(registry.dispatch('kanban_show',{}))['mode']=='review'
assert registry.get_entry('review_inspect') is not None
assert registry.get_entry('review_validate') is not None
print('PASS: native dispatcher and direct registry deny writes, shell, bridge and administrative operations')
print('PASS: explicit immutable review tools are registered')

# Exercise the PUBLIC model-facing API, including cached returns. Registry
# presence alone did not detect the cycle-4 integration failure.
from tools import kanban_tools
with patch.dict(os.environ,HERMES_KANBAN_TASK='t_one'), patch.object(kanban_tools,'_is_dispatcher_owned_worker',return_value=True):
    for mode in ('implementation','review','diagnosis','rework','review'):
        with patch.object(review_boundary,'worker_state',return_value=dict(mode=mode,task='t_one')):
            for quiet in (False,True):
                for skip in (False,True):
                    schemas=model_tools.get_tool_definitions(enabled_toolsets=['kanban','terminal','file'],quiet_mode=quiet,skip_tool_search_assembly=skip)
                    names={d['function']['name'] for d in schemas}
                    required={'review_inspect','review_validate','review_probe_write'} if mode=='review' else {'review_diagnose','review_resume'} if mode=='diagnosis' else {'rework_document'} if mode=='rework' else {'review_fetch_parent'}
                    assert required<=names,(mode,quiet,skip,names)
                    if mode!='implementation': assert not {'terminal','write_file','patch'}&names,(mode,names)
print('PASS: actual model catalogue, cache hits and mode transitions expose only mode-specific tools')
