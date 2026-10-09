"""One clarified CTO decision after verified self-referral, never a waiver."""
import hashlib
import json
from pathlib import Path

from portable_qa_protocol_recovery import digest, read
from release_eval import save_receipt
from qa_decision_authority import CONTRACT, VERSION, self_referral


def evidence(private, incident, prior, cli):
    from portable_qa_observation import previous
    old = previous(incident, prior, cli)
    if old is None:
        return None
    runs = cli('runs', prior['child_issue_id'])
    if len(runs) != 1 or runs[0]['id'] != old['task_id']:
        raise ValueError('authority clarification task drift')
    decision = json.loads(runs[0]['result']['output'])
    if digest(decision) != old['decision_sha256']:
        raise ValueError('authority clarification decision drift')
    if not self_referral(decision):
        return None
    from portable_browser_qa import script_for
    identity = old['browser_receipt']['identity']
    if identity.get('scenario_sha256') != hashlib.sha256(script_for(identity['config']).read_bytes()).hexdigest():
        raise ValueError('authority clarification requires unchanged QA evidence')
    delivery = read(Path(private)/'release-receipts'/(incident['label']+'.json'))
    if (delivery.get('issue_id') != incident['parent_issue_id']
            or delivery.get('merge_sha') != incident['source_sha']
            or identity.get('application_image') != delivery.get('deployment',{}).get('image_id')
            or delivery.get('deployment',{}).get('source_sha') != incident['source_sha']):
        raise ValueError('authority clarification product drift')
    return old


def validate(private, incident, proof):
    if (not isinstance(proof,dict)
            or read(Path(private)/'qa-authority-proofs'/(incident['key']+'.json')) != proof
            or proof.get('incident_key') != incident['key']
            or proof.get('source_sha') != incident['source_sha']
            or proof.get('contract_version') != VERSION
            or proof.get('contract_sha256') != hashlib.sha256(CONTRACT.encode()).hexdigest()
            or proof.get('delivery_approval') is not False
            or proof.get('author_retry_authorized') is not False):
        raise ValueError('durable non-authorizing role clarification required')


def recover(private, cli, *, incident, prior, parent_contract, budget_ready,
            observe=evidence):
    if incident.get('phase') != 'browser' or not budget_ready:
        return None
    old = observe(private, incident, prior, cli)
    if old is None:
        return None
    proof = {'incident_key':incident['key'],'source_sha':incident['source_sha'],
             'cto_id':prior['cto_id'],'previous':old,'contract_version':VERSION,
             'contract_sha256':hashlib.sha256(CONTRACT.encode()).hexdigest(),
             'delivery_approval':False,'author_retry_authorized':False}
    path = Path(private)/'qa-authority-proofs'/(incident['key']+'.json')
    if path.exists():
        if read(path) != proof:
            raise ValueError('one authority clarification per incident; replan required')
    else:
        save_receipt(path,proof)
    validate(private,incident,proof)
    from portable_qa_cto import record
    return record(private,cli,incident=incident,parent_contract=parent_contract,
                  cto_id=prior['cto_id'],reason='CTO decision referred its own technical authority',
                  budget_ready=True,authority_recovery=proof)
