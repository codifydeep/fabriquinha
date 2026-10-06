"""Fixed controller-only retirement of scheduling authority, never a TDD waiver."""
import json
try:
    import u3_work_proposal as work, qa_cleanup_observer as observer
except ImportError:
    from broker import u3_work_proposal as work, qa_cleanup_observer as observer


class ControllerBusy(ValueError):
    pass


def reconcile(con, contract):
    con.execute('CREATE TABLE IF NOT EXISTS u3_lifecycle_reconciliations('
                'root TEXT PRIMARY KEY,contract TEXT,receipt TEXT)')
    row=con.execute('SELECT state FROM incremental_checkpoints WHERE source_task=?',(contract['root'],)).fetchone()
    if not row:raise ValueError('exact original root required')
    old=json.loads(row[0])
    prior=con.execute('SELECT contract,receipt FROM u3_lifecycle_reconciliations WHERE root=?',(contract['root'],)).fetchone()
    if prior:
        receipt=json.loads(prior['receipt'])
        route=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(receipt['original_issue_id'],)).fetchone()
        if (json.loads(prior['contract'])!=contract or observer.digest(old)!=receipt['paused_state_sha256']
                or not route or observer.digest(json.loads(route[0]))!=receipt['paused_route_sha256']):
            raise ValueError('reconciled contract/state drift; diagnosis required')
        return receipt
    if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
        raise ControllerBusy('idle controller required')
    units=old.get('units',{});u3=units.get('U3',{})
    if (old.get('execution_authorized') is not True or old.get('delivery_approval') is not False
            or u3.get('stage')!='awaiting_red' or u3.get('revision')!=5
            or u3.get('green') or u3.get('delivery_review')
            or units.get('U4',{}).get('stage')!='waiting_dependency'
            or any(units.get(k,{}).get('stage')!='checkpointed' for k in ('U1','U2'))):
        raise ValueError('exact historically blocked revision required')
    issue=u3.get('binding',{}).get('issue_id')
    row=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
    if not row:raise ValueError('original scheduling route required')
    route=json.loads(row[0])
    if route.get('issue_id')!=issue or route.get('test_first') is not True:
        raise ValueError('original tests-first identity required')
    paused=json.loads(json.dumps(old));paused['execution_authorized']=False
    paused['stage']='historical_hold_reconciled'
    paused['lifecycle_reconciliation']=dict(work_issue_id=contract['work_issue_id'],
        original_state_sha256=observer.digest(old),historical_tdd_red=False,
        dependency_activation_allowed=False,release_homologated=False,
        next_action='Audit remaining approved scope against current commit before a fresh execution contract')
    stopped=dict(route,enabled=False)
    receipt=dict(schema='u3-lifecycle-reconciliation-v1',contract_sha256=observer.digest(contract),
        original_issue_id=issue,original_state=old,original_route=route,
        original_state_sha256=observer.digest(old),paused_state_sha256=observer.digest(paused),
        paused_route_sha256=observer.digest(stopped),historical_tdd_red=False,
        release_homologated=False,dependency_activation_allowed=False,product_edits=[])
    # One savepoint protects both scheduling writes and their complete evidence.
    con.execute('SAVEPOINT lifecycle')
    try:
        con.execute('INSERT INTO u3_lifecycle_reconciliations VALUES(?,?,?)',
                    (contract['root'],json.dumps(contract,sort_keys=True),json.dumps(receipt,sort_keys=True)))
        con.execute('UPDATE incremental_checkpoints SET state=? WHERE source_task=?',
                    (json.dumps(paused,sort_keys=True),contract['root']))
        con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',
                    (json.dumps(stopped,sort_keys=True),issue))
        con.execute('RELEASE lifecycle')
    except Exception:
        con.execute('ROLLBACK TO lifecycle');con.execute('RELEASE lifecycle');raise
    return receipt


def tick(b):
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='u3_work_proposals'").fetchone():return
        rows=con.execute('SELECT source_task,config,state FROM u3_work_proposals').fetchall()
    for row in rows:
        config,state=json.loads(row['config']),json.loads(row['state'])
        if state.get('stage')!='work_contract_validated':continue
        with b.LOCK,b.db() as con:
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():continue
        try:
            # Revalidate actual independent native outputs; prose supplies no IDs.
            fx=work.Effects(b)
            proposal_task=fx.native.task_record(fx.settings,state['proposal']['task_id'],work.diagnostic.CTO)
            proposal_state=dict(issue_id=proposal_task['issue_id'],wakeup_id=proposal_task['wakeup_id'])
            if work.proposal(config,proposal_state,proposal_task)!=state['proposal']:raise ValueError('native proposal drift')
            review_task=fx.native.task_record(fx.settings,state['review']['task_id'],work.diagnostic.TECHLEAD)
            if (proposal_task['issue_id']==state['issue_id']
                    or work.review(config,state,review_task)!=state['review']):raise ValueError('native review drift')
            if state['proposal']['proposal']['kind']!='lifecycle_reconciliation' or state['review']['decision']['decision']!='ACCEPT_EVIDENCE':
                raise ValueError('accepted lifecycle contract required')
            issue=fx.issues.request('/issues/'+state['work_issue_id'])
            maintenance_contract=dict(state['proposal'],independent_review=state['review'],
                source_sha=config['source_sha'],criteria=config['criteria'],
                original_attempt_status='historically_blocked_not_homologated',
                product_edits_allowed=False,dependency_activation_allowed=False)
            description='VALIDATED TECHNICAL MAINTENANCE CONTRACT; not product execution approval.\n'+json.dumps(maintenance_contract,sort_keys=True)
            if (issue.get('status')!='todo' or issue.get('parent_issue_id')!=config['request']['issue_id']
                    or issue.get('assignee_id') is not None or issue.get('description')!=description
                    or issue.get('title')!='Lifecycle reconciliation '+observer.digest(maintenance_contract)[:12]):
                raise ValueError('pending exact maintenance card required')
            with b.LOCK,b.db() as con:
                con.execute('BEGIN IMMEDIATE')
                entries=con.execute('SELECT config,state FROM u3_product_intakes').fetchall()
                if len(entries)!=1:raise ValueError('unique coverage proof required')
                coverage,classification=map(json.loads,entries[0])
                if observer.digest(dict(config=coverage,state=classification))!=config['coverage_classification_sha256']:
                    raise ValueError('coverage classification drift')
                root=coverage['certificate']['root']
                approved=json.loads(con.execute('SELECT config FROM test_decompositions WHERE source_task=?',(root,)).fetchone()[0])
                if {k:approved['criteria'][k] for k in ('C08','C09','C10')}!=config['criteria']:
                    raise ValueError('approved scope drift')
                receipt=reconcile(con,dict(root=root,work_issue_id=state['work_issue_id'],
                    proposal_sha256=state['proposal']['proposal_sha256'],review_task=state['review']['task_id']))
                state.update(stage='lifecycle_reconciled',receipt_sha256=observer.digest(receipt),
                    original_issue_id=receipt['original_issue_id'],execution_authorized=False,
                    next_action='Audit remaining scope on current commit; historical hold preserved, no dependent release')
                con.execute('UPDATE u3_work_proposals SET state=? WHERE source_task=?',
                            (json.dumps(state,sort_keys=True),row['source_task']))
            print(json.dumps(dict(event='u3_lifecycle_reconciled',work_item=state['work_item'],
                                  receipt_sha256=state['receipt_sha256'],release_homologated=False)),flush=True)
        except ControllerBusy:
            continue
        except Exception as error:
            # Visible durable block, never repeated writes or success fiction.
            state.update(stage='reconciliation_blocked',category=type(error).__name__,
                         next_action='CTO diagnoses reconciliation evidence/identity failure; no identical retry')
            with b.db() as con:con.execute('UPDATE u3_work_proposals SET state=? WHERE source_task=?',
                (json.dumps(state,sort_keys=True),row['source_task']))
