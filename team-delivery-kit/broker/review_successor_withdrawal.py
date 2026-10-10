"""Retire an unstarted feedback plan for read-only review mediation.

No history or consumed round is removed. Parent implementation admission stays
blocked; only its immutable review route may be reconsidered.
"""
import copy


def prepare(config,state,route,red,review,parent_source,parent,admission,runs,wakeups):
    try:import technical_remediation_plan as plans
    except ImportError:from broker import technical_remediation_plan as plans
    feedback=config.get('r1_feedback',{})
    before=copy.deepcopy(parent);before.pop('superseded_by_feedback',None)
    if (set(state)!={'stage','owner','issue_id','identifier','execution_authorized','release_homologated'}
            or state.get('stage')!='plan_dispatch' or not state.get('issue_id')
            or state.get('owner')!=route['cto'] or state.get('execution_authorized') is not False
            or state.get('release_homologated') is not False or runs!=[] or wakeups!=[]
            or route.get('enabled') is not False
            or config.get('intake_kind')!='rejected_remediation_r1_v1'
            or config.get('source_task')!=red['task_id'] or config.get('source_issue')!=route['issue_id']
            or config.get('volume')!=red['volume'] or config.get('cto')!=route['cto']
            or config.get('reviewer')!=route['techlead']
            or feedback.get('previous_source')!=parent_source
            or type(feedback.get('round')) is not int or not 1<=feedback['round']<=2
            or feedback.get('operation')!='remediation_r1_review_feedback_v1'
            or feedback.get('execution_authorized') is not False
            or feedback.get('revision_depth_reset') is not False
            or feedback.get('review_task')!=review.get('review_task')
            or feedback.get('review_decision_sha256')!=plans.digest(review.get('decision'))
            or feedback.get('certificate')!=review.get('technical_replan_certificate')
            or config.get('diagnostic_decision')!=review.get('rejection_diagnosis',{}).get('decision')
            or parent.get('stage')!='r1_base_qualified' or parent.get('issue_id')!=route['issue_id']
            or parent.get('execution_authorized') is not False or parent.get('r1_gate')
            or parent.get('superseded_by_feedback')!={'source_task':red['task_id'],'config_sha256':plans.digest(config)}
            or plans.digest(before)!=feedback.get('previous_execution_sha256')
            or admission.get('stage')!='blocked' or admission.get('category')!='superseded_by_r1_feedback'
            or admission.get('next_source')!=red['task_id'] or not admission.get('superseded_admission')):
        raise ValueError('exact unstarted feedback successor and held parent required')
    proof=dict(operation='unstarted_feedback_successor_withdrawal_v1',
        source_task=red['task_id'],issue_id=state['issue_id'],parent_source=parent_source,
        config_sha256=plans.digest(config),prior_config=copy.deepcopy(config),prior_state=copy.deepcopy(state),
        prior_parent=copy.deepcopy(parent),prior_admission=copy.deepcopy(admission),prior_route=copy.deepcopy(route),
        consumed_feedback_round=feedback['round'],tasks_observed=0,wakeups_observed=0,
        revision_depth_reset=False,author_restarted=False,delivery_approval=False)
    held={**copy.deepcopy(state),'stage':'blocked','category':'withdrawn_for_immutable_review_mediation',
        'required_action':'CTO mediate predecessor review; no dispatch from this preserved successor',
        'review_mediation_withdrawal':proof}
    return held,proof
