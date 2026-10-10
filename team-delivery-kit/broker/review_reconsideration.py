"""Once-only CTO request for reconsideration, never an approval override.

The reviewer must independently inspect the exact unchanged delivery again.
All prior verdicts, diagnoses and recovery counters remain in the durable proof.
"""
import copy
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def prepare(state,red,route,task,decision,reads,report):
    prior=state.get('review_reconsideration')
    if prior:
        if (prior.get('decision_task')!=task.get('id')
                or prior.get('decision_sha256')!=digest(decision)
                or prior.get('manifest_sha256')!=red['red']['manifest_sha256']):
            raise ValueError('reconsideration already consumed or identity changed')
        return state
    diagnosis=state.get('rejection_diagnosis',{})
    paths=['/evidence/'+tree+'/'+name for tree in ('candidate','previous')
           for name in route['test_first_files']]
    if (state.get('status')!='blocked' or state.get('evidence_policy')!=1
            or state.get('terminal_contract')!='typed-review-v1'
            or not state.get('review_task') or state.get('decision',{}).get('action')!='reject_test_revision'
            or state.get('source_task')!=red['task_id'] or state.get('candidate_volume')!=red['volume']
            or red.get('issue_id')!=route['issue_id']
            or state.get('manifest_sha256')!=red['red']['manifest_sha256']
            or state['decision'].get('manifest_sha256')!=state['manifest_sha256']
            or report.get('summary',{}).get('candidate_manifest')!=state['manifest_sha256']
            or not state.get('previous_volume') or not report.get('previous')
            or len({route['author'],route['techlead'],route['cto']})!=3
            or task.get('status')!='completed' or task.get('issue_id')!=route['issue_id']
            or task.get('agent_id')!=route['cto'] or diagnosis.get('target')!=route['cto']
            or task.get('id') in (state['review_task'],red['task_id'])
            or not task.get('wakeup_id') or task['wakeup_id']!=diagnosis.get('wakeup_id')
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
        prior_state=copy.deepcopy(state),attempt_limit=1,author_restarted=False,
        test_changes_authorized=False,delivery_approval=False)
    result.update(status='dispatch_intent',challenge_retry=True)
    for key in ('review_task','decision','reason','wakeup_id','dispatched_at','marker',
                'read_evidence','rejection_diagnosis','technical_replan_certificate','review_failure'):
        result.pop(key,None)
    return result
