"""Independent CTO source review; never manufacture a human answer or approval."""
import hashlib
import json
import subprocess


def transport(task):
    from evalctl import PROJECT
    if PROJECT!='delivery-kit-port2':raise ValueError('isolated source review required')
    for name,service in ((PROJECT+'-execution-broker-1','execution-broker'),(PROJECT+'-model-proxy-1','model-proxy')):
        labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',name],text=True,timeout=10))
        if labels.get('com.docker.compose.project')!=PROJECT or labels.get('com.docker.compose.service')!=service:
            raise ValueError('owned source review services required')
    code='''import broker as b,json,sys
with b.db() as c:
 print(json.dumps([dict(r) for r in c.execute("SELECT * FROM native_bindings WHERE task_id=?",(sys.argv[1],))]))
'''
    bindings=json.loads(subprocess.check_output(['docker','exec','-w','/',PROJECT+'-execution-broker-1',
        'python','-c',code,task],text=True,timeout=15))
    if len(bindings)!=1 or ':planning:' not in bindings[0]['scope']:raise ValueError('source review binding required')
    events=[]
    for line in subprocess.check_output(['docker','logs','--tail','500',PROJECT+'-model-proxy-1'],text=True,timeout=15).splitlines():
        try:event=json.loads(line)
        except json.JSONDecodeError:continue
        if event.get('event')=='model_proxy_request' and event.get('execution_id')==bindings[0]['request_id']:events.append(event)
    if (len(events)!=1 or events[0].get('status')!=200 or events[0].get('structured_format')!='json_schema'
            or events[0].get('strict_schema') is not True or events[0].get('tool_count')!=0):
        raise ValueError('strict tool-free source review transport not proven')
    return {'version':'source-review-transport-v1','execution_id':bindings[0]['request_id'],
            'call_number':events[0]['call_number'],'task_id':task,'strict_schema':True,'tools':0}


def pending(state):
    if not state or not state.get('configuration_sha256'):return False
    if diagnosis_pending(state):return True
    receipt=state.get('source_review') or {}
    if (state.get('stage')=='blocked_awaiting_ceo' and receipt.get('stage')=='verified'
            and not receipt.get('transport') and not state.get('prior_unqualified_source_review')):return True
    return state.get('stage')=='reviewing_brief_sources' or (
        state.get('stage')=='blocked_awaiting_ceo' and state.get('brief_clarification_product')==1
        and not state.get('source_review') and bool(state.get('questions')))


def diagnosis_pending(state):
    receipt=(state or {}).get('source_review') or {}
    prior=(state or {}).get('prior_invalid_source_review') or {}
    return bool(state and state.get('stage')=='blocked' and state.get('active')=='source_review'
        and not state.get('source_review_diagnosis')
        and state.get('category')=='ValueError:unresolved answer cannot claim explicit brief support'
        and receipt.get('stage')=='blocked' and prior.get('stage')=='verified'
        and receipt.get('transport',{}).get('version')=='source-review-transport-v1'
        and receipt.get('task_id')==prior.get('task_id') and receipt.get('task_id')
        and receipt.get('output_sha256')==prior.get('output_sha256')
        and receipt.get('brief_sha256')==state.get('brief_sha256')
        and receipt.get('configuration_sha256')==state.get('configuration_sha256'))


def validate(answer,brief,questions):
    if not isinstance(answer,dict) or set(answer)!={'role','resolutions'} or answer['role']!='cto':
        raise ValueError('invalid source review')
    rows=answer['resolutions']
    if not isinstance(rows,list) or len(rows)!=len(questions):raise ValueError('incomplete question coverage')
    for index,row in enumerate(rows):
        if (not isinstance(row,dict) or set(row)!={'index','classification','quote','answer'}
                or type(row['index']) is not int or row['index']!=index
                or row['classification'] not in ('explicit_brief','requires_ceo')
                or not isinstance(row['quote'],str) or len(row['quote'])>600
                or not isinstance(row['answer'],str) or len(row['answer'])>300):
            raise ValueError('invalid question resolution')
        if row['classification']=='explicit_brief':
            if not row['quote'].strip() or row['quote'] not in brief or not row['answer'].strip():
                raise ValueError('literal brief evidence required')
            if any(marker in row['answer'].lower() for marker in (
                    'brief does not say','not addressed','cannot be confirmed',
                    'not specified','unspecified','unresolved')):
                raise ValueError('unresolved answer cannot claim explicit brief support')
        elif row['quote'] or row['answer']:raise ValueError('CTO cannot answer missing business choices')
    return rows


def revalidate(state,brief):
    receipt=(state or {}).get('source_review') or {}
    if receipt.get('stage')!='verified':return None
    if receipt.get('brief_sha256')!=hashlib.sha256(brief.encode()).hexdigest():
        raise ValueError('persisted source review brief drift')
    try:validate({'role':'cto','resolutions':receipt['resolutions']},brief,receipt['questions'])
    except ValueError as error:
        return {**state,'prior_invalid_source_review':receipt,
            'source_review':{**receipt,'stage':'blocked','validation_category':str(error)},
            'stage':'blocked','owner':'cto','active':'source_review',
            'category':'ValueError:'+str(error),
            'next_action':'CTO diagnoses contradictory source evidence; no fabricated CEO response'}
    return None


def run(state,brief,registry,path):
    from planning_intake import issue_for,completed_output
    from release_eval import save_receipt
    if not pending(state):return state
    if diagnosis_pending(state):
        prior=state['source_review']
        state={**state,'source_review_diagnosis':{'stage':'intent','prior_review':prior,
            'category':state['category'],'scope_approval_created':False}}
        state.pop('source_review')
        state['questions']=prior['questions']
    if state.get('source_review',{}).get('stage')=='verified' and not state['source_review'].get('transport'):
        state={**state,'prior_unqualified_source_review':state['source_review']}
        state.pop('source_review')
    questions=state['questions']
    if state['brief_sha256']!=hashlib.sha256(brief.encode()).hexdigest():raise ValueError('source review brief drift')
    receipt=state.get('source_review') or {'stage':'intent','questions':questions,
        'brief_sha256':state['brief_sha256'],'configuration_sha256':state['configuration_sha256']}
    if (receipt['questions']!=questions or receipt['brief_sha256']!=state['brief_sha256']
            or receipt['configuration_sha256']!=state['configuration_sha256']):
        raise ValueError('source review identity drift')
    state={**state,'source_review':receipt,'stage':'reviewing_brief_sources','active':'cto','owner':'cto'}
    save_receipt(path,state)
    context=('DELIVERY_PLANNING_SCHEMA_V1:source_review\n'
        'You are CTO, independently checking repeated Product questions against the ORIGINAL brief. '
        'For EACH indexed question, use explicit_brief only when a literal contiguous quote '
        'directly answers it. Return that quote and a concise faithful answer. '
        'No scope additions, defaults, invented CEO answers or reinterpretations of absent business requirements. '
        'If the brief does not answer it, use requires_ceo with empty quote and answer. '
        'Future hypothetical features are outside current scope. This review grants no approval or permission. '
        'Return ONLY {"role":"cto","resolutions":[{"index":0,"classification":'
        '"explicit_brief","quote":"literal source","answer":"faithful reading"}]}. '
        'Cover every question in exact index order.\nQuestions: '+json.dumps(questions)+'\nORIGINAL BRIEF:\n'+brief)
    if state.get('source_review_diagnosis'):
        context += ('\nDIAGNOSE THE REJECTED REVIEW, not an identical retry. '
            'Rejected source review: '+json.dumps(state['source_review_diagnosis']['prior_review'])+
            '\nYour prior classification claimed explicit support while the answer claimed missing information. '
            'Inspect ALL interaction constraints in the brief, not just its first sentence. '
            'Distinguish a requested interaction from hypothetical additional features. '
            'An optional feature not requested is not a prerequisite for delivery. '
            'Use only a directly relevant literal quote and a conclusive supported answer. '
            'If support is genuinely absent, requires_ceo must have empty quote and answer. '
            'Never invent a CEO decision or widen scope.')
    try:
        issue=issue_for('cto',context,registry['agents']['cto'],run_name=state['name']+
            ('-SOURCE-REVIEW-DIAGNOSIS' if state.get('source_review_diagnosis') else
             '-SOURCE-REVIEW-STRICT' if state.get('prior_unqualified_source_review') else '-SOURCE-REVIEW'))
        receipt.update(stage='working',issue_id=issue);save_receipt(path,state)
        task,text=completed_output(issue,registry['agents']['cto'])
        wire=transport(task)
        rows=validate(json.loads(text),brief,questions)
        receipt.update(stage='verified',task_id=task,resolutions=rows,
            output_sha256=hashlib.sha256(text.encode()).hexdigest(),ceo_answer_created=False,
            scope_approval_created=False,transport=wire)
        unresolved=[questions[r['index']] for r in rows if r['classification']=='requires_ceo']
        if unresolved:state.update(stage='blocked_awaiting_ceo',owner='ceo',active='product',questions=unresolved)
        else:
            state.update(stage='product_source_reconciliation',owner='product',active='product',
                prior_source_review_product={'output':state['outputs']['product'],
                    'issue_id':state['issues']['product'],'questions':questions},outputs={},source_review_product=1,
                source_review_product_attempt=2 if state.get('source_review_diagnosis') else 1)
            state.pop('questions',None)
        if state.get('source_review_diagnosis'):
            state['source_review_diagnosis']={**state['source_review_diagnosis'],'stage':'decision_verified',
                'task_id':task,'issue_id':issue,'output_sha256':receipt['output_sha256']}
        for field in ('category','next_action'):state.pop(field,None)
        save_receipt(path,state);return state
    except Exception as error:
        receipt.update(stage='blocked',category=(type(error).__name__+':'+str(error))[:180])
        state.update(stage='blocked',owner='cto',active='source_review',category=receipt['category'],
                     next_action='Diagnose source review; no identical retry')
        save_receipt(path,state);return state
