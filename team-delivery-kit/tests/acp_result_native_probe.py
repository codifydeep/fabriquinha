"""Exercise the installed ACP guard offline; not a full provider/RPC trial."""
import ast
import copy
import json
from pathlib import Path
import threading
from types import SimpleNamespace


def main():
    source=Path('/opt/hermes/acp_adapter/server.py').read_text()
    tree=ast.parse(source)
    methods=[n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='prompt']
    assert len(methods)==1
    body=methods[0].body
    starts=[i for i,n in enumerate(body) if isinstance(n,ast.ImportFrom) and n.module=='acp_result_contract']
    assert len(starts)==1
    index=starts[0];assert isinstance(body[index+1],ast.Try)
    # Execute these EXACT installed statements, never a rewritten copy of the
    # guard. The surrounding provider/ACP session is deliberately not mocked
    # into a claim of successful integration.
    function=ast.FunctionDef(name='guard',args=ast.arguments(posonlyargs=[],
        args=[ast.arg(arg='result'),ast.arg(arg='state')],kwonlyargs=[],kw_defaults=[],defaults=[]),
        body=copy.deepcopy(body[index:index+2])+[ast.Return(value=ast.Name(id='result',ctx=ast.Load()))],
        decorator_list=[])
    module=ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[]));scope={}
    exec(compile(module,'<installed-acp-guard>','exec'),scope)
    state=SimpleNamespace(runtime_lock=threading.Lock(),is_running=True,
        current_prompt_text='private prompt',cancel_event=None,history=['preserved'])
    try:
        scope['guard']({'failed':True,'completed':False,'error':'private provider detail',
            'failure_reason':'timeout','final_response':'I will continue.'},state)
    except RuntimeError as error:
        assert str(error)=='hermes_run_failed:timeout'
    else:raise AssertionError('failed run became successful end_turn')
    assert state.is_running is False and state.current_prompt_text=='' and state.history==['preserved']
    normal={'completed':True,'failed':False,'final_response':'tested error branch'}
    assert scope['guard'](normal,state) is normal
    print(json.dumps(dict(operation='installed_acp_result_guard_offline_v1',status='passed',
        structured_failure_raised=True,idle_state_restored=True,history_preserved=True,
        successful_result_unchanged=True,model_calls=0,full_rpc_qualified=False,
        delivery_approval=False)))


if __name__=='__main__':main()
