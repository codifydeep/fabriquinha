"""Project proven R3 delivery to its root without approving failed snapshots."""
import re
from portable_remediation_intake import read,digest
from release_eval import save_receipt,approved_submission,command
from portable_remediation_gate import qualify


def verify_live(stage,receipt,bundle,*,instance):
    """Recheck native review, frozen R1/R2 proof, GitHub CI and local deploy."""
    evidence(bundle,receipt)
    selected=bundle['spec'];context=bundle['context']
    if approved_submission(receipt['issue_id'],selected['implementer_registry'],
                           selected['reviewer_registry'])!=receipt['delivery']:
        raise ValueError('current native delivery approval changed')
    qualify(command,instance,context,receipt['delivery'],previous=receipt['remediation_delivery'])
    from dependent_sequence import verify_predecessor,verify_recovery_ci
    child_stage={**stage,'spec':selected}
    verify_predecessor(receipt,child_stage,allow_advanced_main=False,require_live_qa=True)
    verify_recovery_ci(receipt,child_stage)


def evidence(bundle,receipt):
    context=bundle['context'];proof=context['remediation_expected'];sha=receipt.get('merge_sha')
    browser=receipt.get('browser_qa',{});deployment=receipt.get('deployment',{})
    if (bundle.get('operation')!='prepared_remediation_r3_bundle_v1'
            or any(receipt.get(k)!=v for k,v in context.items())
            or receipt.get('remediation_delivery')!=proof or receipt.get('delivery')!=proof['delivery']
            or receipt.get('stage')!='deployed_qa_passed'
            or not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{40}',sha)
            or type(receipt.get('pr_number')) is not int or receipt['pr_number']<1
            or not isinstance(receipt.get('pr_url'),str) or not receipt['pr_url'].startswith('https://github.com/')
            or not isinstance(receipt.get('main_ci_run'),str) or not receipt['main_ci_run']
            or receipt.get('frozen_tests',{}).get('status')!='passed'
            or receipt.get('board',{}).get('status')!='done'
            or deployment.get('status')!='passed' or deployment.get('source_sha')!=sha
            or not deployment.get('container') or not deployment.get('url')
            or browser.get('status')!='passed' or browser.get('cleanup')!='passed'
            or browser.get('automated') is not True or browser.get('identity',{}).get('source_sha')!=sha
            or browser.get('result',{}).get('source_sha')!=sha or browser.get('result',{}).get('status')!='passed'
            or bundle['spec'].get('browser_qa') is not None
               and browser.get('identity',{}).get('config')!=bundle['spec']['browser_qa']):
        raise ValueError('full exact-SHA R3 delivery and browser evidence required')
    return dict(operation='remediation_parent_delivery_v1',parent_issue=context['remediation_parent']['issue_id'],
        delivery_issue=context['issue_id'],delivery_label=context['label'],run_id=proof['run_id'],
        execution_contract_sha256=proof['execution_contract_sha256'],manifest_sha256=proof['delivery']['manifest_sha256'],
        receipt_sha256=digest(receipt),merge_sha=sha,pr_url=receipt['pr_url'],main_ci_run=receipt['main_ci_run'],
        qa_url=deployment['url'],original_depth=bundle['original_depth'],release_homologated=False)


def board_fields(proof):
    return dict(remediation_recovery='delivered_by_reviewed_r2',remediation_run_id=proof['run_id'],
        remediation_issue_id=proof['delivery_issue'],remediation_delivery_sha=proof['merge_sha'],
        remediation_delivery_manifest=proof['manifest_sha256'],remediation_receipt_sha256=proof['receipt_sha256'],
        remediation_pr_url=proof['pr_url'],remediation_main_ci_url=proof['main_ci_run'],remediation_qa_url=proof['qa_url'])


def publish(paths,receipt,cli,verify):
    """Live GitHub/CI/deployment verification is mandatory, before board writes."""
    if not callable(verify):raise ValueError('live delivery verifier required')
    intake=read(paths['intent']);bundle=intake['bundle']
    if intake.get('stage')!='prepared' or intake.get('bundle_sha256')!=digest(bundle):
        raise ValueError('durable exact prepared R3 intake required')
    proof=evidence(bundle,receipt);fields=board_fields(proof)
    parent=proof['parent_issue'];child=proof['delivery_issue']
    path=paths['intent'].with_name(proof['delivery_label']+'.parent.json')
    intent=dict(stage='parent_projection_intent',proof=proof,parent_context=bundle['context']['remediation_parent'])
    if path.exists() or path.is_symlink():
        if read(path) not in (intent,{**intent,'stage':'parent_projected'}):raise ValueError('parent projection drift')
    else:save_receipt(path,intent)
    verify(receipt,bundle)
    child_item=cli('get',child);child_meta=cli('metadata','list',child)
    parent_item=cli('get',parent);metadata=cli('metadata','list',parent)
    if (child_item.get('id')!=child or child_item.get('status')!='done'
            or child_meta.get('delivery_receipt_sha')!=proof['merge_sha']
            or child_meta.get('delivery_pr_url')!=proof['pr_url']
            or parent_item.get('id')!=parent or parent_item.get('status') not in ('todo','in_progress','blocked','done')
            or parent_item.get('assignee_id') not in (None,receipt['delivery']['author'])
            or any(k in metadata and metadata[k]!=v for k,v in fields.items())
            or parent_item.get('status')=='done' and any(metadata.get(k)!=v for k,v in fields.items())):
        raise ValueError('current uncancelled parent and exact child board evidence required')
    for key,value in fields.items():
        if key not in metadata:
            cli('metadata','set',parent,'--key',key,'--value',value,'--type','string')
    if parent_item.get('assignee_id') is not None:
        # Unassignment cannot start an agent; --no-start applies only to assignment.
        cli('assign',parent,'--unassign')
    current=cli('get',parent);current_meta=cli('metadata','list',parent)
    if (current.get('status') not in ('todo','in_progress','blocked','done') or current.get('assignee_id') is not None
            or any(current_meta.get(k)!=v for k,v in fields.items())):
        raise ValueError('parent state changed before completion')
    if current['status']!='done':cli('status',parent,'done','--no-start')
    if cli('get',parent).get('status')!='done':raise ValueError('parent completion acknowledgment missing')
    result={**intent,'stage':'parent_projected'};save_receipt(path,result)
    return result


def resolve(private,parent):
    """Read a projected receipt; retain the real R2 issue, label and delivery."""
    directory=private/'remediation-publication'
    if directory.is_symlink():raise ValueError('unsafe remediation publication directory')
    matches=[]
    for path in directory.glob('REMEDIATION*.parent.json'):
        projection=read(path)
        if projection.get('parent_context')==parent and projection.get('stage')=='parent_projected':
            matches.append((path,projection))
    if not matches:return None
    if len(matches)!=1:raise ValueError('ambiguous remediation parent delivery')
    path,projection=matches[0];proof=projection['proof'];label=proof['delivery_label']
    if not re.fullmatch(r'REMEDIATION[A-F0-9]{16}-1',label) or path.name!=label+'.parent.json':
        raise ValueError('invalid remediation publication identity')
    intake=read(directory/(label+'.json'));bundle=intake['bundle']
    if intake.get('stage')!='prepared' or intake.get('bundle_sha256')!=digest(bundle):
        raise ValueError('prepared remediation context drift')
    receipt=read(private/'release-receipts'/(label+'.json'))
    if evidence(bundle,receipt)!=proof or bundle['context']['remediation_parent']!=parent:
        raise ValueError('remediation parent evidence drift')
    return {**receipt,'recovery_parent':parent,'recovery_kind':'remediation','recovery_origin':proof}
