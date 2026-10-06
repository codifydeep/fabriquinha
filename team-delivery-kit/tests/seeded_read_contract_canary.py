"""Fixed proxy-image canary; no provider call, source read or write is faked."""
import json
import sys
from test_artifact_schema import apply
from deterministic_read_dispatch import make


def main():
    expectation=sys.argv[1]
    if expectation not in ('reject','dispatch'):raise ValueError('fixed expectation required')
    body=dict(model='deepseek/deepseek-v4.1-flash',stream=False,
        messages=[dict(role='user',content='DELIVERY_TEST_ARTIFACT_V1:/workspace/tests/test_new.py\n'
            'DELIVERY_TEST_SOURCE_V1:/workspace/app.py\nDELIVERY_TEST_REVISION_V1:/workspace/tests/test_new.py\n'
            'DELIVERY_DETERMINISTIC_READ_V1\n')],
        tools=[dict(type='function',function=dict(name=n,parameters={})) for n in ('read_file','write_file')])
    body['messages'] += [dict(role='assistant',tool_calls=[dict(id='fixture-read',function=dict(name='read_file',
        arguments=json.dumps(dict(path='/workspace/app.py',offset=1,limit=50))))]),
        dict(role='tool',tool_call_id='fixture-read',content=json.dumps(dict(content='1|fixture',total_lines=1)))]
    body=apply(body)
    try:dispatch=make(body,'48555431-92f1-4f52-868a-075b4a3a7554')
    except ValueError as error:
        if expectation!='reject' or str(error)!='invalid deterministic read contract':raise
        print(json.dumps(dict(operation='seeded_read_contract_canary_v1',result='rejected_exact_seed_read',
            expected=True,synthetic_fixture=True,provider_called=False,delivery_approval=False)))
        return
    if expectation!='dispatch' or not dispatch:raise ValueError('fixed seed read was not dispatched')
    call=json.loads(dispatch['data'])['choices'][0]['message']['tool_calls'][0]
    if json.loads(call['function']['arguments'])!=dict(path='/workspace/tests/test_new.py',offset=1,limit=50):
        raise ValueError('seeded read arguments drift')
    print(json.dumps(dict(operation='seeded_read_contract_canary_v1',result='dispatched_exact_seed_read',
        expected=True,synthetic_fixture=True,provider_called=False,delivery_approval=False)))


if __name__=='__main__':main()
