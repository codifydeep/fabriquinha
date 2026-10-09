"""One counted provider protocol fixture, never a diagnosis or delivery proof.

Run inside the owned model proxy with --execute. No response content leaves
the process: only hashes, fixed protocol categories and envelope counts.
"""
import json
import hashlib
import sys


def fixture(model):
    # Synthetic tool history belongs ONLY to this explicitly labelled fixture.
    # It must never be registered as an artifact read or operational evidence.
    path='/evidence/previous/qa.json'
    return {'model':model,'max_tokens':512,'stream':True,'messages':[
        {'role':'user','content':'PROTOCOL FIXTURE ONLY: no execution or diagnosis authority. '
         'Return decision=blocked, root_cause="Protocol fixture", empty arrays and empty new_test_file.\n'
         'DELIVERY_STRUCTURED_DECISION_V1:qa\nDELIVERY_REVIEW_READ_PATH:'+path+'\n'},
        {'role':'assistant','content':None,'tool_calls':[{'id':'fixture','type':'function',
         'function':{'name':'read_file','arguments':json.dumps({'path':path})}}]},
        {'role':'tool','tool_call_id':'fixture','content':json.dumps({
            'content':'1|{"fixture":true}\n','total_lines':1})}],
        'tools':[{'type':'function','function':{'name':'read_file','parameters':{
            'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}}]}


def summary(data,media):
    def finish(value):
        return value if value in (None,'stop','length','tool_calls','content_filter') else 'other'
    frames=[]
    for line in data.decode(errors='replace').splitlines():
        if line.startswith('data:') and line[5:].strip()!='[DONE]':
            try:frames.append(json.loads(line[5:].strip()))
            except ValueError:pass
    choices=[c for f in frames for c in f.get('choices',[])]
    text=''.join(c.get('delta',{}).get('content') or '' for c in choices)
    valid=False
    try:json.loads(text);valid=True
    except ValueError:pass
    after=[];finished=False
    for c in choices:
        if finished:after.append({'content_type':type(c.get('delta',{}).get('content')).__name__,
            'content_chars':len(c.get('delta',{}).get('content') or ''),'finish':finish(c.get('finish_reason')),
            'role_is_assistant':c.get('delta',{}).get('role')=='assistant',
            'delta_fields':[k for k in ('content','role','tool_calls','function_call','reasoning','reasoning_details')
                            if k in c.get('delta',{})],
            'unknown_delta_fields':len(set(c.get('delta',{}))-
                {'content','role','tool_calls','function_call','reasoning','reasoning_details'})})
        if c.get('finish_reason') is not None:finished=True
    return {'kind':'protocol_fixture_not_delivery_evidence','media':
        'text/event-stream' if media.startswith('text/event-stream') else
        'application/json' if media.startswith('application/json') else 'other',
        'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'frames':len(frames),
        'indexes':[c.get('index') if type(c.get('index')) is int else 'other' for c in choices],
        'finishes':[finish(c.get('finish_reason')) for c in choices if c.get('finish_reason') is not None],
        'after_finish':after,'text_chars':len(text),'json_valid':valid,
        'fenced':text.strip().startswith('```'),'done_markers':data.count(b'data: [DONE]')}


def main():
    if sys.argv[1:]!=['--execute']:raise ValueError('explicit counted protocol fixture required')
    import model_proxy as p
    body=p.validate_request(fixture(p.MODEL))
    call=p.reserve_call()
    try:
        status,data,media=p.forward(body)
        proof=summary(data,media)
        proof.update(call=call,status=status)
        try:p.validate_structured_response(body,data,media);proof['local_validation']='passed'
        except Exception as error:
            proof['local_validation']=getattr(error,'category',type(error).__name__)
            reasons={'data after decision terminal','invalid content','incomplete stream',
                'nonterminal decision','unexpected tool call','multiple choices',
                'data after terminal','decision object required','schema missing'}
            cause=getattr(error,'__context__',None)
            proof['protocol_reason']=str(cause) if str(cause) in reasons else 'unclassified'
    except Exception as error:
        proof={'kind':'protocol_fixture_not_delivery_evidence','call':call,
               'status':'failed','category':type(error).__name__}
        if hasattr(error,'diagnostic'):proof['diagnostic']=error.diagnostic
    print(json.dumps(proof))


if __name__=='__main__':main()
