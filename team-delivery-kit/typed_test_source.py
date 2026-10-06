"""Opt-in source-line proposal transport; not execution or generated code.

Only agent-supplied lines are joined. Existing path/size/AST and worker gates
still apply, followed by controller Red and independent review.
"""
import copy
import json
import re
NAME='submit_test_source'
MARKER='DELIVERY_TYPED_TEST_SOURCE_V1'

def active(body):
    for m in body.get('messages',[]):
        if m.get('role')=='user' and isinstance(m.get('content'),str) and re.search(r'^'+MARKER+r'$',m['content'],re.M):return True
    return False

def apply(body):
    if not active(body) or body.get('tool_choice')!={'type':'function','function':{'name':'write_file'}}:return body
    from surgical_test_edit import marker_config
    if marker_config(body):raise ValueError('typed source cannot replace surgical edits')
    for m in body.get('messages',[]):
        if 'DELIVERY_TEST_REVISION_V1:' in str(m.get('content','')):raise ValueError('typed source is initial-artifact only')
    write=next(t['function'] for t in body['tools'] if t['function']['name']=='write_file')
    paths=write['parameters']['properties']['path'].get('enum')
    if not paths or len(paths)!=1 or not paths[0].endswith('.py'):raise ValueError('bound Python source required')
    if any(t.get('function',{}).get('name')==NAME for t in body['tools']):raise ValueError('typed source collision')
    result=copy.deepcopy(body)
    result['stream']=False
    result['tools'].append(dict(type='function',function=dict(name=NAME,strict=True,
        description='Propose exact Python source lines; never execute. The controller preserves the existing write gates.',
        parameters=dict(type='object',properties=dict(path=dict(type='string',enum=paths),
            lines=dict(type='array',minItems=1,maxItems=128,items=dict(type='string',maxLength=512))),
            required=['path','lines'],additionalProperties=False))))
    result['tool_choice']=dict(type='function',function=dict(name=NAME))
    result['messages'].append(dict(role='user',content='SOURCE-LINE TRANSPORT: use submit_test_source(path, lines). '
        'Each item is one exact Python source line, with indentation but without a newline character. '
        'Start with import unittest; define a unittest.TestCase class and def test_...(self) with real assertions. '
        'No Markdown, quoted complete file, JSON envelope or helper-only harness. '
        'The adapter joins lines with newlines; it does not invent imports/tests or execute anything. '
        'Only the pinned new test path is allowed. Full Red and independent review remain mandatory.'))
    return result

def validation_body(body):
    if body.get('tool_choice')!={'type':'function','function':{'name':NAME}}:return body
    result=copy.deepcopy(body);result['tool_choice']=dict(type='function',function=dict(name='write_file'))
    result['tools']=[t for t in result['tools'] if t.get('function',{}).get('name')!=NAME]
    return result

def translate(body,data,media):
    if body.get('tool_choice')!={'type':'function','function':{'name':NAME}}:return data,media
    if media!='application/json':raise ValueError('typed source requires nonstreaming response')
    record=json.loads(data);choices=record.get('choices',[])
    if len(choices)!=1 or choices[0].get('finish_reason')!='tool_calls':raise ValueError('typed source incomplete')
    calls=choices[0].get('message',{}).get('tool_calls',[])
    if len(calls)!=1 or calls[0].get('function',{}).get('name')!=NAME:raise ValueError('typed source wrong tool')
    args=json.loads(calls[0]['function']['arguments'])
    proposal=next(t['function'] for t in body['tools'] if t['function']['name']==NAME)
    paths=proposal['parameters']['properties']['path']['enum']
    if not isinstance(args,dict) or set(args)!={'path','lines'} or args['path'] not in paths:raise ValueError('typed source path')
    lines=args['lines']
    if (not isinstance(lines,list) or not 1<=len(lines)<=128 or any(not isinstance(s,str) or len(s)>512
            or any(c in s for c in ('\n','\r','\0')) for s in lines)):raise ValueError('typed source lines')
    content='\n'.join(lines)+'\n'
    limit=next(t['function'] for t in body['tools'] if t['function']['name']=='write_file')['parameters']['properties']['content']['maxLength']
    if len(content)>limit or len(content.encode())>6144:raise ValueError('typed source size')
    call=calls[0];call['function']=dict(name='write_file',arguments=json.dumps(dict(path=args['path'],content=content)))
    return json.dumps(record).encode(),'application/json'

def caller_response(body,data,media,requested_stream):
    """Restore the caller's transport after validation; never execute a tool.

    The typed upstream proposal is nonstreaming. Hermes streaming consumers
    must still receive SSE, not a JSON completion they cannot consume.
    """
    if (not requested_stream or media!='application/json'
            or body.get('tool_choice')!={'type':'function','function':{'name':NAME}}):return data,media
    record=json.loads(data);choice=record['choices'][0]
    calls=choice['message']['tool_calls']
    if len(calls)!=1 or calls[0]['function']['name']!='write_file' or choice['finish_reason']!='tool_calls':
        raise ValueError('validated source write required')
    common={k:record[k] for k in ('id','created','model','system_fingerprint') if k in record}
    common['object']='chat.completion.chunk'
    frames=[dict(common,choices=[dict(index=0,delta=dict(role='assistant',tool_calls=[dict(calls[0],index=0)]),finish_reason=None)]),
            dict(common,choices=[dict(index=0,delta={},finish_reason='tool_calls')])]
    return (''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n').encode(),'text/event-stream'
