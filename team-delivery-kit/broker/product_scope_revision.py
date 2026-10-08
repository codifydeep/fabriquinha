"""Pure policy for independently reviewed product-code scope amendments.

This module grants nothing. Runtime adapters must authenticate native task and
read receipts, persist qualification, materialize a new immutable contract and
enforce that contract before dispatch. A proposal or approval is not delivery.
"""
import copy
import hashlib
import json
import re
from portable_contract import validate, safe_path, is_test_path


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def validate_proposal(original, context, proposal):
    validate(original)
    keys={'operation','issue_id','source_task','contract_sha256','snapshot_sha256',
          'failure_output_sha256','write_files','reason'}
    if (not isinstance(proposal,dict) or set(proposal)!=keys
            or proposal['operation']!='propose_product_scope_revision_v1'
            or not isinstance(proposal['reason'],str) or not 1<=len(proposal['reason'])<=1200
            or len({context.get(k) for k in ('author','cto','reviewer')})!=3
            or any(not isinstance(context.get(k),str) or not context[k] for k in ('author','cto','reviewer'))
            or context.get('contract_sha256')!=digest(original)
            or any(proposal[k]!=context.get(k) for k in ('issue_id','source_task',
                'contract_sha256','snapshot_sha256','failure_output_sha256'))
            or any(not isinstance(proposal[k],str) or not re.fullmatch(r'[a-f0-9]{64}',proposal[k])
                for k in ('contract_sha256','snapshot_sha256','failure_output_sha256'))):
        raise ValueError('exact controller-bound scope proposal required')
    paths=proposal['write_files'];eligible=context.get('eligible_code_sha256')
    if (not isinstance(paths,list) or not 1<=len(paths)<=8
            or any(not isinstance(p,str) for p in paths) or len(set(paths))!=len(paths)
            or not isinstance(eligible,dict) or not set(paths)<=set(eligible)):
        raise ValueError('bounded observed dependency code paths required')
    for path in paths:
        safe_path(path)
        if (path not in original['protected_files'] or path in original['test_files']
                or any(is_test_path(path,root,original['test_command'][0]) for root in original['test_roots'])
                or not path.endswith('.py') or path.rsplit('/',1)[-1] in ('conftest.py','setup.py')
                or path.startswith(('.github/','.delivery-kit/','tests/','broker/'))
                or not isinstance(eligible[path],str) or not re.fullmatch(r'[a-f0-9]{64}',eligible[path])):
            raise ValueError('only observed protected Python product code may become editable')
    frozen=context.get('frozen_test_sha256')
    if (not isinstance(frozen,dict) or not frozen or not set(frozen)<=set(original['test_files'])
            or any(not isinstance(v,str) or not re.fullmatch(r'[a-f0-9]{64}',v) for v in frozen.values())):
        raise ValueError('frozen test identity required; scope cannot change tests')
    return copy.deepcopy(proposal)


def candidate_contract(original,context,proposal):
    proposal=validate_proposal(original,context,proposal)
    result=copy.deepcopy(original)
    paths=set(proposal['write_files'])
    result['protected_files']=sorted(set(original['protected_files'])-paths)
    result['editable_files']=sorted(set(original['editable_files'])|paths)
    validate(result)
    return result


def qualify_review(context,proposal,review,proposal_task,review_task,observed_read_hashes):
    if (not isinstance(review,dict) or set(review)!={'operation','proposal_sha256','decision','reason'}
            or review['operation']!='review_product_scope_revision_v1'
            or review['proposal_sha256']!=digest(proposal)
            or review['decision'] not in ('approve','request_changes')
            or not isinstance(review['reason'],str) or not 1<=len(review['reason'])<=1200
            or len({context.get(k) for k in ('author','cto','reviewer')})!=3
            or proposal_task.get('agent_id')!=context['cto']
            or review_task.get('agent_id')!=context['reviewer']
            or not proposal_task.get('id') or not review_task.get('id')
            or proposal_task['id']==review_task['id']
            or any(task.get('status')!='completed' or task.get('issue_id')!=context['issue_id']
                   for task in (proposal_task,review_task))
            or any(proposal.get(k)!=context.get(k) for k in ('issue_id','source_task',
                'contract_sha256','snapshot_sha256','failure_output_sha256'))):
        raise ValueError('independent completed review bound to this exact proposal required')
    files=proposal.get('write_files') or []
    if (not files or not isinstance(observed_read_hashes,dict)
            or any(path not in context.get('eligible_code_sha256',{})
                   or observed_read_hashes.get(path)!=context['eligible_code_sha256'][path] for path in files)):
        raise ValueError('observed independent reads of every proposed code dependency required')
    return dict(operation='qualified_product_scope_plan_v1',
        status='plan_approved' if review['decision']=='approve' else 'changes_requested',
        issue_id=context['issue_id'],source_task=context['source_task'],
        contract_sha256=context['contract_sha256'],snapshot_sha256=context['snapshot_sha256'],
        proposal_sha256=digest(proposal),proposal_task=proposal_task['id'],review_task=review_task['id'],
        write_files=list(files),frozen_test_sha256=copy.deepcopy(context['frozen_test_sha256']),
        delivery_approval=False,write_grant_issued=False)
