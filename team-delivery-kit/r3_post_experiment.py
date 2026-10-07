"""New immutable evidence -> CTO decision -> independent TL review. No restart."""
from portable_remediation_intake import digest,read
from r3_fixed_experiments import experiment_identity,validate_result
from r3_incident_runtime import validate_evidence,reconcile
from pathlib import Path

OBSERVATIONS=dict(controller_absent='experiment_controller_absent',controller_present='experiment_controller_present',
    controller_ambiguous='experiment_controller_ambiguous',snapshot_hashes_match='experiment_snapshot_intact',
    github_ci_exact_sha='experiment_github_ci_exact_sha',local_deployment_exact_sha='experiment_local_deployment_exact_sha',
    delivery_receipt_unavailable='experiment_delivery_unavailable')
FAILURES=dict(fixed_verification_failed='experiment_verification_failed',invalid_fixed_observation='experiment_verification_failed',
    independent_review_not_current='experiment_review_obsolete',independent_review_unobservable='experiment_review_unobservable',
    experiment_result_unobservable='experiment_result_unobservable')


def next_evidence(evidence,state,bundle,journal):
    validate_evidence(evidence)
    if (state.get('stage')!='experiment_pending' or state.get('incident_sha256')!=digest(evidence)
            or state.get('proposal_sha256')!=digest(state.get('proposal'))
            or state.get('proposal',{}).get('action')!='request_experiment'
            or state.get('review',{}).get('decision')!='approve_experiment'
            or state.get('execution_authorized') is not False or state.get('release_homologated') is not False
            or evidence['bundle_sha256']!=digest(bundle)
            or journal.get('operation')!='r3_fixed_experiment_v1'
            or journal.get('identity')!=experiment_identity(evidence,state,bundle)
            or journal.get('incident_sha256')!=digest(evidence)
            or journal.get('experiment')!=state['proposal']['experiment']
            or journal.get('execution_authorized') is not False or journal.get('release_homologated') is not False):
        raise ValueError('exact immutable reviewed experiment and original lineage required')
    if journal.get('stage')=='experiment_recorded':
        result=validate_result(journal.get('result'),journal['experiment'],bundle)
        if journal.get('result_sha256')!=digest(result):raise ValueError('recorded experiment result changed')
        fact=OBSERVATIONS[result['observation']];result_sha=digest(result)
    elif journal.get('stage')=='blocked' and journal.get('category') in FAILURES:
        fact=FAILURES[journal['category']]
        result_sha=digest(dict(stage='blocked',category=journal['category']))
    else:raise ValueError('terminal observed experiment required; not an uncertain acknowledgment')
    history=[*evidence.get('experiment_history',[]),journal['experiment']]
    if len(set(history))!=len(history) or len(history)>4:raise ValueError('distinct fixed operations required')
    facts={**evidence['facts'],'F'+str(len(evidence['facts'])+1).zfill(2):fact}
    revised={**evidence,'facts':facts,'previous_incident_sha256':digest(evidence),
        'experiment_receipt_sha256':digest(journal),'experiment_result_sha256':result_sha,'experiment_history':history}
    return validate_evidence(revised)


def reconcile_post(private,evidence,state,bundle,journal,*,instance='delivery-kit-port2',effects=None):
    """The receipt must exist exactly; a caller's claimed result is insufficient."""
    private=Path(private);directory=private/'r3-experiments'
    if directory.is_symlink():raise ValueError('unsafe experiment receipt directory')
    identity=experiment_identity(evidence,state,bundle)
    if read(directory/(identity+'.json'))!=journal:raise ValueError('exact persisted experiment receipt required')
    value=next_evidence(evidence,state,bundle,journal)
    return reconcile(private,value,instance=instance,effects=effects)


def drive(private,evidence,state,bundle,*,instance='delivery-kit-port2',effects=None,experiment_effects=None,contract=None):
    """Traverse preserved evidence, not a handoff counter or a fresh retry budget."""
    from r3_fixed_experiments import execute
    current=evidence;incident=state;projection=None
    while incident.get('stage')=='experiment_pending':
        journal=execute(private,current,incident,bundle,instance=instance,effects=experiment_effects,contract=contract)
        projection={k:journal[k] for k in ('stage','owner','category','identity','result_sha256') if k in journal}
        if journal.get('stage') not in ('experiment_recorded','blocked'):
            return {**incident,'experiment':projection}
        post=reconcile_post(private,current,incident,bundle,journal,instance=instance,effects=effects)
        current=next_evidence(current,incident,bundle,journal)
        incident=post
        # Every new transition appends a distinct member of the four fixed
        # operation types. A repeated operation is rejected by intake, not
        # interpreted as release completion or another execution attempt.
    return {**incident,'experiment':projection} if projection is not None else incident
