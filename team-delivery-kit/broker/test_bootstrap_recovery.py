"""One controller-proven bootstrap repair; never reinterpret a CTO response."""
import hashlib
import json
import re
import time
import uuid


def reopen(broker, payload, *, normalized=False):
    try:
        import native, handoffs, test_revision_review
    except ImportError:
        from broker import native, handoffs, test_revision_review
    fields={'issue_id','source_task','worker_image'}|({'completed_source','test_sha256'} if normalized else set())
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError('exact bootstrap recovery identity required')
    for key in ('issue_id','source_task'):
        if str(uuid.UUID(payload[key])) != payload[key]:raise ValueError('invalid recovery identity')
    if normalized and (str(uuid.UUID(payload['completed_source']))!=payload['completed_source']
                       or not re.fullmatch(r'[0-9a-f]{64}',payload['test_sha256'])):
        raise ValueError('exact completed author and artifact hash required')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',payload['worker_image']) or payload['worker_image'] != broker.IMAGE:
        raise ValueError('installed immutable recovery image required')
    with broker.LOCK, broker.db() as con:
        prior=handoffs.load(con,payload['source_task'])
        if not prior or prior['issue_id']!=payload['issue_id']:raise ValueError('missing blocked source')
        data=json.loads(prior['data'])
        if data.get('bootstrap_recovery'):
            if data['bootstrap_recovery']['request']!=payload:raise ValueError('bootstrap recovery identity drift')
            return data['bootstrap_recovery']
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(payload['issue_id'],)).fetchone()[0])
        trial=con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(payload['issue_id'],)).fetchone()
        if (not trial or not route.get('enabled') or not route.get('test_first')
                or prior['stage']!='test_first_blocked' or data.get('diagnostic')
                or data.get('error')!=('test_first_correction_failed_after_cto_diagnosis' if normalized
                                      else 'test_first_cto_invalid_decision:JSONDecodeError')):
            raise ValueError('only blocked revision-child bootstrap may recover')
        if con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(payload['issue_id'],)).fetchone():
            raise ValueError('Red already exists; bootstrap repair forbidden')
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():
            raise ValueError('bootstrap repair requires idle workers')
        binding=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',
                            (payload['source_task'],)).fetchall()
        if len(binding)!=1 or binding[0]['status']!='failed' or binding[0]['agent_id']!=route['author']:
            raise ValueError('exact failed author lease required')
        binding=dict(binding[0])
        error=con.execute('SELECT 1 FROM broker_errors WHERE request_id=? AND operation=? AND category=?',
            (binding['request_id'],'transport_start','bootstrap:broker_internal')).fetchone()
        if not error:raise ValueError('recorded pre-prompt bootstrap failure required')
        config=json.loads(trial[0])
        parent=con.execute('SELECT state FROM test_revision_trials WHERE issue_id=?',(config['parent_issue'],)).fetchone()
        parent=json.loads(parent[0]) if parent else {}
        if (parent.get('rejection_diagnosis',{}).get('decision',{}).get('action')!='request_test_revision'
                or parent.get('rejection_diagnosis',{}).get('decision_task')!=config['cto_decision']
                or not parent.get('size_invalidation')):
            raise ValueError('existing independent CTO sponsorship required')
        settings=json.loads((broker.STATE/'native.json').read_text())
        runs=native.issue_task_runs(settings,payload['issue_id'])
        authors=[r for r in runs if r.get('agent_id')==route['author']]
        source=next((r for r in authors if r['id']==payload['source_task']),{})
        if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=payload['source_task']
                or any(r.get('status') in ('queued','running') for r in runs)
                or source.get('status')!='failed'
                or source.get('error')!='hermes initialize failed: hermes process exited'):
            raise ValueError('idle latest failed author required')
        # Actual fixed seed and root-owned permission fence, no model or arbitrary
        # command. Hash-bound historical input is selected from existing receipts.
        selection=test_revision_review.seed_source(broker,payload['issue_id'])
        if not selection or not selection['selection'].get('repair_input_bytes'):
            raise ValueError('measured historical repair input required')
        volume=broker.PREFIX+'-work-'+hashlib.sha256(binding['scope'].encode()).hexdigest()[:32]
        editables=['/workspace/'+name for name in route['test_first_files']]
        formatting=None
        if normalized:
            completed=next((r for r in authors if r['id']==payload['completed_source']),{})
            original=con.execute('SELECT scope FROM native_bindings WHERE task_id=?',(payload['completed_source'],)).fetchall()
            if (completed.get('status')!='completed' or len(original)!=1
                    or original[0]['scope']!=binding['scope'] or len(route['test_first_files'])!=1):
                raise ValueError('exact same-workspace completed author required')
            try:import test_normalization_job
            except ImportError:from broker import test_normalization_job
            formatting=test_normalization_job.run(broker,payload['issue_id'],binding['scope'],payload['completed_source'],
                {'path':route['test_first_files'][0],'sha256':payload['test_sha256']})
        else:broker.seed_workspace(payload['issue_id'],binding['scope'],volume)
        broker.lock_workspace(payload['issue_id'],binding['scope'],volume,editables)
        receipt={'request':payload,'phase':'test_first','probe':'fixed_seed_and_phase_fence_passed',
                 'selection':selection['selection'],'cto_decision':config['cto_decision'],
                 'reason':config['reason'],'previous_blocker':data.copy(),'at':time.time()}
        if formatting:
            receipt.update(normalization=formatting,reason='The controller preserved the original candidate and applied exact AST-preserving formatting only. Inspect the NEW test and run the complete pinned suite. Do not spend turns trimming comments or rewriting the harness. Report actual Red and findings; no product code edits. Independent review still compares this submission against the original frozen tests.')
        data.update(bootstrap_recovery=receipt)
        handoffs.save(con,payload['source_task'],payload['issue_id'],'test_first_bootstrap_recovery_pending',
                      route['author'],data,time.time())
        return receipt
