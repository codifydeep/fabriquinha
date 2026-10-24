"""Default-off coordinator continuation, never publication or homologation.

Uses only persisted handoff/admission/job/attestation records. Waiting stages
remain active in the team coordinator and retain its observation deadline.
Product revision admission/launch and PR/CI/deploy remain separate unfinished
bridges; this source adapter must not be enabled in an installed product flow.
"""
import json
try:
    from . import quality_delivery_review_handoff as review,quality_delivery_review_validation as validation
    from . import quality_delivery_review_attestation as attestation,quality_delivery_revision as revision
except ImportError:
    import quality_delivery_review_handoff as review,quality_delivery_review_validation as validation
    import quality_delivery_review_attestation as attestation,quality_delivery_revision as revision

quality=review.quality
require=review.require
STAGES={'waiting_final_review_dispatch','awaiting_final_review_admission','waiting_final_review_validation',
    'waiting_final_review','waiting_product_revision_dispatch','awaiting_product_revision_admission','awaiting_publication'}


def outcome(stage,owner,evidence):
    return dict(stage=stage,owner=owner,evidence_sha256=quality.digest(evidence),execution_authorized=False,
        merge_authorized=False,delivery_approval=False)


def blocked(owner,evidence,category):
    return {**outcome('technical_blocked',owner,evidence),'incident':dict(category=category,automatic_retry=False,
        next_action='CTO diagnose original final-review/correction evidence; no replay or delivery gate waiver')}


def advance(b,request,techlead):
    review.enabled(b);review.enrollment.canonical(techlead)
    context,_=review.prepare(b,request);context,state=review.load(b,request)
    owner=context['reviewer'];stage='waiting_final_review_dispatch'
    try:
        if state['stage'] in ('prepared','dispatch_intent'):
            state=review.dispatch(b,request);require(review.load(b,request)[1]==state)
        if state['stage']=='technical_blocked':return blocked(context['cto'],state,'final_review_dispatch_blocked')
        if state['stage']=='awaiting_delivery_review_admission':
            settings=json.loads((b.STATE/'native.json').read_bytes())
            runs=[r for r in review.native.issue_task_runs(settings,context['issue_id']) if r.get('wakeup_id')==state['wakeup_id']]
            require(len(runs)<=1)
            if runs:
                require(runs[0].get('agent_id')==context['reviewer'] and runs[0].get('issue_id')==context['issue_id'])
                if runs[0].get('status') in ('failed','cancelled','completed'):
                    return blocked(context['cto'],runs[0],'final_review_ended_before_admission')
            return outcome('awaiting_final_review_admission',owner,state)
        require(state['stage']=='admitted');execution=state['request_id']
        stage='waiting_final_review_validation';old=validation.load(b,execution)
        if not old or old[1]['stage']!='review_validation_observed':
            result=validation.observe(b,execution);require(validation.load(b,execution)[1]==result)
            if result['stage']=='technical_blocked':return blocked(context['cto'],result,'final_review_validation_blocked')
            require(result['stage']=='review_validation_observed')
        stage='waiting_final_review';result=attestation.observe(b,execution)
        require(attestation.load(b,execution)==result)
        if result['stage']=='technical_blocked':return blocked(context['cto'],result,'final_review_attestation_blocked')
        if result['stage']=='delivery_reviewed':
            return {**outcome('awaiting_publication',techlead,result),
                'next_action':'bind this exact review/SHA to independent PR/CI, deploy, QA and rollback gates; not delivered'}
        require(result['stage']=='changes_requested');owner=context['author'];stage='waiting_product_revision_dispatch'
        corrected=revision.dispatch(b,execution);require(revision.load(b,execution)[1]==corrected)
        if corrected['stage']=='technical_blocked':return blocked(context['cto'],corrected,'product_revision_dispatch_blocked')
        require(corrected['stage']=='awaiting_product_revision_admission')
        return outcome('awaiting_product_revision_admission',owner,corrected)
    except review.validation_job.Pending as pending:
        return outcome(stage,owner,getattr(pending,'progress',dict(stage=stage)))
