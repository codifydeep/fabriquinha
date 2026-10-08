"""Independent CTO source review; never manufacture a human answer or approval."""
import hashlib
import json


def pending(state):
    if not state or not state.get('configuration_sha256'):return False
    return state.get('stage')=='reviewing_brief_sources' or (
        state.get('stage')=='blocked_awaiting_ceo' and state.get('brief_clarification_product')==1
        and not state.get('source_review') and bool(state.get('questions')))


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
        elif row['quote'] or row['answer']:raise ValueError('CTO cannot answer missing business choices')
    return rows


def run(state,brief,registry,path):
    from planning_intake import issue_for,completed_output
    from release_eval import save_receipt
    if not pending(state):return state
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
    try:
        issue=issue_for('cto',context,registry['agents']['cto'],run_name=state['name']+'-SOURCE-REVIEW')
        receipt.update(stage='working',issue_id=issue);save_receipt(path,state)
        task,text=completed_output(issue,registry['agents']['cto'])
        rows=validate(json.loads(text),brief,questions)
        receipt.update(stage='verified',task_id=task,resolutions=rows,
            output_sha256=hashlib.sha256(text.encode()).hexdigest(),ceo_answer_created=False,scope_approval_created=False)
        unresolved=[questions[r['index']] for r in rows if r['classification']=='requires_ceo']
        if unresolved:state.update(stage='blocked_awaiting_ceo',owner='ceo',active='product',questions=unresolved)
        else:
            state.update(stage='product_source_reconciliation',owner='product',active='product',
                prior_source_review_product={'output':state['outputs']['product'],
                    'issue_id':state['issues']['product'],'questions':questions},outputs={},source_review_product=1)
            state.pop('questions',None)
        save_receipt(path,state);return state
    except Exception as error:
        receipt.update(stage='blocked',category=(type(error).__name__+':'+str(error))[:180])
        state.update(stage='blocked',owner='cto',active='source_review',category=receipt['category'],
                     next_action='Diagnose source review; no identical retry')
        save_receipt(path,state);return state
