"""Once-only reviewed-hold reassessment after full probe evidence and fixed policy."""
from pathlib import Path
from portable_remediation_intake import read,digest
from release_eval import save_receipt
from r3_resume_contract import sha


def recover(private,incoming,bundle,*,instance='delivery-kit-port2'):
    if (incoming.get('stage')!='retained_hold' or not incoming.get('post_experiment')
            or incoming.get('resume_contract_reassessment_sha256')
            or incoming.get('proposal',{}).get('action')!='retain_hold'
            or incoming.get('review',{}).get('decision')!='retain_hold'):return None
    from r3_verified_resume import verify_lineage
    from r3_incident_runtime import Effects
    path=Path(private)/'r3-incidents'/(incoming['incident_sha256']+'.json')
    saved=read(path);state=saved['state'];config=saved['config'];evidence=config['evidence']
    if {k:v for k,v in incoming.items() if k!='experiment'}!=state:raise ValueError('exact persisted reviewed hold required')
    if (set(evidence.get('experiment_history',[]))!={'observe_existing_controller','verify_frozen_delivery','verify_github_ci','verify_local_deployment'}
            or not {'experiment_snapshot_intact','experiment_local_deployment_exact_sha',
                    'experiment_github_ci_exact_sha','experiment_controller_absent'}<=set(evidence['facts'].values())):return None
    verify_lineage(Path(private),evidence,bundle)
    selected=dict(state,stage='awaiting_review')
    result=Effects(instance).request('reassess',dict(config=config,state=selected));proof=result['proof']
    if (digest(proof)!=result['reassessment_sha256'] or proof.get('policy_sha256')!=sha()
            or proof.get('incident_sha256')!=digest(evidence) or proof.get('issue_id')!=state['issue_id']
            or proof.get('execution_authorized') is not False or proof.get('release_homologated') is not False):
        raise ValueError('installed conditional-resume policy qualification drift')
    if read(path)!=saved:raise ValueError('hold changed during reassessment')
    revised={**state,'stage':'diagnose_dispatch','owner':'cto','previous_reviewed_hold':state,
             'resume_contract_reassessment_sha256':result['reassessment_sha256']}
    for key in ('proposal','proposal_sha256','review','task_id','wakeup_id','review_task','diagnosis_task','diagnosis_wakeup',
                'category','next_action','dispatched_at','observation_started'):
        revised.pop(key,None)
    save_receipt(path,dict(config=config,state=revised))
    return revised
