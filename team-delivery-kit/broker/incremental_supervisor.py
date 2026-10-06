"""Single coordinator for explicitly authorized, already bound incremental units.

Disabled by default. Does not manufacture issues, workspaces, approvals or an
initial-base receipt. Missing provisioning remains a visible technical incident.
"""
import json
import os
try:
    import incremental_checkpoints as ledger,incremental_evidence as evidence,incremental_dispatch as dispatch
    import handoff_runtime,native,test_first_handoffs,test_revision_review,incremental_read_recovery,handoffs
except ImportError:
    from broker import incremental_checkpoints as ledger,incremental_evidence as evidence,incremental_dispatch as dispatch
    from broker import handoff_runtime,native,test_first_handoffs,test_revision_review,incremental_read_recovery,handoffs


def _record(b,source,receipt):
    with b.db() as con:ledger.record(con,source,ledger.digest(receipt),lambda ref:receipt)


def require_repair_delta(unit, red, trial):
    """A sponsored repair cannot resubmit the exact known-defective seed."""
    if not unit.get('test_repair'):return
    repair=unit['test_repair']
    if (trial.get('parent_issue')!=repair['parent_issue']
            or trial.get('cto_decision')!=repair['decision_task']
            or not trial.get('old_red')):
        raise ValueError('repair snapshot sponsorship drift')
    old=trial['old_red']['red']['test_sha256'];new=red['red']['test_sha256']
    if set(old)!=set(new) or old==new:
        raise ValueError('sponsored repair requires changed NEW-test snapshot')


def _repair_guard(b,unit,issue,red=None):
    if not unit.get('test_repair'):return
    with b.db() as con:
        if red is None:
            red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()[0])
        trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()[0])
    require_repair_delta(unit,red,trial)
    try:import source_harness_completion
    except ImportError:from broker import source_harness_completion
    source_harness_completion.enforce(b,trial,red)
    try:import harness_candidate_gate
    except ImportError:from broker import harness_candidate_gate
    harness_candidate_gate.enforce(b,trial,red)


def observe_author_acceptance(b,route,runs):
    """Bind only an existing correction wakeup to its actual running author.

    Observation only: no wakeup, snapshot, test evidence or verdict is created.
    The coordinator must publish acceptance even while implementation is active.
    """
    with b.db() as con:
        rows=con.execute("SELECT * FROM delivery_handoffs WHERE issue_id=? AND stage='awaiting_acceptance'",
                         (route['issue_id'],)).fetchall()
        for row in rows:
            data=json.loads(row['data'])
            if (data.get('dispatch_stage')!='correct_author' or data.get('target')!=route['author']
                    or not data.get('wakeup_id') or data.get('contract_sha256')!=route['contract_sha256']):continue
            matches=[r for r in runs if r.get('wakeup_id')==data['wakeup_id']
                     and r.get('issue_id')==route['issue_id'] and r.get('agent_id')==route['author']]
            if len(matches)>1:raise ValueError('ambiguous author correction acceptance')
            if not matches or matches[0]['status'] not in ('running','completed'):continue
            data['recipient_task']=matches[0]['id']
            data['acceptance_observed_by']='incremental-supervisor'
            handoffs.save(con,row['source_task'],route['issue_id'],'accepted',route['author'],data,__import__('time').time())


def reconcile_red_author(b,route,runs,effects):
    """Pre-Red failures use the existing bounded CTO/author recovery machine."""
    with b.db() as con:
        red=con.execute('SELECT task_id FROM test_first_red WHERE issue_id=?',(route['issue_id'],)).fetchone()
    if not red:
        test_first_handoffs.reconcile(b,route,runs,effects)
        with b.db() as con:
            red=con.execute('SELECT task_id FROM test_first_red WHERE issue_id=?',(route['issue_id'],)).fetchone()
            row=con.execute('SELECT * FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(route['issue_id'],)).fetchone()
        if row:handoff_runtime.safe_publish(b,route,dict(row))
    if not red:return None
    matches=[r for r in runs if r.get('id')==red[0] and r.get('agent_id')==route['author']
             and r.get('issue_id')==route['issue_id'] and r.get('status')=='completed']
    if len(matches)!=1:raise ValueError('exact completed Red author required')
    return matches[0]


def _step(b,config,state,effects,settings):
    source=config['source_task']
    unit=next((u for u in state['units'].values() if u['stage'] not in ('checkpointed','waiting_dependency')
               and u['id'] in state.get('execution_units',list(state['units']))),None)
    if not unit:return
    if unit['stage']=='blocked':return
    if not unit.get('binding'):raise ValueError('unit provisioning required')
    issue=unit['binding']['issue_id']
    with b.db() as con:
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
    if not route['enabled']:return
    runs=native.issue_task_runs(settings,issue)
    if unit['stage']=='awaiting_red':
        with b.db() as con:
            table=con.execute("SELECT 1 FROM sqlite_master WHERE name='seeded_edit_recoveries'").fetchone()
            row=con.execute('SELECT receipt FROM seeded_edit_recoveries WHERE issue_id=?',(issue,)).fetchone() if table else None
        if row:
            recovery=json.loads(row[0])
            if recovery['source_task']!=source or recovery['revision']!=unit['revision'] or not recovery.get('wakeup_id'):
                raise ValueError('seeded edit recovery identity drift')
            runs=[r for r in runs if r.get('agent_id')!=route['author'] or r.get('wakeup_id')==recovery['wakeup_id']]
    if unit['stage']=='awaiting_red':
        with b.db() as con:dispatch.dispatch(con,source,unit['id'],effects)
        authors=[r for r in runs if r.get('agent_id')==route['author']]
        with b.db() as con:recovery=incremental_read_recovery.reconcile(con,source,unit,effects)
        if recovery:
            # Only the specifically authorized replacement may produce Red.
            preserved_failures={recovery['failed_task'],*recovery.get('prior_failed_tasks',[])}
            unexpected=[r for r in authors if r['id'] not in preserved_failures and r.get('wakeup_id')!=recovery.get('wakeup_id')]
            if unexpected:raise ValueError('unexpected author run during bounded recovery')
            authors=[r for r in authors if recovery.get('wakeup_id') and r.get('wakeup_id')==recovery['wakeup_id']]
        if not authors or any(r['status'] in ('queued','dispatched','running') for r in authors):return
        author=reconcile_red_author(b,route,runs,effects)
        if not author:return
        _repair_guard(b,unit,issue)
        with b.db() as con:
            proof=evidence.red(con,config,unit,issue,author['id'],prior_green=unit['binding']['prior_suite'])
        _record(b,source,proof)
    elif unit['stage']=='awaiting_test_review':
        with b.db() as con:
            red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()[0])
        _repair_guard(b,unit,issue,red)
        test_revision_review.reconcile(b,route,runs,effects,red)
        with b.db() as con:
            row=con.execute('SELECT state FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()
            review=json.loads(row[0]) if row else {}
            if review.get('status') not in ('approved','blocked') or not review.get('decision'):return
            proof=evidence.test_review(con,config,unit,issue)
        _record(b,source,proof)
    elif unit['stage']=='awaiting_green':
        _repair_guard(b,unit,issue)
        implementation=test_first_handoffs.reconcile(b,route,runs,effects)
        if not implementation:return
        authors=[r for r in implementation if r.get('agent_id')==route['author']]
        _check_author_leases(b,route,authors)
        observe_author_acceptance(b,route,runs)
        if not authors or any(r['status'] in ('queued','dispatched','running') for r in authors):return
        author=sorted(authors,key=lambda r:(r.get('created_at') or '',r['id']))[-1]
        with b.db() as con:
            prior=handoffs.load(con,author['id'])
            if prior and prior['stage'] not in ('approved','superseded','ready_review'):
                try:import structural_diagnosis
                except ImportError:from broker import structural_diagnosis
                if structural_diagnosis.reconcile(b,prior):return
                try:import failed_execution_evidence
                except ImportError:from broker import failed_execution_evidence
                if failed_execution_evidence.reconcile_trace(b,prior):return
                if failed_execution_evidence.reconcile_trace(b,prior,membership=True):return
                # The incremental coordinator retains ownership; only diagnosis
                # and correction use the existing durable handoff state machine.
                handoffs.reconcile(con,route,runs,effects)
                return
        if author['status']!='completed':raise ValueError('implementation execution requires diagnosis')
        snapshot=effects.freeze(author['id'])
        # This proves frozen Red tests + full Green before granting any review.
        try:
            validated=registered_green(prior,snapshot)
            if validated is None:validated=effects.validate(snapshot,author['id'])
        except Exception as error:
            failure=getattr(error,'validation_failure',None)
            if not isinstance(failure,dict) or failure.get('category')!='executed_test_failure':
                if _missing_product_delta(error):
                    _artifact_handoff(b,source,route,author,snapshot,error,
                        phase=effects.phase_evidence(author['id']))
                    return
                raise
            _functional_handoff(b,route,author,failure,snapshot,
                phase=effects.phase_evidence(author['id']))
            return
        if unchanged_review_correction(b,route,author,snapshot,validated):return
        if not effects.assign(author['id'],route['reviewer']):return
        marker=ledger.digest(dict(source_task=source,unit=unit['id'],revision=unit['revision'],
                                  operation='incremental-delivery-review-v2',author_task=author['id']))
        register_review_intent(b,route,author,snapshot,validated,marker)
        wake=effects.ensure_wakeup(issue,route['reviewer'],author['id'],marker,
            'Review the assigned immutable incremental delivery. Run the fixed controller suite. '+route['review_instruction'],
            allow_create=effects.remaining_calls()>=route['minimum_calls'])
        if not wake:return
        with b.db() as con:
            row=handoffs.load(con,author['id']);data=json.loads(row['data'])
            if data.get('wakeup_id') and data['wakeup_id']!=wake['id']:raise ValueError('incremental review wakeup drift')
            if not data.get('wakeup_id'):
                data['wakeup_id']=wake['id']
                handoffs.save(con,author['id'],issue,'ready_review',route['reviewer'],data,__import__('time').time())
        reviewers=[r for r in runs if r.get('agent_id')==route['reviewer'] and r.get('wakeup_id')==wake['id']]
        if not reviewers or reviewers[0]['status'] in ('queued','dispatched','running'):return
        if len(reviewers)!=1 or reviewers[0]['status']!='completed':raise ValueError('independent delivery review requires diagnosis')
        result=effects.review_result(reviewers[0]['id'],author['id'])
        if result is None:return
        if result['status']=='changes_requested':
            register_review_changes(b,route,author,reviewers[0],result,validated)
            return
        with b.db() as con:
            proof=evidence.green(con,config,unit,issue,author['id'],reviewers[0]['id'])
        _record(b,source,proof)
        with b.db() as con:
            current=ledger.status(con,source)
            current['units'][unit['id']]['delivery_source_task']=author['id']
            current['units'][unit['id']]['delivery_review_task']=reviewers[0]['id']
            con.execute('UPDATE incremental_checkpoints SET state=? WHERE source_task=?',(json.dumps(current,sort_keys=True),source))
    elif unit['stage']=='awaiting_delivery_review':
        # Recover even if the controller restarted between Green and task-ID storage.
        with b.db() as con:
            stored=json.loads(con.execute('SELECT receipt FROM incremental_checkpoint_events WHERE source_task=? AND receipt_sha256=?',
                (source,unit['green'])).fetchone()[0]);author=stored['task_id']
            rows=con.execute('SELECT review_task_id FROM reviews WHERE source_task_id=? AND manifest_sha256=?',
                (author,unit['green_manifest_sha256'])).fetchall()
            if len(rows)!=1:raise ValueError('unique current delivery decision required')
            proof=evidence.delivery_review(con,config,unit,issue,author,rows[0][0])
        _record(b,source,proof)


def registered_green(prior,snapshot):
    """Reuse only the controller receipt bound to this immutable review intent."""
    if not prior or prior['stage']!='ready_review':return None
    data=json.loads(prior['data'])
    if data.get('coordinator')!='incremental-delivery-review-v2' or not data.get('green_validation'):return None
    if data['snapshot']!=snapshot:raise ValueError('registered immutable snapshot drift')
    validated=data['green_validation']
    if validated.get('manifest_sha256')!=data['manifest_sha256']:raise ValueError('registered Green manifest drift')
    return validated


def unchanged_review_correction(b,route,author,snapshot,validated):
    """Do not spend a new review on an unchanged previously rejected delivery.

    No-delta can reflect an invalid finding rather than a product defect. CTO
    diagnoses that distinction; this guard grants no approval or test exception.
    """
    if not author.get('wakeup_id'):return False
    with b.db() as con:
        previous=None
        for row in con.execute('SELECT * FROM delivery_handoffs WHERE issue_id=? AND source_task<>?',
                (route['issue_id'],author['id'])):
            data=json.loads(row['data'])
            if (data.get('dispatch_stage')=='correct_author'
                    and data.get('wakeup_id')==author['wakeup_id']
                    and data.get('review',{}).get('status')=='changes_requested'
                    and data.get('manifest_sha256')==validated.get('manifest_sha256')):
                previous=(dict(row),data);break
        if not previous:return False
        old,data=previous
        incident=dict(category='unchanged_rejected_delivery',previous_source=old['source_task'],
            source_task=author['id'],review_task=data['review']['review_task_id'],
            manifest_sha256=validated['manifest_sha256'],finding=data['finding'],
            required_action='cto_diagnose_finding_or_correction_before_another_review')
        now=__import__('time').time()
        data['superseded_by']=author['id']
        handoffs.save(con,old['source_task'],route['issue_id'],'superseded',route['author'],data,now)
        replacement=dict(source_task=author['id'],contract_sha256=route['contract_sha256'],
            author=route['author'],reviewer=route['reviewer'],attempts=1,
            source_status='completed',snapshot=snapshot,manifest_sha256=validated['manifest_sha256'],
            evidence={**validated,'correction_diagnosis':incident},
            error='correction_returned_unchanged_rejected_delivery',
            required_action=incident['required_action'],delivery_approval=False)
        handoffs.save(con,author['id'],route['issue_id'],'diagnose_cto',route['cto'],replacement,now)
        return True


def register_review_changes(b,route,author,review,result,validated):
    """A rejection transfers ownership; it is never a Green checkpoint."""
    if (review.get('status')!='completed' or review.get('agent_id')!=route['reviewer']
            or result.get('review_task_id')!=review['id']
            or result.get('source_task_id')!=author['id']
            or result.get('reviewer_agent_id')!=route['reviewer']
            or result.get('status')!='changes_requested' or not result.get('finding')):
        raise ValueError('bound independent change request required')
    with b.db() as con:
        row=handoffs.load(con,author['id']);data=json.loads(row['data'])
        if (row['stage']!='ready_review' or review.get('wakeup_id')!=data.get('wakeup_id')
                or validated.get('manifest_sha256')!=data.get('manifest_sha256')):
            raise ValueError('change request handoff identity drift')
        data.update(finding=result['finding'],trigger_task=review['id'],review=result,
                    evidence=validated,delivery_approval=False,
                    contract_sha256=route['contract_sha256'],author=route['author'],
                    reviewer=route['reviewer'],attempts=1,source_status='completed')
        handoffs.save(con,author['id'],route['issue_id'],'correct_author',route['author'],data,__import__('time').time())


def register_review_intent(b,route,author,snapshot,validated,marker):
    """Commit source/target/snapshot BEFORE native wakeup can initialize.

    This uses the same durable registry checked by native_grant/auto_prepare_review,
    rather than granting a special bypass to incremental workers.
    """
    if (author.get('status')!='completed' or author.get('agent_id')!=route['author']
            or author.get('issue_id')!=route['issue_id']
            or snapshot.get('task_id')!=author['id'] or snapshot.get('status')!='complete'
            or not snapshot.get('volume') or not validated.get('manifest_sha256')
            or validated.get('tests',0)<=0 or route['author']==route['reviewer']):
        raise ValueError('validated independent review intent required')
    data=dict(source_task=author['id'],target=route['reviewer'],dispatch_marker=marker,
        snapshot=snapshot,manifest_sha256=validated['manifest_sha256'],
        green_validation=validated,coordinator='incremental-delivery-review-v2',delivery_approval=False)
    with b.db() as con:
        old=handoffs.load(con,author['id'])
        if old:
            prior=json.loads(old['data'])
            # Existing v2 intents contain a controller-run Green receipt in
            # delivery_tdd, but predate its explicit projection into the intent.
            # Caller must supply a freshly controller-validated receipt to migrate.
            if old['stage']=='ready_review' and 'green_validation' not in prior:
                if any(prior.get(k)!=v for k,v in data.items() if k!='green_validation'):
                    raise ValueError('legacy registered Green identity drift')
                prior['green_validation']=validated
                handoffs.save(con,author['id'],route['issue_id'],'ready_review',route['reviewer'],prior,__import__('time').time())
                return prior
            if old['stage'] not in ('ready_review','approved') or any(prior.get(k)!=v for k,v in data.items()):
                raise ValueError('incremental review intent identity drift')
            return prior
        handoffs.save(con,author['id'],route['issue_id'],'ready_review',route['reviewer'],data,__import__('time').time())
    return data


class ExpiredAuthorLease(ValueError):
    def __init__(self,route,task,row):
        self.incident=dict(category='author_native_running_with_expired_lease',
            owner=route['cto'],task_id=task['id'],request_id=row['request_id'],
            lease_status=row['status'],deadline=row['deadline'],automatic_retry=False,
            delivery_approval=False,
            required_action='preserve_workspace_and_reconcile_native_task_before_diagnosed_recovery')
        super().__init__('author native state outlived expired worker lease')


def _check_author_leases(b,route,authors):
    """Native running alone cannot keep a dead execution invisible forever."""
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='native_bindings'").fetchone():return
        for task in authors:
            if task.get('status')!='running':continue
            row=con.execute('SELECT n.request_id,l.status,l.deadline FROM native_bindings n '
                'JOIN leases l USING(request_id) WHERE n.task_id=? ORDER BY n.rowid DESC LIMIT 1',
                (task['id'],)).fetchone()
            if row and row['status']=='expired':raise ExpiredAuthorLease(route,task,row)


def _missing_product_delta(error):
    import re
    return isinstance(error,ValueError) and bool(re.fullmatch(
        r'artifact_validation: new product code required; new test files present=[1-9][0-9]*',str(error)))


def _artifact_handoff(b,source,route,author,snapshot,error,*,phase):
    """A structural rejection is not a failed suite or a reason to retry blindly."""
    import hashlib,time
    if (not _missing_product_delta(error) or author.get('status')!='completed'
            or snapshot.get('task_id')!=author['id'] or snapshot.get('status')!='complete'
            or not snapshot.get('volume') or not isinstance(phase,dict)):
        raise ValueError('exact completed structural rejection required')
    with b.db() as con:
        handoffs.initialize(con)
        prior=handoffs.load(con,author['id'])
        if prior:return
        data=dict(source_task=author['id'],contract_sha256=route['contract_sha256'],
            author=route['author'],reviewer=route['reviewer'],attempts=1,
            error=str(error),error_type='ValueError',failure_category='missing_delivery_artifacts',
            failure_signature=hashlib.sha256(('ValueError:'+str(error)).encode()).hexdigest(),
            source_status='completed',snapshot=snapshot,phase_evidence=phase)
        incident=con.execute('SELECT receipt FROM incremental_runtime_incidents WHERE source_task=?',(source,)).fetchone()
        if incident:
            saved=json.loads(incident[0])
            if saved==dict(category='ValueError',owner='cto',required_action='diagnose_incremental_runtime_binding_or_execution'):
                data['previous_runtime_incident']=saved
                con.execute('DELETE FROM incremental_runtime_incidents WHERE source_task=?',(source,))
        handoffs.save(con,author['id'],route['issue_id'],'diagnose_cto',route['cto'],data,time.time())


def _functional_handoff(b,route,author,failure,snapshot,*,phase=None):
    """Persist real failed Green evidence before any CTO/model side effect."""
    import hashlib,time
    if failure.get('source_task')!=author['id'] or failure.get('volume')!=snapshot['volume']:
        raise ValueError('functional recovery snapshot identity mismatch')
    with b.db() as con:
        handoffs.initialize(con)
        if handoffs.load(con,author['id']):return
        data=dict(source_task=author['id'],contract_sha256=route['contract_sha256'],
            author=route['author'],reviewer=route['reviewer'],attempts=1,
            error='portable frozen suite failed',error_type='FrozenSuiteFailure',
            failure_signature=hashlib.sha256(b'FrozenSuiteFailure:portable frozen suite failed').hexdigest(),
            validation_failure=failure,artifact_diagnosis=True,
            diagnostic_revision=failure['output_sha256']+':incremental-artifacts-v1',
            source_status='completed',snapshot=snapshot)
        if phase is not None:data['phase_evidence']=phase
        handoffs.save(con,author['id'],route['issue_id'],'diagnose_cto',route['cto'],data,time.time())


def recover_proxy_health(b,source,effects,now=None):
    """Resume only an attributed failed GET /status, never an execution retry."""
    import time,hashlib
    now=time.time() if now is None else now
    with b.db() as con:
        row=con.execute('SELECT receipt FROM incremental_runtime_incidents WHERE source_task=?',(source,)).fetchone()
    if not row:return True
    original=row[0];incident=json.loads(original)
    if (incident.get('category')!='model_proxy_status_unavailable' or incident.get('version')!=1
            or incident.get('endpoint')!='model_proxy_status' or incident.get('required_action')!='health_check_only'):
        return False
    if incident.get('next_check_at',now+10)>now:return False
    try:effects.remaining_calls()
    except handoff_runtime.BudgetStatusUnavailable:
        checks=incident.get('health_checks',0)+1
        incident.update(health_checks=checks,next_check_at=now+min(10*2**min(checks,3),60))
        with b.db() as con:
            con.execute('UPDATE incremental_runtime_incidents SET receipt=? WHERE source_task=? AND receipt=?',
                (json.dumps(incident,sort_keys=True),source,original))
        return False
    except Exception:return False  # invalid budget/auth/schema remains blocked
    receipt=dict(operation='verified_proxy_health_recovery_v1',incident=incident,
                 recovered_at=now,health_read_only=True,execution_retried=False,delivery_approval=False)
    encoded=json.dumps(receipt,sort_keys=True);sha=hashlib.sha256(encoded.encode()).hexdigest()
    with b.db() as con:
        current=con.execute('SELECT receipt FROM incremental_runtime_incidents WHERE source_task=?',(source,)).fetchone()
        if not current or current[0]!=original:return False
        con.execute('CREATE TABLE IF NOT EXISTS incremental_recovery_evidence('
                    'source_task TEXT,receipt_sha256 TEXT,receipt TEXT,PRIMARY KEY(source_task,receipt_sha256))')
        con.execute('INSERT OR IGNORE INTO incremental_recovery_evidence VALUES(?,?,?)',(source,sha,encoded))
        con.execute('DELETE FROM incremental_runtime_incidents WHERE source_task=? AND receipt=?',(source,original))
    return True


def checkpoint_tasks(con,root,unit):
    """Recover IDs from immutable ledger receipts, not task ordering or claims."""
    proofs=[]
    for key,operation in (('green','green'),('delivery_review','delivery_review')):
        row=con.execute('SELECT receipt FROM incremental_checkpoint_events WHERE source_task=? AND receipt_sha256=?',
                        (root,unit.get(key))).fetchone()
        if not row:raise ValueError('checkpoint task identity evidence missing')
        proof=json.loads(row[0])
        if (ledger.digest(proof)!=unit[key] or proof.get('operation')!=operation
                or proof.get('source_task')!=root or proof.get('unit')!=unit['id']
                or proof.get('manifest_sha256')!=unit['green_manifest_sha256']):
            raise ValueError('checkpoint task identity evidence drift')
        proofs.append(proof)
    if proofs[1].get('decision')!='approve' or proofs[1].get('green_receipt_sha256')!=unit['green']:
        raise ValueError('checkpoint task identity approval missing')
    source,review=proofs[0]['task_id'],proofs[1]['task_id']
    if ((unit.get('delivery_source_task') and unit['delivery_source_task']!=source)
            or (unit.get('delivery_review_task') and unit['delivery_review_task']!=review)):
        raise ValueError('checkpoint task identity binding drift')
    return source,review


def publish_checkpoints(b,state,root=None):
    """Project verified checkpoints to handoffs; recover a crash before publish."""
    import time
    for unit in state['units'].values():
        if unit['stage']!='checkpointed':continue
        if not root and not unit.get('delivery_source_task'):continue
        with b.db() as con:
            source,review=checkpoint_tasks(con,root,unit) if root else (unit['delivery_source_task'],unit.get('delivery_review_task'))
            row=handoffs.load(con,source)
            if not row:raise ValueError('checkpoint handoff unavailable')
            data=json.loads(row['data'])
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
            receipt=con.execute('SELECT * FROM reviews WHERE source_task_id=? AND review_task_id=?',(source,review)).fetchone()
            if (not receipt or receipt['status']!='approved' or receipt['reviewer_agent_id']!=route['reviewer']
                    or route['author']==route['reviewer'] or receipt['manifest_sha256']!=unit['green_manifest_sha256']
                    or data.get('green_validation',{}).get('manifest_sha256')!=unit['green_manifest_sha256']):
                raise ValueError('checkpoint publication approval drift')
            if root and (not unit.get('delivery_source_task') or not unit.get('delivery_review_task')):
                current=ledger.status(con,root)
                actual=current['units'][unit['id']]
                if actual['stage']!='checkpointed' or actual['green']!=unit['green'] or actual['delivery_review']!=unit['delivery_review']:
                    raise ValueError('checkpoint recovery state drift')
                actual.update(delivery_source_task=source,delivery_review_task=review)
                con.execute('UPDATE incremental_checkpoints SET state=? WHERE source_task=?',(json.dumps(current,sort_keys=True),root))
                unit.update(delivery_source_task=source,delivery_review_task=review)
            changed=row['stage']=='ready_review'
            if changed:
                data['review']=dict(receipt)
                data['checkpoint_sync']=dict(operation='verified_existing_checkpoint_publication_v1',
                    source_task=source,review_task=review,manifest_sha256=receipt['manifest_sha256'],release_homologated=False)
                handoffs.save(con,source,row['issue_id'],'approved',route['reviewer'],data,time.time())
                row=handoffs.load(con,source)
            elif row['stage']!='approved':raise ValueError('checkpoint handoff stage drift')
            pending=con.execute("SELECT 1 FROM sqlite_master WHERE name='handoff_publication_errors'").fetchone()
            retry=pending and con.execute('SELECT 1 FROM handoff_publication_errors WHERE issue_id=?',(row['issue_id'],)).fetchone()
        if changed or retry:handoff_runtime.safe_publish(b,route,row)


def tick(b):
    if os.environ.get('BROKER_INCREMENTAL_ENABLED')!='1':return
    with b.LOCK,b.db() as con:
        ledger.initialize(con);dispatch.initialize(con)
        con.execute('CREATE TABLE IF NOT EXISTS incremental_runtime_incidents('
                    'source_task TEXT PRIMARY KEY,receipt TEXT)')
        rows=con.execute('SELECT config,state FROM incremental_checkpoints').fetchall()
    for row in rows:
        config,state=map(json.loads,row)
        if not state['execution_authorized']:continue
        with b.LOCK:
            try:
                try:import incremental_harness_replan
                except ImportError:from broker import incremental_harness_replan
                incremental_harness_replan.tick(b,config['source_task'])
            except Exception:
                # Existing incident remains visible; never bypass its pause.
                continue
            settings=json.loads((b.STATE/'native.json').read_text());effects=handoff_runtime.Effects(b,settings)
            if not recover_proxy_health(b,config['source_task'],effects):continue
            try:
                publish_checkpoints(b,state,config['source_task'])
                _step(b,config,state,effects,settings)
            except Exception as error:
                with b.db() as con:
                    incident=getattr(error,'incident',None) or dict(category=type(error).__name__,owner='cto',
                        required_action='diagnose_incremental_runtime_binding_or_execution')
                    con.execute('INSERT OR IGNORE INTO incremental_runtime_incidents VALUES(?,?)',
                        (config['source_task'],json.dumps(incident,sort_keys=True)))
