"""Synthetic complete-read fixture; never actual artifact or product evidence."""
import json


def body():
    paths=['/evidence/'+tree+'/tests/test_fixture.py' for tree in ('candidate','previous')]
    messages=[dict(role='user',content='DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'+
        ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in paths)+
        'Synthetic transport qualification ONLY: these are fixture reads, not actual repository artifacts. '
        'Submit action=escalate_cto, reason="Synthetic qualification only", optional_files=[]. '
        'Do not claim approval, execution, file editing or a real defect.')]
    for i,path in enumerate(paths):
        identity='fixture-'+str(i)
        messages.extend([dict(role='assistant',tool_calls=[dict(id=identity,type='function',function=dict(
            name='read_file',arguments=json.dumps(dict(path=path,offset=1,limit=100))))]),
            dict(role='tool',tool_call_id=identity,content=json.dumps(dict(content='1|assert True\n',total_lines=1)))])
    return dict(messages=messages)
