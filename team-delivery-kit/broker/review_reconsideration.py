"""Once-only CTO request for reconsideration, never an approval override.

The reviewer must independently inspect the exact unchanged delivery again.
All prior verdicts, diagnoses and recovery counters remain in the durable proof.
"""
import copy
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def upgrade_state(state,red,task):
    """New diagnosis contract; never reinterpret an old decision as a dispute."""
    prior=state.get('review_mediation_upgrade')
    if prior:
        if prior['decision_task']!=task['id'] or prior['manifest_sha256']!=red['red']['manifest_sha256']:
            raise ValueError('mediation upgrade already consumed or changed')
        return state
    diagnosis=state.get('rejection_diagnosis',{})
    if (state.get('status')!='blocked' or diagnosis.get('status')!='revision_required'
            or diagnosis.get('decision_task')!=task.get('id') or task.get('status')!='completed'
            or diagnosis.get('decision',{}).get('action')!='request_test_revision'
            or state.get('manifest_sha256')!=red['red']['manifest_sha256']
            or state.get('source_task')!=red['task_id']):
        raise ValueError('closed original diagnosis and exact unchanged Red required')
    result=copy.deepcopy(state)
    result['review_mediation_upgrade']=dict(operation='changed_readonly_mediation_contract_v1',
        decision_task=task['id'],decision_sha256=digest(diagnosis['decision']),
        manifest_sha256=state['manifest_sha256'],prior_state=copy.deepcopy(state),attempt_limit=1,
        limits_increased=False,author_restarted=False,delivery_approval=False)
    result['rejection_diagnosis']=dict(status='dispatch_intent',target=diagnosis['target'])
    # Preserve consumed recovery counters in active state as well as history.
    for key in ('schema_recovery','typed_transport_recovery'):
        if key in diagnosis:result['rejection_diagnosis'][key]=copy.deepcopy(diagnosis[key])
    result.pop('technical_replan_certificate',None)
    return result


def upgrade(b,issue,operation):
    """Administrative contract migration under sealed maintenance, no worker API."""
    try:import controller_maintenance as maintenance,native,handoff_runtime,test_revision_review,test_review_replan_certificate
    except ImportError:from broker import controller_maintenance as maintenance,native,handoff_runtime,test_revision_review,test_review_replan_certificate
    with b.LOCK:
        with b.db() as con:
            barrier=maintenance.current(con)
            if not barrier or barrier['stage']!='sealed' or barrier['operation_id']!=operation:
                raise ValueError('exact sealed maintenance required')
            config,state=map(json.loads,con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone())
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
            red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()[0])
            if not route.get('enabled') or con.execute('SELECT 1 FROM technical_remediation_plans WHERE source_task=?',(red['task_id'],)).fetchone():
                raise ValueError('unsuperseded original review required; preserve existing follow-up')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle upgrade required')
        if maintenance.native_active(b):raise ValueError('native idle required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        original=state.get('review_mediation_upgrade',{}).get('prior_state',state)
        diagnosis=original['rejection_diagnosis']
        task=native.task_record(settings,diagnosis['decision_task'],route['cto'])
        reviewer=native.task_record(settings,original['review_task'],config['reviewer'])
        if (reviewer.get('status')!='completed' or reviewer.get('issue_id')!=issue
                or fx.decision(reviewer)!=original['decision'] or fx.decision(task)!=diagnosis['decision']):
            raise ValueError('actual original decisions required')
        test_revision_review.validate_evidence(b,route,original,original['decision'])
        test_revision_review.validate_evidence(b,route,original,diagnosis['decision'])
        proof=test_review_replan_certificate.qualify(route,original,red,task,diagnosis['decision'],
            fx.read_evidence(task),config.get('initial_review',False))
        if original.get('technical_replan_certificate')!=proof:raise ValueError('qualified original diagnosis required')
        updated=upgrade_state(state,red,task)
        with b.db() as con:
            if json.loads(con.execute('SELECT state FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()[0])!=state:
                raise ValueError('review changed during upgrade')
        test_revision_review._save_rejection(b,route,updated)
    return dict(stage='dispatch_intent',limits_increased=False,delivery_approval=False,author_restarted=False)


def prepare(state,red,route,task,decision,reads,report,*,initial=False):
    prior=state.get('review_reconsideration')
    if prior:
        if (prior.get('decision_task')!=task.get('id')
                or prior.get('decision_sha256')!=digest(decision)
                or prior.get('manifest_sha256')!=red['red']['manifest_sha256']):
            raise ValueError('reconsideration already consumed or identity changed')
        return state
    diagnosis=state.get('rejection_diagnosis',{})
    paths=['/evidence/'+tree+'/'+name for tree in (('candidate',) if initial else ('candidate','previous'))
           for name in route['test_first_files']]
    if (state.get('status')!='blocked' or state.get('evidence_policy')!=1
            or state.get('terminal_contract')!='typed-review-v1'
            or not state.get('review_task') or state.get('decision',{}).get('action')!='reject_test_revision'
            or state.get('source_task')!=red['task_id'] or state.get('candidate_volume')!=red['volume']
            or red.get('issue_id')!=route['issue_id']
            or state.get('manifest_sha256')!=red['red']['manifest_sha256']
            or state['decision'].get('manifest_sha256')!=state['manifest_sha256']
            or report.get('summary',{}).get('candidate_manifest')!=state['manifest_sha256']
            or report.get('summary')!=state.get('comparison')
            or (not initial and (not state.get('previous_volume') or not report.get('previous')))
            or (initial and (state.get('previous_volume') or report.get('previous')))
            or len({route['author'],route['techlead'],route['cto']})!=3
            or task.get('status')!='completed' or task.get('issue_id')!=route['issue_id']
            or task.get('agent_id')!=route['cto'] or diagnosis.get('target')!=route['cto']
            or diagnosis.get('mediation_contract')!='immutable-review-reconsideration-v1'
            or task.get('id') in (state['review_task'],red['task_id'])
            or not task.get('wakeup_id') or task['wakeup_id']!=diagnosis.get('wakeup_id')
            or set(decision)!={'action','reason','optional_files','findings'}
            or decision.get('action')!='request_review_reconsideration' or decision.get('optional_files')!=[]
            or not isinstance(decision.get('reason'),str) or not 1<=len(decision['reason'])<=1200
            or not isinstance(decision.get('findings'),list) or not 1<=len(decision['findings'])<=3
            or any(f.get('kind')!='review_disagreement' for f in decision['findings'])
            or not paths or any(type(reads.get(p,{}).get('lines')) is not int
                or reads[p]['lines']<=0 or reads[p]['lines']!=reads[p].get('total_lines') for p in paths)):
        raise ValueError('independent same-snapshot fully observed reconsideration required')
    try:import test_review_facts
    except ImportError:from broker import test_review_facts
    test_review_facts.validate_findings(decision,report)
    result=copy.deepcopy(state)
    result['review_reconsideration']=dict(operation='immutable_review_reconsideration_v1',
        decision_task=task['id'],decision=decision,decision_sha256=digest(decision),
        original_review_task=state['review_task'],original_review_sha256=digest(state['decision']),
        manifest_sha256=state['manifest_sha256'],read_receipt_sha256=digest(reads),
        required_read_paths=paths,initial_review=initial,
        prior_state=copy.deepcopy(state),attempt_limit=1,author_restarted=False,
        test_changes_authorized=False,delivery_approval=False)
    result.update(status='dispatch_intent',challenge_retry=True)
    for key in ('review_task','decision','reason','wakeup_id','dispatched_at','marker',
                'read_evidence','rejection_diagnosis','technical_replan_certificate','review_failure'):
        result.pop(key,None)
    return result
