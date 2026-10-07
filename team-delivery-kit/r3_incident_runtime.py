"""Durable TL diagnosis -> independent CTO review, without recovery authority."""
import fcntl
import json
import os
from pathlib import Path
import time
from portable_remediation_intake import digest, read
from release_eval import command, save_receipt
from r3_incident_contract import schema, planning_instruction as instruction

FACTS = {'controller_handle_missing','controller_identity_changed','controller_ambiguous',
    'controller_unrecorded','launch_acknowledgment_unknown','progress_deadline_exceeded',
    'r2_dependency_not_qualified','delivery_receipt_missing','status_identity_changed',
    'invalid_launch_handle','delivery_not_verified','experiment_controller_absent','experiment_controller_present',
    'experiment_controller_ambiguous','experiment_snapshot_intact','experiment_github_ci_exact_sha',
    'experiment_local_deployment_exact_sha','experiment_delivery_unavailable','experiment_verification_failed',
    'experiment_review_obsolete','experiment_review_unobservable','experiment_result_unobservable'}

CATEGORIES = dict(r3_controller_handle_missing='controller_handle_missing',
    r3_controller_identity_changed='controller_identity_changed',ambiguous_r3_controller='controller_ambiguous',
    unrecorded_r3_controller='controller_unrecorded',r3_progress_deadline='progress_deadline_exceeded',
    r3_dependency_not_qualified='r2_dependency_not_qualified',r3_delivery_receipt_disappeared='delivery_receipt_missing',
    r3_status_identity_changed='status_identity_changed',invalid_r3_launch_handle='invalid_launch_handle')

RPC = '''import sys;sys.path.insert(0,"/")
import json,r3_incident_native
print(json.dumps(r3_incident_native.request(sys.argv[1],json.loads(sys.argv[2]))))
'''


class Effects:
    def __init__(self, instance):self.instance=instance
    def request(self, operation, body):
        return json.loads(command('docker','exec',self.instance+'-execution-broker-1',
                                  'python','-c',RPC,operation,json.dumps(body,sort_keys=True)))
    def binding(self,evidence):return self.request('binding',dict(evidence=evidence))
    def issue(self,config,*,allow_create):return self.request('issue',dict(config=config,allow_create=allow_create))
    def wake(self,config,state,note,*,allow_create):
        return self.request('wake',dict(config=config,state=state,note=note,allow_create=allow_create))
    def runs(self,config,state):return self.request('runs',dict(config=config,state=state))
    def task(self,config,state,task):return self.request('task',dict(config=config,state=state,task=task))
    def remaining(self):return self.request('remaining',{})
    def now(self):return time.time()


def validate_evidence(evidence):
    expected={'operation','root_issue','source_task','controller_identity','bundle_sha256','r2_proof_sha256',
              'category','facts','execution_authorized','release_homologated'}
    continuation={'previous_incident_sha256','experiment_receipt_sha256','experiment_result_sha256','experiment_history'}
    import re
    if (set(evidence) not in (expected,expected|continuation) or evidence['operation']!='r3_incident_evidence_v1'
            or any(not re.fullmatch('[a-f0-9]{64}',str(evidence[k])) for k in
                   ('controller_identity','bundle_sha256','r2_proof_sha256'))
            or not isinstance(evidence['category'],str) or not re.fullmatch('[a-z0-9_]{1,80}',evidence['category'])
            or not all(isinstance(evidence[k],str) and 1<=len(evidence[k])<=64 for k in ('root_issue','source_task'))
            or evidence['execution_authorized'] is not False or evidence['release_homologated'] is not False
            or not isinstance(evidence['facts'],dict) or not 1<=len(evidence['facts'])<=10
            or set(evidence['facts'])!={'F'+str(i).zfill(2) for i in range(1,len(evidence['facts'])+1)}
            or any(not re.fullmatch('F[0-9]{2}',key) or value not in FACTS for key,value in evidence['facts'].items())):
        raise ValueError('bounded controller-produced R3 evidence required')
    if continuation<=set(evidence):
        operations={'observe_existing_controller','verify_frozen_delivery','verify_github_ci','verify_local_deployment'}
        history=evidence['experiment_history']
        if (any(not re.fullmatch('[a-f0-9]{64}',str(evidence[k])) for k in continuation-{'experiment_history'})
                or not isinstance(history,list) or not 1<=len(history)<=4
                or any(not isinstance(v,str) or v not in operations for v in history) or len(set(history))!=len(history)):
            raise ValueError('exact bounded post-experiment lineage required')
    return evidence


def validate_decision(config,state,task):
    review=state['stage']=='awaiting_review';kind='review' if review else 'diagnose'
    actor=config[('techlead' if review else 'cto') if state.get('escalated') else ('cto' if review else 'techlead')]
    if (task.get('id')!=state['task_id'] or task.get('status')!='completed'
            or task.get('issue_id')!=state['issue_id'] or task.get('agent_id')!=actor
            or task.get('wakeup_id')!=state['wakeup_id']):
        raise ValueError('exact independent incident execution required')
    raw=(task.get('result') or {}).get('output')
    if not isinstance(raw,str) or not 1<=len(raw)<=6000:raise ValueError('bounded actual JSON submission required')
    body=json.loads(raw)
    spec=schema(kind,config['evidence_sha256'],sorted(config['evidence']['facts']),state.get('proposal_sha256') if review else None)
    if not isinstance(body,dict) or set(body)!=set(spec['required']):raise ValueError('exact R3 decision required')
    for key,prop in spec['properties'].items():
        value=body[key]
        if prop['type']=='boolean' and type(value) is not bool:raise ValueError('exact boolean required')
        if prop['type']=='string' and (not isinstance(value,str) or not prop.get('minLength',0)<=len(value)<=prop.get('maxLength',6000)):
            raise ValueError('bounded incident string required')
        if 'enum' in prop and value not in prop['enum']:raise ValueError('incident binding or authority drift')
        if prop['type']=='array' and (not isinstance(value,list) or any(not isinstance(v,str) for v in value)
                or len(value)!=len(config['evidence']['facts']) or set(value)!=set(config['evidence']['facts'])):
            raise ValueError('all verified fact identities required')
    return body


def reconcile(private,evidence,*,instance='delivery-kit-port2',effects=None):
    """One effect intent per occurrence; uncertain acknowledgment is lookup-only."""
    evidence=validate_evidence(evidence);fx=effects or Effects(instance);private=Path(private)
    if private.is_symlink() or not private.is_dir():raise ValueError('private incident root required')
    directory=private/'r3-incidents'
    if directory.is_symlink():raise ValueError('unsafe incident directory')
    directory.mkdir(mode=0o700,exist_ok=True)
    identity=digest(evidence);path=directory/(identity+'.json')
    descriptor=os.open(directory/(identity+'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'w') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        saved=read(path) if path.exists() or path.is_symlink() else None
        if saved:
            config,state=saved['config'],saved['state']
            if config['evidence']!=evidence or config['evidence_sha256']!=identity:raise ValueError('immutable incident drift')
        else:
            actors=fx.binding(evidence)
            if (set(actors)!={'techlead','cto'} or not all(isinstance(v,str) and v for v in actors.values())
                    or actors['techlead']==actors['cto']):raise ValueError('independent technical roles required')
            config=dict(evidence=evidence,evidence_sha256=identity,**actors)
            state=dict(stage='issue_intent',owner='techlead',incident_sha256=identity,
                       execution_authorized=False,release_homologated=False,started_at=fx.now())
            if 'experiment_history' in evidence:
                state.update(owner='cto',escalated=True,post_experiment=True)
        def save(value):
            save_receipt(path,dict(config=config,state=value));return value
        def hold(category):
            if state['stage']=='awaiting_diagnose' and not state.get('escalated'):
                return save({**state,'stage':'diagnose_dispatch','owner':'cto','escalated':True,
                    'escalation':dict(category=category,prior_wakeup=state['wakeup_id'],prior_task=state.get('task_id')),
                    'category':category,'next_action':'CTO diagnosis of failed Tech Lead attention; no repeat of prior action'})
            return save({**state,'stage':'blocked','owner':'cto','category':category,
                'next_action':'reconcile exact technical incident; no identical dispatch or controller relaunch'})
        if state['stage'] in ('blocked','experiment_pending','resume_verification_pending','credentials_required','retained_hold'):
            return state
        now=fx.now()
        if state['stage'] in ('issue_intent','observe_issue'):
            create=state['stage']=='issue_intent'
            if create:state=save({**state,'stage':'observe_issue','observation_started':now})
            try:item=fx.issue(config,allow_create=create)
            except (TimeoutError,OSError):
                return hold('incident_issue_unobservable') if now-state['observation_started']>=1800 else state
            if not item:
                return hold('incident_issue_missing') if now-state['observation_started']>=1800 else state
            if not isinstance(item.get('id'),str) or not item['id']:return hold('incident_issue_identity_invalid')
            return save({**state,'stage':'diagnose_dispatch','issue_id':item['id']})
        if state['stage'] in ('diagnose_dispatch','review_dispatch','observe_diagnose','observe_review'):
            phase='review' if 'review' in state['stage'] else 'diagnose'
            create=state['stage'].endswith('_dispatch')
            if create:
                if fx.remaining()<16:
                    return save({**state,'category':'model_budget_reserve_unavailable','attention_required':True})
                state=save({**state,'stage':'observe_'+phase,'observation_started':now})
            try:wake=fx.wake(config,state,instruction(config,state),allow_create=create)
            except (TimeoutError,OSError):
                return hold('incident_dispatch_unobservable') if now-state['observation_started']>=1800 else state
            if not wake:
                return hold('incident_dispatch_missing') if now-state['observation_started']>=1800 else state
            if not isinstance(wake.get('id'),str) or not wake['id']:return hold('incident_wakeup_identity_invalid')
            return save({**state,'stage':'awaiting_'+phase,'wakeup_id':wake['id'],
                'owner':('techlead' if phase=='review' else 'cto') if state.get('escalated') else
                        ('cto' if phase=='review' else 'techlead'),'dispatched_at':state['observation_started'],
                'category':None,'attention_required':False})
        runs=fx.runs(config,state)
        matching=[r for r in runs if r.get('wakeup_id')==state['wakeup_id']]
        if len(matching)>1:return hold('duplicate_incident_execution')
        age=now-state['dispatched_at']
        if not matching or matching[0].get('status') in ('queued','running'):
            if age>=1800:return hold('incident_execution_deadline')
            return save({**state,'attention_required':age>=600})
        state={**state,'task_id':matching[0]['id']}
        try:decision=validate_decision(config,state,fx.task(config,state,state['task_id']))
        except (ValueError,TypeError,KeyError):return hold('invalid_incident_submission')
        if state['stage']=='awaiting_diagnose':
            if ((decision['action']=='request_experiment' and decision['experiment']=='none')
                    or (decision['action']!='request_experiment' and decision['experiment']!='none')):
                return hold('inconsistent_incident_operation')
            if decision['action']=='request_experiment' and decision['experiment'] in evidence.get('experiment_history',[]):
                return hold('experiment_repeated_without_new_inputs')
            return save({**state,'stage':'review_dispatch','owner':'techlead' if state.get('escalated') else 'cto','proposal':decision,
                'proposal_sha256':digest(decision),'diagnosis_task':state['task_id'],'diagnosis_wakeup':state['wakeup_id']})
        proposal=state['proposal']
        outcome='retained_hold'
        if decision['decision']=='approve_experiment' and proposal['action']=='request_experiment' and proposal['experiment']!='none':
            outcome='experiment_pending'
        elif decision['decision']=='approve_resume' and proposal['action']=='propose_resume':outcome='resume_verification_pending'
        elif proposal['action']=='request_credentials' and decision['decision']=='confirm_credentials_dependency':outcome='credentials_required'
        return save({**state,'stage':outcome,'review':decision,'review_task':state['task_id'],
                     'next_action':'fixed controller verification required; no execution authority from agent text'})


def supervise(private,parent,publication,*,instance='delivery-kit-port2',effects=None,contract=None):
    """Use only the persisted exact R3 intake and matching controller hold."""
    if publication.get('stage')!='blocked':return None
    category=publication.get('category')
    if category not in CATEGORIES:raise ValueError('known R3 incident category required')
    directory=Path(private)/'remediation-publication'
    if directory.is_symlink():raise ValueError('unsafe R3 incident intake directory')
    matches=[]
    for path in directory.glob('REMEDIATION*.json'):
        if path.name.endswith(('.run.json','.parent.json','.controller.json')):continue
        intake=read(path)
        if intake.get('bundle',{}).get('context',{}).get('remediation_parent')==parent:matches.append((path,intake))
    if len(matches)!=1:raise ValueError('one exact incident intake required')
    path,intake=matches[0];value=intake['bundle'];context=value['context']
    saved=read(path.with_name(context['label']+'.controller.json'))
    if (saved!=publication or intake.get('stage')!='prepared' or intake.get('bundle_sha256')!=digest(value)
            or value.get('execution_authorized') is not False or value.get('release_homologated') is not False):
        raise ValueError('actual nonauthorizing persisted R3 hold required')
    proof=context['remediation_expected']
    evidence=dict(operation='r3_incident_evidence_v1',root_issue=parent['issue_id'],source_task=proof['source_task'],
        controller_identity=saved['identity'],bundle_sha256=digest(value),r2_proof_sha256=digest(proof),category=category,
        facts={'F01':CATEGORIES[category],'F02':'delivery_not_verified'},execution_authorized=False,release_homologated=False)
    incident=reconcile(private,evidence,instance=instance,effects=effects)
    if incident.get('stage')=='experiment_pending':
        from r3_post_experiment import drive
        incident=drive(private,evidence,incident,value,instance=instance,effects=effects,contract=contract)
    return incident
