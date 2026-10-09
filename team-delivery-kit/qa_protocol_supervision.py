"""Resume sequence observation only after a bounded CTO protocol recovery."""
import json
from pathlib import Path

from provider_diagnosis_supervision import resume as shared_resume
from portable_qa_protocol_recovery import digest,read

CATEGORIES={'RuntimeError:ValueError:QA issue metadata drift: execution_gate',
            'RuntimeError:ValueError:QA gate delivery evidence drift',
            'RuntimeError:delivery_incomplete'}


def resume(ledger,plan,private,cli,*,query=None):
    if ledger.get('category') not in CATEGORIES:return None
    def reconcile(context):
        from portable_qa_incident import find
        from portable_qa_cto import find as find_cto,record
        from portable_qa_protocol_recovery import recover
        from prepare_issue_base import verified_main
        from start_eval import check_model_budget
        label=context['label']
        stage=next(s for s in plan['stages'] if s['spec']['label']==label)
        incident=find(private,context['issue_id'],label)
        if not incident or incident.get('phase')!='browser':return None
        original=find_cto(private,incident['key'])
        if not original:return None
        delivery=read(Path(private)/'release-receipts'/(label+'.json'))
        if (delivery.get('issue_id')!=context['issue_id']
                or delivery.get('merge_sha')!=incident['source_sha']
                or delivery.get('deployment',{}).get('source_sha')!=incident['source_sha']
                or delivery.get('contract_sha256')!=context['contract_sha256']
                or delivery.get('delivery',{}).get('author')==original['cto_id']
                or verified_main()!=incident['source_sha']):
            raise ValueError('exact unreleased QA delivery required for diagnosis recovery')
        check_model_budget()
        original=record(private,cli,incident=incident,parent_contract=stage['contract'],
            cto_id=original['cto_id'],reason=original['reason'],budget_ready=True)
        recovery=recover(private,cli,incident=incident,original=original,
            parent_contract=stage['contract'],budget_ready=True)
        if recovery and recovery.get('dispatch')=='cto_started':
            from portable_qa_observation import recover as recover_observation
            observed=recover_observation(private,cli,incident=incident,prior=recovery,
                parent_contract=stage['contract'],budget_ready=True)
            if observed:recovery=observed
        if not recovery or recovery.get('dispatch')!='cto_started':return None
        runs=cli('runs',recovery['child_issue_id'])
        if (len(runs)!=1 or runs[0].get('agent_id')!=original['cto_id']
                or runs[0].get('status') not in ('queued','dispatched','running','completed')):
            raise ValueError('one actual recovered CTO execution required')
        return {'qualified':True,'issue_id':context['issue_id'],
            'contract_sha256':context['contract_sha256'],'independent':True,
            'task_id':runs[0]['id'],'recovery_sha256':digest(recovery),
            'delivery_approval':False,'author_retry_authorized':False}
    return shared_resume(ledger,plan,private,query=query or reconcile,
        category=ledger['category'],record_key='qa_protocol_supervision')
