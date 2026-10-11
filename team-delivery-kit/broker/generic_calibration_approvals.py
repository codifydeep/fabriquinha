"""Native attestation/review of immutable controls; not a delivery approval.

Shares the producer workflow's persistent row. Every wakeup intent precedes
its effect; uncertain responses only observe the same marker. The final intake
still needs actual input probes and registration before calibration or TDD.
"""
import json
import time
import urllib.error

from generic_harness_calibration import digest
try:import generic_calibration_gate as gate
except ImportError:from broker import generic_calibration_gate as gate


def instruction(source,phase):
    from calibration_response_contract import context as make_context,capsule
    policy=source['policy'];context=source['context']
    action='propose_calibration' if phase=='attestation' else 'approve_calibration'
    note=('IMMUTABLE CALIBRATION POLICY '+phase.upper()+'. Read every listed file completely. '
        'Evaluate fixture independence, positive/negative sensitivity, all unchanged acceptance IDs '
        'and preservation of historical methods/assertions. This is not product review or TDD Red. '
        'Do not write, run tests, execute shell, change scope, approve delivery or ask the CEO technical questions. '
        'The controller independently verifies native reads, identities and AST inventories. '
        'If the policy is sound, return exactly one compact JSON object, no prose/fences: '+
        json.dumps(dict(action=action,policy_sha256=digest(policy),
            controls_manifest_sha256=policy['controls_manifest_sha256'],
            execution_authorized=False,delivery_approval=False),separators=(',',':'))+
        '\nIf unsound, return exactly {"action":"calibration_objection","reason":"concrete technical objection",'
        '"execution_authorized":false,"delivery_approval":false}; it becomes an owned hold, not approval.\n'+
        ''.join('READ FULL FILE: '+p+'\n' for p in gate.required_paths(policy,context)))
    note=capsule(make_context('attestation' if phase=='attestation' else 'review',
        gate.required_paths(policy,context),digest(source),digest(policy),policy['controls_manifest_sha256'],
        engine=policy['engine'] if policy['version']=='generic_harness_calibration_v2' else None))+note
    gate.require(len(note)<=4000)
    return note


def advance(con,c,fx,*,now=None):
    now=time.time() if now is None else now
    row=con.execute('SELECT config,state FROM generic_calibration_workflows WHERE issue_id=? AND author_task=?',
        (c['issue_id'],c['author_task'])).fetchone()
    gate.require(row and json.loads(row[0])==c);s=json.loads(row[1])
    if s['stage'] in ('blocked','inputs_ready'):return s
    def save(**changes):
        s.update(changes)
        con.execute('UPDATE generic_calibration_workflows SET state=? WHERE issue_id=? AND author_task=?',
            (json.dumps(s,sort_keys=True),c['issue_id'],c['author_task']));con.commit();return s
    def hold(category,action,**facts):
        return save(stage='blocked',category=category,owner=c['cto'],required_action=action,**facts)
    try:
        fx.verify(c);source=fx.approval_source(c,s)
        gate.require(digest(source['policy'])==s['policy_sha256'])
    except TimeoutError:return s
    except (ValueError,KeyError,TypeError):
        return hold('policy_source_rejected','CTO diagnose changed immutable bundle; no replacement dispatch')
    if s['stage']=='controls_ready':save(stage='policy_attestation_dispatch')
    phase='attestation' if s['stage'].startswith('policy_attestation_') else 'review'
    gate.require(s['stage'] in tuple('policy_'+phase+'_'+suffix for suffix in ('dispatch','observe','wait')))
    actor=c['cto'] if phase=='attestation' else c['reviewer']
    action='propose_calibration' if phase=='attestation' else 'approve_calibration'
    marker=digest(dict(config_sha256=digest(c),bundle_sha256=s['bundle_sha256'],
        policy_sha256=s['policy_sha256'],phase=phase,protocol='generic-calibration-approvals-v1'))
    if s['stage'].endswith(('dispatch','observe')):
        first=s['stage'].endswith('dispatch')
        if first and not fx.reserve(c):return save(required_action='Await proxy reserve before policy wakeup intent')
        try:note=instruction(source,phase)
        except (ValueError,KeyError,TypeError):
            return hold('policy_readonly_capsule_required','Controller provide complete readonly context; never truncate')
        if first:save(stage='policy_'+phase+'_observe',policy_marker=marker,policy_started=now,
            owner=actor,required_action='Observe exact native policy wakeup; no duplicate dispatch')
        gate.require(s['policy_marker']==marker)
        try:wake=fx.wake_policy(c,actor,note,marker,first)
        except (TimeoutError,urllib.error.URLError):wake=None
        if wake is None:
            if now-s['policy_started']>=600:
                return hold('policy_dispatch_unobserved','CTO diagnose unobserved policy wakeup; never repeat POST')
            return s
        gate.require(isinstance(wake.get('id'),str) and bool(wake['id']))
        return save(stage='policy_'+phase+'_wait',policy_wakeup=wake['id'],
            required_action=actor+' examine exact policy and controls; no execution authority')
    matches=[t for t in fx.runs(c) if t.get('wakeup_id')==s['policy_wakeup']]
    if len(matches)>1:return hold('policy_ambiguous_runs','CTO diagnose duplicate native policy tasks')
    if not matches or matches[0]['status'] in ('queued','dispatched','running'):
        age=now-s['policy_started']
        if age>=1800 or (not matches and age>=600):
            return hold('policy_progress_deadline','CTO inspect exact native policy task; no identical restart')
        return s
    task=matches[0]
    try:
        gate.require(task.get('agent_id')==actor and task['status']=='completed'
            and task['id'] not in (c['author_task'],s['producer_task'],s.get('attestation_task')))
        if not fx.ready(c,task):
            if now-s['policy_started']>=1800:
                return hold('policy_lease_deadline','CTO diagnose exact unclosed policy lease',observed_task=task['id'])
            return s
        task=fx.policy_task(c,task['id'],actor)
        artifact=gate.attest(source['policy'],source['context'],task,actor,s['policy_wakeup'],action,fx.policy_reads(task))
    except TimeoutError:return s
    except (ValueError,KeyError,TypeError):
        return hold('policy_native_decision_rejected','CTO diagnose exact native policy objection or invalid evidence',
            observed_task=task.get('id'))
    if phase=='attestation':
        return save(stage='policy_review_dispatch',attestation_task=task['id'],
            attestation_wakeup=s['policy_wakeup'],attestation_artifact=artifact,owner=c['reviewer'],
            required_action='Tech Lead independently review the same immutable bundle')
    try:
        proposal=fx.policy_task(c,s['attestation_task'],c['cto'])
        gate.require(fx.ready(c,proposal))
        context={**source['context'], 'proposal_wakeup':s['attestation_wakeup'],'review_wakeup':s['policy_wakeup']}
        qualified=gate.qualify(source['policy'],context,proposal,task,fx.policy_reads(proposal),fx.policy_reads(task))
        gate.require(qualified['approvals']['propose_calibration']==s['attestation_artifact'])
        intake=dict(policy=source['policy'],context=context,previous=source['previous'],
            proposal_task=proposal['id'],review_task=task['id'],
            probe_job_key=c['author_task']+':calibration-inputs:'+digest(source['policy']))
        fx.persist_intake(c,s,intake)
    except TimeoutError:return s  # Reconcile the same immutable intake after restart.
    except (ValueError,KeyError,TypeError):
        return hold('policy_intake_rejected','CTO diagnose exact independent approval binding; no stale approval reuse')
    return save(stage='inputs_ready',review_task=task['id'],review_artifact=artifact,
        intake_sha256=digest(intake),required_action='Controller run exact readonly input probe; not Red or delivery approval')
