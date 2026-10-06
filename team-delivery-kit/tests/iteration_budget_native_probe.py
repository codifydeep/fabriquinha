"""Execute installed guard AST; no agent/provider call, not a full RPC claim."""
import ast
import json
import os
from pathlib import Path
from unittest.mock import patch

import acp_result_contract

source=Path('/opt/hermes/agent/turn_finalizer.py').read_text()
tree=ast.parse(source)
function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='finalize_turn')
nodes=function.body
start=next(i for i,n in enumerate(nodes) if isinstance(n,ast.ImportFrom)
           and n.module=='iteration_budget_contract')
guard=nodes[start:start+3]
assert isinstance(guard[-1],ast.If)
assert ast.unparse(guard[-1].test)=='delivery_controller_budget_exhausted'
stamp=next(n for n in reversed(nodes) if isinstance(n,ast.If)
           and ast.unparse(n.test)=='delivery_controller_budget_exhausted')
compiled=compile(ast.fix_missing_locations(ast.Module(body=guard,type_ignores=[])),
                 '<installed-budget-guard>','exec')
finish=compile(ast.fix_missing_locations(ast.Module(body=[stamp],type_ignores=[])),
               '<installed-budget-stamp>','exec')
for mode in ('implementation','review','diagnostic'):
    state=dict(os=os,budget_fallback_eligible=True,continuation_budget_exhausted=False,
        iteration_limit_fallback=False,failed=False,final_response=None,result={})
    with patch.dict(os.environ,{'DELIVERY_EXECUTION_MODE':mode}):exec(compiled,state)
    exec(finish,state)
    assert state['failed'] and state['final_response']==''
    assert state['iteration_limit_fallback'] and state['_turn_exit_reason']=='iteration_budget_exhausted'
    assert state['result']['completed'] is False
    try:acp_result_contract.require_success(state['result'])
    except RuntimeError as error:assert str(error)=='hermes_run_failed:iteration_budget_exhausted'
    else:raise AssertionError('budget failure accepted')
assert 'agent._persist_session(' in source and 'agent._cleanup_task_resources(' in source
print(json.dumps(dict(installed_budget_guard='passed',modes=3,model_calls=0,
                     delivery_approval=False,full_rpc_qualified=False)))
