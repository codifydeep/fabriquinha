"""Resume observation of a qualified recovered incident, never its author."""
import hashlib
import json
from pathlib import Path
import subprocess


def recoverable(status):
    category=str((status or {}).get('category',''))
    return ((status or {}).get('stage')=='escalation_required' and
        (category.startswith('technical_decision_required:') or category in (
            'test_first_blocked:test_first_correction_failed_after_cto_diagnosis',
            'test_revision_recovery:ValueError:second test revision requires new technical replan')))


def eligible(status, managed):
    if (not recoverable(status)
            or not managed or managed.get('route',{}).get('enabled') is not True
            or managed['route'].get('issue_id')!=status.get('issue_id')):return False
    state=managed.get('state') or {};data=json.loads(state.get('data','{}'))
    if state.get('stage')=='test_revision_required' and data.get('technical_replan_certificate'):
        from portable_test_revision_recovery import next_revision_depth
        try:return next_revision_depth(dict(issue_id=status['issue_id']),managed,'1')=='2'
        except (ValueError,KeyError,TypeError):return False
    checkpoint=managed.get('failed_test_checkpoint') or {}
    if checkpoint:
        approved=(state.get('stage')=='test_revision_approved' and data.get('status')=='approved'
            and data.get('read_contract')=='complete-lines-v2'
            and data.get('decision',{}).get('action')=='approve_test_revision'
            and data['decision'].get('manifest_sha256')==data.get('manifest_sha256')
            and bool(data.get('review_task')))
        return (checkpoint.get('operation')=='failed_test_checkpoint_v1'
            and checkpoint.get('status')=='red_captured'
            and checkpoint.get('issue_id')==status.get('issue_id')
            and checkpoint.get('source_task')==state.get('source_task')==data.get('source_task')
            and checkpoint.get('delivery_approved') is False
            and checkpoint.get('native_task_completed') is False
            and (approved or (state.get('stage')=='awaiting_test_revision_review'
                and data.get('status') in ('dispatch_intent','awaiting_review')))
            and bool(data.get('manifest_sha256')))
    proof=data.get('diagnostic_presentation_recovery') or {}
    digest=hashlib.sha256(json.dumps(data.get('diagnostic') or {},sort_keys=True).encode()).hexdigest()
    postwrite=data.get('postwrite_diagnosis') or {};snapshot=postwrite.get('probe') or {}
    postwrite_valid=(postwrite.get('operation')=='postwrite_phase_diagnosis_v1'
        and postwrite.get('source_task')==state.get('source_task')
        and postwrite.get('issue_id')==status.get('issue_id')
        and postwrite.get('author_retry_authorized') is False and postwrite.get('delivery_approval') is False
        and snapshot.get('verified') is True and snapshot.get('baseline_unchanged') is True
        and snapshot.get('manifest_sha256')==data.get('diagnostic',{}).get('manifest_sha256'))
    presentation_valid=(proof.get('operation')=='bounded_pre_red_diagnostic_presentation_v1'
        and proof.get('source_task')==state.get('source_task')
        and proof.get('diagnostic_sha256')==digest
        and proof.get('approval') is False and proof.get('author_restarted') is False)
    capacity=data.get('read_capacity_diagnosis') or {};experiment=capacity.get('probe') or {}
    capacity_valid=(capacity.get('operation')=='read_capacity_diagnosis_v1'
        and capacity.get('source_task')==state.get('source_task')
        and capacity.get('issue_id')==status.get('issue_id')
        and capacity.get('author_retry_authorized') is False and capacity.get('delivery_approval') is False
        and experiment.get('baseline_unchanged') is True and experiment.get('all_lines_observed') is True
        and experiment.get('manifest_sha256')==data.get('diagnostic',{}).get('manifest_sha256'))
    return (state.get('stage') in ('test_first_cto_diagnosis','test_first_cto_correction',
                                  'test_first_cto_correction_wait')
        and data.get('phase')=='test_first'
        and (presentation_valid or postwrite_valid or capacity_valid)
        and (str(status.get('category','')).startswith('technical_decision_required:') or capacity_valid)
        and bool(data.get('test_first_cto_wakeup')))


def read_proof(context):
    from evalctl import PROJECT
    program='''import broker as b,json,native,sys,postwrite_diagnosis,read_capacity_diagnosis,failed_test_checkpoint,technical_replan_certificate,handoff_runtime
issue=sys.argv[1]
with b.db() as c:
 route=c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
 rows=c.execute('SELECT * FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC',(issue,)).fetchall()
 if route and rows:
  configuration=json.loads(route[0]);latest=dict(rows[0]);current=json.loads(latest['data'])
  certificate=current.get('technical_replan_certificate') or {}
  if latest['stage']=='test_revision_required' and certificate.get('operation')=='qualified_frozen_green_cto_replan_v1':
   settings=json.loads((b.STATE/'native.json').read_text());effects=handoff_runtime.Effects(b,settings)
   task=native.task_record(settings,certificate['decision_task'],configuration['cto'])
   observed=technical_replan_certificate.qualify(configuration,current,task,effects.decision(task),effects.read_evidence(task))==certificate
   print(json.dumps(dict(managed=dict(route=configuration,state=latest),issue_id=issue,
     contract_sha256=configuration['contract_sha256'],independent=configuration['cto']!=configuration['author'],
     qualified=observed,task=task['id'],delivery_approval=False,author_retry_authorized=False)));sys.exit()
  red=c.execute('SELECT task_id,receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
  trial=c.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()
  if red and trial:
   review_config,review_state=map(json.loads,trial)
   approved_checkpoint=failed_test_checkpoint.proof(c,issue,red['task_id'])
   red_receipt=json.loads(red['receipt'])
   if (approved_checkpoint and failed_test_checkpoint.qualified(c,issue,red['task_id'],red_receipt)
       and review_state.get('status')=='approved' and review_state.get('source_task')==red['task_id']
       and review_state.get('manifest_sha256')==red_receipt['red']['manifest_sha256']
       and latest['stage'] in ('author_active','ready_review','dispatch_intent','awaiting_acceptance','accepted','approved','ready_publish','published','qa_active','done')):
    runs=native.issue_task_runs(json.loads((b.STATE/'native.json').read_text()),issue)
    reviewed=[r for r in runs if r['id']==review_state.get('review_task') and r.get('status')=='completed'
        and r.get('agent_id')==review_config['reviewer'] and r.get('wakeup_id')==review_state.get('wakeup_id')]
    successors=[r for r in runs if r['id']==latest['source_task'] and r['id']!=red['task_id']
        and r.get('agent_id')==configuration['author'] and r.get('status') in ('queued','dispatched','running','completed')]
    original=[r for r in runs if r['id']==red['task_id'] and r.get('status')=='failed' and r.get('agent_id')==configuration['author']]
    projection=dict(source_task=red['task_id'],stage='test_revision_approved',data=json.dumps(review_state))
    print(json.dumps(dict(managed=dict(route=configuration,state=projection,failed_test_checkpoint=approved_checkpoint),
       issue_id=issue,contract_sha256=configuration['contract_sha256'],independent=review_config['reviewer']!=configuration['author'],
       qualified=len(reviewed)==len(successors)==len(original)==1,task=latest['source_task'],delivery_approval=False,author_retry_authorized=False)));sys.exit()
  checkpoint=failed_test_checkpoint.proof(c,issue,latest['source_task'])
  if checkpoint and red and failed_test_checkpoint.qualified(c,issue,red['task_id'],json.loads(red['receipt'])) and latest['stage']=='awaiting_test_revision_review' and current.get('status') in ('dispatch_intent','awaiting_review'):
   runs=native.issue_task_runs(json.loads((b.STATE/'native.json').read_text()),issue)
   sources=[r for r in runs if r['id']==red['task_id'] and r.get('agent_id')==configuration['author'] and r.get('status')=='failed']
   reviewers=[r for r in runs if r.get('wakeup_id')==current.get('wakeup_id') and r.get('agent_id')==configuration['techlead'] and r.get('status') in ('queued','dispatched','running','completed')]
   observed=bool(sources) and (current['status']=='dispatch_intent' or len(reviewers)==1)
   print(json.dumps(dict(managed=dict(route=configuration,state=latest,failed_test_checkpoint=checkpoint),issue_id=issue,contract_sha256=configuration['contract_sha256'],independent=configuration['techlead']!=configuration['author'],qualified=observed,task=reviewers[0]['id'] if reviewers else None,delivery_approval=False,author_retry_authorized=False)));sys.exit()
 recovered=[r for r in rows if any(json.loads(r['data']).get(k) for k in ('diagnostic_presentation_recovery','postwrite_diagnosis','read_capacity_diagnosis'))]
 if not route or not recovered:print('null');sys.exit()
 route=json.loads(route[0]);state=dict(recovered[0]);data=json.loads(state['data'])
 latest=dict(rows[0])
 certificate=not data.get('postwrite_diagnosis') or bool(postwrite_diagnosis.qualified(c,issue,state['source_task'],data))
 if data.get('read_capacity_diagnosis'):certificate=bool(read_capacity_diagnosis.qualified(c,issue,state['source_task'],data))
runs=native.issue_task_runs(json.loads((b.STATE/'native.json').read_text()),issue)
tasks=[r for r in runs if r.get('agent_id')==route['cto'] and r.get('wakeup_id')==data.get('test_first_cto_wakeup')]
task=tasks[0] if len(tasks)==1 else {}
active=task.get('status') in ('queued','dispatched','running') and state['stage']=='test_first_cto_diagnosis'
decided=task.get('status')=='completed' and data.get('cto_task')==task.get('id') and data.get('decision',{}).get('action')=='request_correction' and state['stage'] in ('test_first_cto_correction','test_first_cto_correction_wait')
authors=[r for r in runs if r.get('agent_id')==route['author']]
author=max(authors,key=lambda r:(r.get('created_at') or '',r['id'])) if authors else {}
if state['stage']=='test_first_cto_correction_wait':
 decided=decided and author.get('id')!=state['source_task'] and author.get('wakeup_id')==data.get('test_first_correction_wakeup') and author.get('status') in ('queued','dispatched','running','completed') and latest['stage'] not in ('test_first_blocked','technical_decision_required','diagnose_cto')
print(json.dumps(dict(managed=dict(route=route,state=state),issue_id=issue,
 contract_sha256=route['contract_sha256'],independent=route['cto']!=route['author'],
 qualified=certificate and bool(task.get('id')) and (active or decided),task=task.get('id'),
 delivery_approval=False,author_retry_authorized=False)))'''
    return json.loads(subprocess.check_output(['docker','exec','-e','PYTHONPATH=/',
        PROJECT+'-execution-broker-1','python','-c',program,context['issue_id']],text=True))


def qualified(status, context, *, query=read_proof):
    if not recoverable(status):return False
    proof=query(context) or {}
    return (proof.get('qualified') is True and proof.get('independent') is True
        and proof.get('issue_id')==context['issue_id']
        and proof.get('contract_sha256')==context['contract_sha256']
        and proof.get('delivery_approval') is False and proof.get('author_retry_authorized') is False
        and eligible(status,proof.get('managed')))


def resumed_projection(ledger,child_issue):
    """Keep the old incident in history, not in the live working status."""
    result={**ledger,'stage':'working','pre_red_supervision_recovery':dict(
        child_issue=child_issue,category=ledger['category'],owner=ledger.get('owner'),
        next_action=ledger.get('next_action'),delivery_approval=False)}
    for key in ('category','owner','next_action','board_notification_error'):
        result.pop(key,None)
    return result


def resume(ledger,plan,private,*,query=read_proof,read_delivery=None,verify=None,verify_ci=None):
    from dependent_sequence import read_json,receipt_identity,read_stage_delivery,verify_predecessor,verify_recovery_ci
    from portable_delivery import managed_handoff
    from portable_test_revision_recovery import child_spec
    labels=[s['spec']['label'] for s in plan['stages']];label=ledger.get('active')
    if (ledger.get('stage')!='blocked' or ledger.get('category')!='RuntimeError:delivery_incomplete'
            or ledger.get('plan_sha256')!=plan['sha256'] or label not in labels):return None
    index=labels.index(label)
    if index==0 or ledger.get('completed')!=labels[:index]:return None
    stage=plan['stages'][index];context=read_json(Path(private)/('portable-context-'+label+'.json'))
    if (not context or context.get('issue_id')!=ledger.get('issues',{}).get(label)
            or context.get('contract_sha256')!=hashlib.sha256(json.dumps(stage['contract'],
                sort_keys=True,separators=(',',':')).encode()).hexdigest()):return None
    root=Path(private)/'test-revision-recovery';path=root/(context['issue_id']+'.json')
    if path.is_symlink():raise ValueError('unsafe child recovery intent')
    intent=read_json(path) or {};spec=intent.get('spec') or {}
    if intent.get('parent_issue')!=context['issue_id'] or not spec.get('label'):return None
    if child_spec(context,stage['spec'],managed_handoff(context))!=spec:return None
    child=read_json(Path(private)/('portable-context-'+spec['label']+'.json'))
    status=read_json(Path(private)/'autonomy-status'/(spec['label']+'.json'))
    if (not child or child.get('issue_id')!=intent.get('child_issue')
            or child.get('base_sha')!=context.get('base_sha')
            or child.get('contract_sha256')!=context.get('contract_sha256')
            or child.get('run_spec_sha256')!=hashlib.sha256(json.dumps(spec,
                sort_keys=True,separators=(',',':')).encode()).hexdigest()
            or not qualified(status,child,query=query)):return None
    previous=plan['stages'][index-1];receipt=(read_delivery or read_stage_delivery)(private,previous)
    if not receipt_identity(receipt,previous) or receipt.get('merge_sha')!=context['base_sha']:return None
    (verify or verify_predecessor)(receipt,previous,allow_advanced_main=False,require_live_qa=True)
    (verify_ci or verify_recovery_ci)(receipt,previous)
    return resumed_projection(ledger,child['issue_id'])
