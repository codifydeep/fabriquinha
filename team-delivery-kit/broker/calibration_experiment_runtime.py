"""One CTO design and independent Lead decision after an insufficient SPIKE.

Only permits preparation of untrusted control data. Existing fixed calibration
executors, TDD, review and delivery gates retain their exclusive authority.
"""
import json
import urllib.error
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from generic_harness_calibration import digest,require
import calibration_experiment_contract as contract
import structured_rejection_receipts


def context(cfg,s,phase):
    return contract.context(phase,digest(cfg['source']),digest(s['decision']),
        digest(s['experiment']['proposal']) if phase=='review' else digest(None))


def instruction(cfg,s,phase):
    c=cfg['source'];note=contract.capsule(context(cfg,s,phase))
    note+=('CTO EXPERIMENT DESIGN. Resolve the Lead hold through a genuinely different experiment, not a repeat of the readFileSync SPIKE. '
        if phase=='design' else 'INDEPENDENT LEAD EXPERIMENT PLAN REVIEW. Do not demand completed experimental results before allowing their preparation. ')
    note+=('No tools, commands, product edits, author restart or delivery approval. The old SPIKE only measured Path binding. '
        'Design a reference-fixture experiment using the frozen full Python/Node harness, positive controls and criterion-specific negative controls. '
        'A permit allows ONE untrusted data proposal, not execution or approval. Actual full harness results must subsequently pass existing calibration gates. '
        'Do not weaken tests or acceptance; no product-specific controller special cases. If the adapter cannot support the design, select '
        +('needs_engineering_capability' if phase=='design' else 'retain_technical_hold')+'. '
        'Return exact JSON; reason<=200 chars.\nLead hold: '+s['decision']['value']['reason']+
        '\nAcceptance: '+json.dumps(c['criteria'],separators=(',',':'))+
        '\nFrozen methods: '+json.dumps(c['prepared']['test_methods'],separators=(',',':')))
    if phase=='design':
        note+='\nState hypothesis, method<=220 chars and expected_evidence. Describe a falsifiable experiment, not a claimed result.'
    else:note+='\nCTO proposal (unexecuted; exact receipt hash bound above): '+json.dumps(
        {k:s['experiment']['proposal']['value'][k] for k in ('hypothesis','method','expected_evidence')},separators=(',',':'))
    correction=s.get('experiment',{}).get('format_recoveries',{}).get(phase)
    if correction:
        note+='\nFORMAT CORRECTION ONLY: prior response rejected for maxLength. reason/hypothesis <=100 chars; method/expected_evidence <=120 chars. Same schema, no tools or approval. Receipt '+digest(correction['proof'])+'.'
    require(len(note)<=3800);return note


def advance(con,cfg,s,fx,*,now):
    c=cfg['source'];e=s.setdefault('experiment',dict(stage='design_dispatch',started=now))
    def save(**updates):
        e.update(updates);s.update(owner=c['cto'] if e['stage'].startswith('design') else c['reviewer'],
            required_action='Technical experiment '+e['stage']+'; no author restart, test execution or delivery approval')
        con.execute('UPDATE calibration_objections SET state=? WHERE issue_id=? AND author_task=?',
            (json.dumps(s,sort_keys=True),c['issue_id'],c['author_task']));con.commit();return s
    def hold(category,owner):
        result=save(stage='blocked',category=category);s.update(owner=owner,category=category,
            required_action='CTO resolve '+category+' with a new implementation capability; this experiment budget is spent')
        con.execute('UPDATE calibration_objections SET state=? WHERE issue_id=? AND author_task=?',
            (json.dumps(s,sort_keys=True),c['issue_id'],c['author_task']));con.commit();return result
    def recover_format(task,phase):
        histories=e.get('format_recoveries',{})
        if phase in histories:return hold('experiment_format_recovery_exhausted',c['cto'])
        proof=fx.experiment_format_rejection(cfg,s,task,phase)
        if proof is None:return hold('experiment_failure_needs_diagnosis',c['cto'])
        receipt=proof['receipt'];diagnostic=receipt['diagnostic']
        require(set(proof)=={'receipt','context_sha256'} and proof['context_sha256']==digest(context(cfg,s,phase))
            and receipt['category']=='schema_violation' and diagnostic['version']=='structured-constraint-v1'
            and diagnostic['constraints']==['maxLength'] and type(receipt['call_number']) is int and receipt['call_number']>0
            and all(receipt[k] is False for k in ('response_forwarded','worker_tool_executed','execution_authorized','delivery_approval')))
        require(structured_rejection_receipts.from_event(dict(event='model_proxy_request',status=502,
            category='structured_decision_response_invalid',execution_id=receipt['execution_id'],call_number=receipt['call_number'],
            structured_rejection_category=receipt['category'],structured_rejection_diagnostic=diagnostic))==receipt)
        entry=dict(proof=proof,failed_task=task['id'],old_wakeup=e['wakeup_id'],attempt_limit=1,
            execution_authorized=False,delivery_approval=False)
        s['category']='objection_hold_retained'
        return save(stage=phase+'_dispatch',format_recoveries={**histories,phase:entry})
    format_candidate=e['stage']=='blocked' and e.get('category') in ('experiment_evidence_rejected','experiment_native_failed')
    if e['stage']=='permitted' or (e['stage']=='blocked' and not format_candidate):return s
    try:
        fx.verify(cfg);fx.verify_decision(cfg,s)
        phase='design' if e['stage'].startswith('design') else 'review'
        if format_candidate:phase='review' if 'proposal' in e else 'design'
        actor=c['cto'] if phase=='design' else c['reviewer']
        require(c['cto']!=c['reviewer'])
        if format_candidate:
            matches=[t for t in fx.runs(cfg,s) if t.get('wakeup_id')==e['wakeup_id']]
            require(len(matches)==1 and matches[0].get('status')=='failed' and matches[0].get('agent_id')==actor
                and matches[0].get('issue_id')==s['issue_id'])
            return recover_format(matches[0],phase)
        note=instruction(cfg,s,phase)
        if e['stage'] in (phase+'_dispatch',phase+'_observe'):
            first=e['stage']==phase+'_dispatch'
            if first and not fx.reserve():return save(required_capacity=32)
            if first:save(stage=phase+'_observe',marker=digest(dict(context=context(cfg,s,phase),instruction=note)),started=now)
            try:wake=fx.experiment_wake(cfg,s,actor,note,first)
            except (TimeoutError,urllib.error.URLError):wake=None
            if wake is None:return hold('experiment_'+phase+'_unobserved',c['cto']) if now-e['started']>=600 else s
            return save(stage=phase+'_wait',wakeup_id=wake['id'])
        require(e['stage']==phase+'_wait')
        matches=[t for t in fx.runs(cfg,s) if t.get('wakeup_id')==e['wakeup_id']]
        require(len(matches)<=1)
        if not matches or matches[0].get('status') in ('queued','dispatched','running'):
            return hold('experiment_'+phase+'_deadline',c['cto']) if now-e['started']>=1800 else s
        task=matches[0];require(task.get('agent_id')==actor and task.get('issue_id')==s['issue_id'])
        if task.get('status')=='failed':return recover_format(task,phase)
        require(task.get('status')=='completed')
        decision=fx.experiment_decision(cfg,s,task,phase)
        require(decision['agent_id']==actor and decision['task_id']==task['id'])
        Draft202012Validator(contract.schema(context(cfg,s,phase))).validate(decision['value'])
        if phase=='design':
            save(proposal=decision)
            if decision['value']['action']=='needs_engineering_capability':return hold('experiment_requires_engineering_capability',c['cto'])
            return save(stage='review_dispatch')
        save(review=decision)
        if decision['value']['action']=='retain_technical_hold':return hold('experiment_plan_rejected',c['cto'])
        save(stage='permitted');s.update(stage='resume_pending',resume_started=now,
            required_action='Verify CTO experiment plan and independent Lead permit; prepare one untrusted fixture bundle')
        con.execute('UPDATE calibration_objections SET state=? WHERE issue_id=? AND author_task=?',
            (json.dumps(s,sort_keys=True),c['issue_id'],c['author_task']));con.commit();return s
    except (TimeoutError,urllib.error.URLError):
        return hold('experiment_evidence_observation_deadline',c['cto']) if now-e['started']>=1800 else save()
    except (ValueError,KeyError,TypeError,ValidationError):
        return hold('experiment_format_evidence_rejected' if format_candidate else 'experiment_evidence_rejected',c['cto'])


def verify(cfg,s,fx):
    e=s['experiment'];require(e['stage']=='permitted')
    for phase,key,actor,action in (('design','proposal','cto','propose_fixture_experiment'),('review','review','reviewer','permit_fixture_draft')):
        receipt=e[key];task=fx.plans.task(receipt['task_id'],cfg['source'][actor])
        require(fx.experiment_decision(cfg,s,task,phase)==receipt and receipt['value']['action']==action)
