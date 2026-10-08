"""A reviewed hold may be reassessed once with a qualified capability catalogue."""
import hashlib
import json
from pathlib import Path
from portable_remediation_intake import digest, read
from release_eval import command, save_receipt
from r3_incident_capabilities import OPERATIONS, sha


def recover(private,evidence,state,*,instance='delivery-kit-port2'):
    from r3_incident_runtime import Effects,validate_decision
    fact='fixed_incident_capability_catalogue_qualified'
    if (state.get('stage')!='retained_hold' or fact in evidence.get('facts',{}).values()
            or 'experiment_history' in evidence):return None
    root=Path(private);saved=read(root/'r3-incidents'/(digest(evidence)+'.json'))
    if saved['state']!=state or saved['config']['evidence']!=evidence:
        raise ValueError('current independently reviewed hold required')
    config=saved['config'];fx=Effects(instance)
    author=dict(state,stage='awaiting_diagnose',task_id=state['diagnosis_task'],wakeup_id=state['diagnosis_wakeup'])
    reviewer=dict(state,stage='awaiting_review',task_id=state['review_task'])
    proposal=validate_decision(config,author,fx.task(config,author,author['task_id']))
    review=validate_decision(config,reviewer,fx.task(config,reviewer,reviewer['task_id']))
    if (proposal!=state['proposal'] or review!=state['review']
            or proposal['action']!='retain_hold' or proposal['experiment']!='none'
            or review['decision'] not in ('retain_hold','request_changes')
            or review['proposal_sha256']!=digest(proposal)):
        return None
    proof=json.loads(command('docker','exec','-w','/',instance+'-execution-broker-1','python','-c',
        'import json,hashlib;from pathlib import Path;import r3_incident_capabilities as c;'
        'print(json.dumps(dict(catalogue_sha256=c.sha(),operations=c.OPERATIONS,'
        'module_sha256=hashlib.sha256(Path(c.__file__).read_bytes()).hexdigest(),execution_authorized=False)))'))
    module_sha=hashlib.sha256(Path(__file__).with_name('r3_incident_capabilities.py').read_bytes()).hexdigest()
    if proof!=dict(catalogue_sha256=sha(),operations=OPERATIONS,module_sha256=module_sha,execution_authorized=False):
        raise ValueError('installed fixed capability catalogue drift')
    receipt=dict(operation='qualified_incident_capability_reassessment_v1',incident_sha256=digest(evidence),
        diagnosis_task=author['task_id'],review_task=reviewer['task_id'],proposal_sha256=digest(proposal),
        review_sha256=digest(review),catalogue=proof,original_hold_preserved=True,
        execution_authorized=False,release_homologated=False)
    folder=root/'r3-capability-reassessments'
    if folder.is_symlink():raise ValueError('unsafe capability reassessment storage')
    path=folder/(digest(evidence)+'.json')
    if path.exists():
        if read(path)!=receipt:raise ValueError('immutable capability reassessment drift')
    else:save_receipt(path,receipt)
    return {**evidence,'facts':{**evidence['facts'],'F'+str(len(evidence['facts'])+1).zfill(2):fact}}
