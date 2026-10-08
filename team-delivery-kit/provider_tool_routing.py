"""Haiku named-tool routing compatibility; local contracts remain authoritative.

Only the provider-selection hint changes. The model, selected tool, strict
schema, arguments, budgets and caller validation are never changed here.
"""
import copy


def wire(body):
    choice=body.get('tool_choice')
    if (body.get('model')!='anthropic/claude-haiku-5.5'
            or not isinstance(choice,dict) or choice.get('type')!='function'
            or (body.get('provider') or {}).get('require_parameters') is not True):return body
    name=(choice.get('function') or {}).get('name')
    selected=[t for t in body.get('tools',[]) if (t.get('function') or {}).get('name')==name]
    if not isinstance(name,str) or not name or len(selected)!=1:
        raise ValueError('exact forced tool registry required for routing compatibility')
    result=copy.deepcopy(body)
    result['provider']['require_parameters']=False
    return result
