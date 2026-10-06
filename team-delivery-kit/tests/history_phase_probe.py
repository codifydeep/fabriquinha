"""Offline private-history diagnosis; output categories only, never contents."""
import hashlib
import json
import sqlite3
import sys
import uuid
from model_policy import MODEL
from model_proxy import validate_request
from deterministic_read_dispatch import make


def main():
    session,execution=sys.argv[1:3]
    assert str(uuid.UUID(session))==session and str(uuid.UUID(execution))==execution
    con=sqlite3.connect('file:/session/state.db?mode=ro',uri=True)
    con.row_factory=sqlite3.Row
    messages=[]
    for row in con.execute('SELECT role,content,tool_call_id,tool_calls FROM messages WHERE session_id=? ORDER BY id',(session,)):
        message={k:row[k] for k in ('role','content')}
        if row['tool_call_id']:message['tool_call_id']=row['tool_call_id']
        if row['tool_calls']:message['tool_calls']=json.loads(row['tool_calls'])
        messages.append(message)
    assert messages
    body=dict(model=MODEL,messages=messages,tools=[dict(type='function',function=dict(
        name=name,parameters={})) for name in ('read_file','write_file','patch','terminal')])
    body['tools'][1]['function']['parameters']={'type':'object','properties':{
        'path':{'type':'string'},'content':{'type':'string'}}}
    prefix_rejections=[]
    for end in range(1,len(messages)+1):
        if messages[end-1].get('role')!='tool':continue
        try:
            prefix=validate_request({**body,'messages':messages[:end]})
            make(prefix,execution)
        except (ValueError,TypeError) as error:
            prefix_rejections.append(dict(message_count=end,exception_type=type(error).__name__,
                error_sha256=hashlib.sha256(str(error).encode()).hexdigest()))
    try:
        result=validate_request(body)
        selected=(result.get('tool_choice') or {}).get('function',{}).get('name')
        function=next((t['function'] for t in result.get('tools',[]) if t['function']['name']==selected),{})
        outcome=dict(status='accepted',selected_tool=selected,selected_read={k:v.get('enum')
            for k,v in function.get('parameters',{}).get('properties',{}).items()
            if selected=='read_file' and k in ('path','offset','limit')})
        make(result,execution)
    except (ValueError,TypeError) as error:
        known={'review inspection stalled','invalid new-test target','invalid test artifact phase contract',
               'seeded edit target drift','revision target drift','test artifact write failed twice; diagnosis required',
               'invalid deterministic read contract','unrecognized write_file signature',
               'typed source is initial-artifact only'}
        outcome=dict(status='rejected',category=str(error) if str(error) in known else 'unclassified',
            exception_type=type(error).__name__,error_sha256=hashlib.sha256(str(error).encode()).hexdigest())
    con.close()
    print(json.dumps(dict(operation='private_history_phase_probe_v1',messages=len(messages),
        validation=outcome,prefix_rejections=prefix_rejections[-12:],
        model_calls=0,delivery_approval=False,full_rpc_qualified=False)))


if __name__=='__main__':main()
