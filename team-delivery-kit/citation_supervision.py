"""Evidence-bound supervision reentry after one immutable citation repair."""
import hashlib
import json
from pathlib import Path
import subprocess
import time

TEST_CATEGORY='test_revision_blocked:invalid_independent_test_review:ValueError'
CONTEXT_CATEGORY='test_revision_recovery:ValueError:execution context reference mismatch'


def eligible(status, managed):
    if (not status or status.get('stage')!='escalation_required' or status.get('category') not in (TEST_CATEGORY,CONTEXT_CATEGORY)
            or not managed or managed.get('route',{}).get('enabled') is not True
            or managed['route'].get('issue_id')!=status.get('issue_id')):return False
    state=managed.get('state') or {};data=json.loads(state.get('data','{}'))
    if state.get('stage') not in ('awaiting_test_revision_review','test_revision_approved',
                                  'test_review_cto_diagnosis','test_revision_required'):return False
    repair=data.get('citation_recovery') or {};prior=repair.get('prior_state') or {}
    if status.get('category')==CONTEXT_CATEGORY:
        from execution_context import validate
        try:validate(managed['route'].get('execution_context'))
        except (ValueError,TypeError):return False
        if state.get('stage')!='test_revision_required' or not data.get('protocol_diagnosis'):return False
    return (repair.get('approval') is False and repair.get('author_restarted') is False
        and repair.get('attempt_limit')==1 and bool(repair.get('failed_task'))
        and prior.get('source_task')==state.get('source_task')
        and prior.get('manifest_sha256')==data.get('manifest_sha256')
        and prior.get('candidate_volume')==data.get('candidate_volume')
        and prior.get('review_failure',{}).get('detail')=='finding quote not observed at exact line')


def read_proof(context):
    from evalctl import PROJECT
    program='''import broker as b,json,native,test_revision_review as revision,sys
issue=sys.argv[1];settings=json.loads((b.STATE/'native.json').read_text())
with b.db() as c:
 row=c.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()
 route=c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
 red=c.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
 if not row or not route or not red:print('null');sys.exit()
 config,state=map(json.loads,row);route=json.loads(route[0]);red=json.loads(red[0])
repair=state.get('citation_recovery') or {};runs=native.issue_task_runs(settings,issue)
if not repair.get('prior_state') or not repair.get('invalid_decision'):print('null');sys.exit()
failed=next((r for r in runs if r['id']==repair.get('failed_task')),None)
paths=['/evidence/'+tree+'/'+name for tree in (('candidate',) if config.get('initial_review') else ('candidate','previous')) for name in route['test_first_files']]
if not failed:print('null');sys.exit()
expected=revision.prepare_citation_recovery(repair['prior_state'],red,failed,config['reviewer'],repair['invalid_decision'],paths)
fresh=[r for r in runs if r.get('agent_id')==config['reviewer'] and r.get('wakeup_id')==state.get('wakeup_id') and r['id']!=failed['id']]
task=fresh[0] if len(fresh)==1 else {}
diagnosis=state.get('rejection_diagnosis') or {};protocol=state.get('protocol_diagnosis') or {}
cto=[r for r in runs if r.get('agent_id')==route['cto'] and r.get('wakeup_id')==diagnosis.get('wakeup_id')]
cto=cto[0] if len(cto)==1 else {}
protocol_active=(protocol.get('operation')=='invalid_review_citation_escalation_v1'
 and protocol.get('approval') is False and protocol.get('author_restarted') is False
 and protocol.get('failed_task')==task.get('id') and route['cto'] not in (route['author'],config['reviewer'])
 and diagnosis.get('target')==route['cto'] and diagnosis.get('status') in ('awaiting_cto','revision_required')
 and bool(cto.get('id')) and cto.get('status') in ('queued','dispatched','running','completed')
 and (diagnosis.get('status')!='revision_required' or
      diagnosis.get('decision_task')==cto['id'] and cto['status']=='completed'
      and (diagnosis.get('decision') or {}).get('action')=='request_test_revision'))
print(json.dumps(dict(qualified=expected.get('citation_recovery')==repair,issue_id=issue,
 enabled=route.get('enabled'),contract_sha256=route.get('contract_sha256'),source_task=red['task_id'],
 source_status=next((r['status'] for r in runs if r['id']==red['task_id']),None),
 manifest_sha256=state.get('manifest_sha256'),candidate_volume=state.get('candidate_volume'),
 frozen_manifest=red['red']['manifest_sha256'],frozen_volume=red['volume'],
 reviewer=config['reviewer'],independent=config['reviewer']==route['techlead'] and config['reviewer']!=route['author'],
 approval=repair.get('approval'),author_restarted=repair.get('author_restarted'),
 review_task=task.get('id'),review_status=task.get('status'),review_wakeup=task.get('wakeup_id'),
 wakeup=state.get('wakeup_id'),state_status=state.get('status'),decision=state.get('decision'),
 protocol_active=protocol_active,repair=repair)))'''
    return json.loads(subprocess.check_output(['docker','exec','-e','PYTHONPATH=/',
        PROJECT+'-execution-broker-1','python','-c',program,context['issue_id']],text=True))


def resume(ledger, plan, private, *, query=read_proof, verify_initial=None, read_delivery=None,
           verify=None, verify_ci=None):
    from dependent_sequence import (read_json, receipt_identity, verify_initial_review_base,
        read_stage_delivery, verify_predecessor, verify_recovery_ci)
    labels=[s['spec']['label'] for s in plan['stages']];label=ledger.get('active')
    if (ledger.get('stage')!='blocked' or ledger.get('plan_sha256')!=plan['sha256']
            or ledger.get('category') not in ('RuntimeError:'+TEST_CATEGORY,'RuntimeError:'+CONTEXT_CATEGORY)
            or label not in labels):return None
    index=labels.index(label)
    if ledger.get('completed')!=labels[:index]:return None
    stage=plan['stages'][index];context=read_json(Path(private)/('portable-context-'+label+'.json'))
    contract_sha=hashlib.sha256(json.dumps(stage['contract'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if (not context or context.get('issue_id')!=ledger.get('issues',{}).get(label)
            or context.get('label')!=label or context.get('contract_sha256')!=contract_sha
            or not context.get('durable_handoffs')):return None
    proof=query(context) or {}
    valid_state=(proof.get('state_status') in ('awaiting_review','approved')
        or proof.get('state_status')=='blocked' and (
            (proof.get('decision') or {}).get('action')=='reject_test_revision'
            or proof.get('protocol_active') is True))
    if (proof.get('qualified') is not True or proof.get('enabled') is not True
            or proof.get('issue_id')!=context['issue_id'] or proof.get('contract_sha256')!=contract_sha
            or proof.get('independent') is not True or proof.get('source_status')!='completed'
            or proof.get('approval') is not False or proof.get('author_restarted') is not False
            or not proof.get('review_task') or proof.get('review_task')==proof.get('source_task')
            or proof.get('review_status') not in ('queued','dispatched','running','completed')
            or not proof.get('wakeup') or proof.get('review_wakeup')!=proof['wakeup'] or not valid_state
            or proof.get('manifest_sha256')!=proof.get('frozen_manifest') or not proof.get('frozen_manifest')
            or proof.get('candidate_volume')!=proof.get('frozen_volume') or not proof.get('frozen_volume')):return None
    if index==0:(verify_initial or verify_initial_review_base)(context,stage)
    else:
        prior=plan['stages'][index-1];receipt=(read_delivery or read_stage_delivery)(private,prior)
        if not receipt_identity(receipt,prior) or receipt.get('merge_sha')!=context.get('base_sha'):return None
        (verify or verify_predecessor)(receipt,prior,allow_advanced_main=False,require_live_qa=True)
        (verify_ci or verify_recovery_ci)(receipt,prior)
    event=dict(stage_label=label,source_task=proof['source_task'],review_task=proof['review_task'],
               category=ledger['category'],status='supervision_resumed_not_delivered',at=time.time())
    return {**ledger,'stage':'working','updated_at':time.time(),
            'recovery_supervision':[*ledger.get('recovery_supervision',[]),event]}
