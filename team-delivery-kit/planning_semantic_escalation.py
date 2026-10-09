"""Bounded Tech Lead -> CTO diagnosis -> fresh plan, never synthesized tests."""
import copy
import hashlib
import json
import subprocess

ERRORS = {
    'unsupported execution graph', 'unqualified test runner',
    'planning edits frozen tests',
    'each implementation card requires a new discoverable test file',
    'new tests must be discoverable in qualified roots',
}


def qualify(state, runs, bindings, proposals, tracked, agent):
    from planning_intake import validate_execution_plan
    if (not state or state.get('stage')!='blocked' or state.get('active')!='techlead'
            or state.get('retry_techlead')!=1 or state.get('semantic_escalation')
            or not state.get('configuration_sha256')
            or set(state.get('outputs',{}))!={'product','cto'}
            or state.get('category')!='ValueError:'+state.get('rejected_category','').removeprefix('ValueError:')
            or state.get('category','').removeprefix('ValueError:') not in ERRORS
            or len(runs)!=2 or len(bindings)!=2 or len(proposals)!=2):
        return None
    identities=[r.get('id') for r in runs]
    if identities[0]!=state.get('rejected_task_id') or not identities[1] or len(set(identities))!=2:
        return None
    for index,(run,binding,proposal) in enumerate(zip(runs,bindings,proposals)):
        if (run.get('status')!='completed' or run.get('agent_id')!=agent
                or binding.get('task_id')!=run['id'] or binding.get('agent_id')!=agent
                or binding.get('issue_id')!=run.get('issue_id')
                or binding.get('mode')!='planning' or binding.get('lease_status')!='closed'
                or ':planning:' not in binding.get('scope','')
                or index==1 and run.get('issue_id')!=state['issues']['techlead']):
            return None
        try: validate_execution_plan(proposal,tracked)
        except ValueError as error:
            if 'ValueError:'+str(error)!=state['category']: return None
        else: return None
    proof=dict(operation='repeated_invalid_execution_plan_v1',tasks=identities,
        issues=[r['issue_id'] for r in runs],constraint=state['category'],
        proposal_sha256=[digest(p) for p in proposals],tracked_sha256=digest(sorted(tracked)),
        configuration_sha256=state['configuration_sha256'],delivery_approval=False,
        author_execution_authorized=False)
    result=copy.deepcopy(state)
    result['semantic_escalation']=dict(stage='diagnosing',proof=proof,
        rejected_plan=proposals[-1],previous_blocker=copy.deepcopy(state),attempt_limit=1)
    result.update(stage='planning_technical_diagnosis',active='cto',owner='cto',
        next_action='CTO diagnoses the repeated planning constraint; never ask CEO to fix technical scope')
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def observe(state,selection,registry,cli,project_config=None):
    if (not state or state.get('stage')!='blocked' or state.get('active')!='techlead'
            or state.get('semantic_escalation') or state.get('retry_techlead')!=1
            or state.get('configuration_sha256')!=selection['configuration_sha256']
            or state.get('base_sha')!=selection['base_sha']
            or state.get('category','').removeprefix('ValueError:') not in ERRORS): return None
    from evalctl import PROJECT
    if PROJECT!='delivery-kit-port2': return None
    broker=PROJECT+'-execution-broker-1'
    labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',broker],text=True,timeout=10))
    if labels.get('com.docker.compose.project')!=PROJECT or labels.get('com.docker.compose.service')!='execution-broker':
        raise ValueError('owned planning diagnosis controller required')
    agent=registry['agents']['techlead']
    latest=[r for r in cli('runs',state['issues']['techlead']) if r.get('agent_id')==agent]
    if len(latest)!=1 or latest[0].get('status')!='completed': return None
    tasks=[state.get('rejected_task_id'),latest[0]['id']]
    if not tasks[0] or len(set(tasks))!=2: return None
    program='''import broker as b,json,sys
with b.db() as c:
 rows=c.execute("SELECT n.task_id,n.agent_id,n.issue_id,n.scope,g.mode,l.status AS lease_status FROM native_bindings n JOIN grants g USING(request_id) JOIN leases l USING(request_id) WHERE n.task_id IN (?,?)",sys.argv[1:]).fetchall()
 print(json.dumps([dict(r) for r in rows]))
'''
    rows=json.loads(subprocess.check_output(['docker','exec','-w','/',broker,'python','-c',program,*tasks],text=True,timeout=15))
    by_task={row['task_id']:row for row in rows}
    if len(rows)!=2 or set(by_task)!=set(tasks): return None
    runs=[];proposals=[]
    from planning_intake import parse_proposal
    for task in tasks:
        binding=by_task[task]
        matches=[r for r in cli('runs',binding['issue_id']) if r.get('agent_id')==agent]
        if len(matches)!=1 or matches[0].get('id')!=task: return None
        run=matches[0];run={**run,'issue_id':binding['issue_id']}
        output=(run.get('result') or {}).get('output')
        if not isinstance(output,str): return None
        try: proposal=parse_proposal(output,'techlead')
        except (ValueError,TypeError): return None
        proposals.append(proposal);runs.append(run)
    from project_selection import current
    project=current(project_config)
    tracked=subprocess.check_output(['git','-C',str(project['checkout']),
        'ls-tree','-r','--name-only',selection['base_sha']],text=True,timeout=15).splitlines()
    return qualify(state,runs,[by_task[t] for t in tasks],proposals,tracked,agent)


def pending(state,selection,registry,cli,project_config=None):
    if (not state or state.get('configuration_sha256')!=selection['configuration_sha256']
            or state.get('base_sha')!=selection['base_sha']): return False
    if (state.get('stage')=='planning_technical_diagnosis'
            and state.get('semantic_escalation',{}).get('stage')=='diagnosing'): return True
    if context_recovery(state,selection,registry,cli) is not None: return True
    return observe(state,selection,registry,cli,project_config) is not None


def context_recovery(state,selection,registry,cli):
    """One pre-dispatch transport repair; no model re-execution or invented evidence."""
    record=(state or {}).get('semantic_escalation') or {}
    if (not state or state.get('stage')!='blocked' or record.get('stage')!='blocked'
            or record.get('error')!='ValueError:planning context exceeds issue limit'
            or record.get('context_recovery') or not record.get('diagnosis')
            or state.get('configuration_sha256')!=selection['configuration_sha256']
            or state.get('base_sha')!=selection['base_sha']): return None
    previous=record['previous_blocker'];diagnosis=record['diagnosis']
    if (diagnosis.get('delivery_approval') is not False
            or state['issues'].get('techlead')!=previous['issues']['techlead']): return None
    title=state['name']+'-S1 — techlead'
    if any(i['title'].startswith(title) for i in cli('list')['issues']): return None
    runs=cli('runs',record['diagnosis_issue_id'])
    if (len(runs)!=1 or runs[0].get('status')!='completed'
            or runs[0].get('id')!=diagnosis['task_id']
            or runs[0].get('agent_id')!=registry['agents']['cto']): return None
    from planning_intake import completed_output,parse_proposal
    task,answer=completed_output(record['diagnosis_issue_id'],registry['agents']['cto'])
    if (task!=diagnosis['task_id'] or hashlib.sha256(answer.encode()).hexdigest()!=diagnosis['content_sha256']
            or parse_proposal(answer,'cto')!=diagnosis['proposal']): return None
    value=copy.deepcopy(previous);restored=copy.deepcopy(record)
    restored.update(stage='awaiting_replan',context_recovery=dict(previous_failure=copy.deepcopy(state),
        pre_dispatch=True,diagnosis_reexecuted=False,delivery_approval=False))
    value.update(semantic_escalation=restored,stage='technical_replanning_techlead',active='techlead',owner='techlead')
    value.pop('category',None)
    return value


def replan_prompt(state,body,capabilities):
    record=state['semantic_escalation'];diagnosis=record['diagnosis']
    if (record['stage']!='awaiting_replan' or diagnosis.get('delivery_approval') is not False
            or state['outputs']!=record['previous_blocker']['outputs']):
        raise ValueError('independent CTO diagnosis and unchanged accepted inputs required')
    prompt=('DELIVERY_PLANNING_SCHEMA_V1:techlead\nNEW JSON plan only: '
        'role,cards,integration_order. Every card has id,title,owner,depends_on,acceptance,files,test_command. '
        'No tools, claims of executed work or approval.\n'+body)
    for role in ('product','cto'):
        prompt+='\nVerified '+role+' proposal: '+json.dumps(state['outputs'][role]['proposal'],ensure_ascii=False,separators=(',',':'))
    guidance={key:diagnosis['proposal'][key] for key in ('technical_decisions','risks')}
    return (prompt+'\nCTO diagnostic decisions/risks; full record preserved: '+
        json.dumps(guidance,ensure_ascii=False,separators=(',',':'))+
        '\nRejected constraint: '+record['proof']['constraint']+capabilities)


def diagnosis_prompt(state,body,capabilities):
    record=state['semantic_escalation'];proof=record['proof'];previous=record['previous_blocker']
    if (record['stage']!='diagnosing' or state['stage']!='planning_technical_diagnosis'
            or proof.get('operation')!='repeated_invalid_execution_plan_v1'
            or proof.get('configuration_sha256')!=state.get('configuration_sha256')
            or proof.get('delivery_approval') is not False or proof.get('author_execution_authorized') is not False
            or proof.get('proposal_sha256',[None])[-1]!=digest(record['rejected_plan'])
            or state.get('outputs')!=previous.get('outputs')
            or proof.get('constraint')!=previous.get('category')
            or proof.get('constraint','').removeprefix('ValueError:') not in ERRORS):
        raise ValueError('exact pending CTO planning diagnosis required')
    plan=record['rejected_plan']
    declarations=dict(role=plan['role'],integration_order=plan['integration_order'],cards=[
        {key:card[key] for key in ('id','owner','depends_on','files','test_command')}
        for card in plan['cards']])
    return ('DELIVERY_PLANNING_SCHEMA_V1:cto\nYOU ARE THE CTO. Diagnose a repeatedly '
        'rejected Tech Lead plan. Return only a concise CTO proposal with keys role,stack,'
        'components,security,technical_decisions,risks; strings <=300 characters. '
        'No tools, code writes, invented tests, CEO question or approval of the plan. '
        'Explain the failed execution constraint and propose how the Tech Lead must '
        'declare actual NEW discoverable tests alongside product files. Keep the '
        'existing approved stack and business scope. Another independent Tech Lead '
        'proposal must satisfy the unchanged compiler before cards can exist.\n'+body+
        '\nConstraint evidence: '+json.dumps(record['proof'],separators=(',',':'))+
        '\nCOMPLETE EXECUTION DECLARATIONS (acceptance remains in the binding CEO request; '
        'full rejected proposal is preserved by the controller): '+json.dumps(declarations,separators=(',',':'))+
        '\nExisting CTO proposal: '+json.dumps(state['outputs']['cto']['proposal'],separators=(',',':'))+capabilities)


def advance(state,body,capabilities,registry,path,run_name):
    from planning_intake import issue_for,completed_output,parse_proposal
    from release_eval import save_receipt
    value=copy.deepcopy(state);record=value['semantic_escalation']
    prompt=diagnosis_prompt(value,body,capabilities)
    if len(prompt)>8000:
        record.update(stage='blocked',error='diagnosis_context_requires_bounded_split')
        value.update(stage='blocked',active='cto',owner='cto',category='planning_diagnosis_context_too_large')
        save_receipt(path,value);return value
    save_receipt(path,value)  # durable intent precedes idempotent native issue lookup
    try:
        issue=issue_for('cto',prompt,registry['agents']['cto'],run_name=run_name+'-S1')
        if record.get('diagnosis_issue_id') not in (None,issue): raise ValueError('CTO diagnosis issue drift')
        record['diagnosis_issue_id']=issue;save_receipt(path,value)
        task,answer=completed_output(issue,registry['agents']['cto'])
        proposal=parse_proposal(answer,'cto')
        record.update(stage='awaiting_replan',diagnosis=dict(task_id=task,proposal=proposal,
                      content_sha256=hashlib.sha256(answer.encode()).hexdigest(),delivery_approval=False))
        value.update(stage='technical_replanning_techlead',active='techlead',owner='techlead')
        value.pop('category',None);save_receipt(path,value);return value
    except TimeoutError:
        record['observation']='native execution still requires terminal evidence'
        save_receipt(path,value)
        return value  # observer deadline is not permission to restart or reassign
    except Exception as error:
        record.update(stage='blocked',error=type(error).__name__+':'+str(error)[:180])
        value.update(stage='blocked',active='cto',owner='cto',category='planning_diagnosis_failed',
            next_action='CTO incident remains visible; no identical retry, test synthesis or CEO technical escalation')
        save_receipt(path,value);return value
