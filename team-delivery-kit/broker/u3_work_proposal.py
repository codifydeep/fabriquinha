"""Evidence-bound lifecycle work proposal and independent review, no TDD waiver."""
import json
import time
from jsonschema import Draft202012Validator, ValidationError
from work_proposal_contract import schema
try:
    import qa_cleanup_handoff as diagnostic, qa_cleanup_observer as observer
except ImportError:
    from broker import qa_cleanup_handoff as diagnostic, qa_cleanup_observer as observer


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS u3_work_proposals(source_task TEXT PRIMARY KEY,config TEXT,state TEXT,next_try REAL)')


def proposal(config, state, task):
    if (task.get('status')!='completed' or task.get('agent_id')!=diagnostic.CTO
            or task.get('issue_id')!=state['issue_id'] or task.get('wakeup_id')!=state['wakeup_id']):
        raise ValueError('exact completed CTO proposal required')
    raw=task.get('result',{}).get('output','')
    if not isinstance(raw,str) or len(raw)>3000:raise ValueError('bounded proposal required')
    value=json.loads(raw);Draft202012Validator(schema(observer.digest(config))).validate(value)
    return dict(task_id=task['id'],proposal=value,proposal_sha256=observer.digest(value),execution_authorized=False)


def review(config,state,task):
    if (task.get('status')!='completed' or task.get('agent_id')!=diagnostic.TECHLEAD
            or task.get('issue_id')!=state['issue_id'] or task.get('wakeup_id')!=state['wakeup_id']):
        raise ValueError('exact independent Tech Lead review required')
    value=json.loads(task.get('result',{}).get('output',''))
    keys={'decision','evidence_sha256','reason','limitations','release_homologated','product_admission_authorized','historical_tdd_red'}
    if (set(value)!=keys or value['decision'] not in ('ACCEPT_EVIDENCE','REQUEST_CHANGES')
            or value['evidence_sha256']!=state['proposal']['proposal_sha256']
            or not isinstance(value['reason'],str) or not 1<=len(value['reason'])<=1200
            or not isinstance(value['limitations'],list) or not 1<=len(value['limitations'])<=6
            or any(not isinstance(s,str) or not 1<=len(s)<=300 for s in value['limitations'])
            or any(value[k] is not False for k in ('release_homologated','product_admission_authorized','historical_tdd_red'))):
        raise ValueError('non-authorizing exact-proposal review required')
    return dict(task_id=task['id'],decision=value,execution_authorized=False)


class Effects(diagnostic.Effects):
    def issue(self,config,role):
        source=self.native.task_record(self.settings,config['request']['task_id'],diagnostic.CTO)
        if (source.get('status')!='completed' or source.get('issue_id')!=config['request']['issue_id']
                or json.loads(source.get('result',{}).get('output',''))!=config['diagnostic_receipt']['decision']):
            raise ValueError('exact completed originating CTO diagnostic required')
        return super().issue(config,role)
    def wake(self,config,state):
        if state['role']=='cto_proposal':
            sha=observer.digest(config)
            note=('STRUCTURED LIFECYCLE WORK PROPOSAL ONLY. Controller classification proves existing behavior '
                'already passes on byte-identical product; additive coverage is NOT new behavior or historical Red. '
                'The previous generic diagnosis asked for a new test-first item, but approved U3 scope has no '
                'verified missing behavior. Do not invent scope, break correct code or produce artificial Red. '
                'Propose lifecycle_reconciliation (audit obsolete attempt/dependency bindings while preserving '
                'blocked history) or retain_hold. Criteria exactly C08,C09,C10. No product edits, release '
                'approval, historical Red, dependent activation or execution authority.\n'
                'DELIVERY_WORK_PROPOSAL_V1:'+sha+'\nDELIVERY_TYPED_WORK_PROPOSAL_V1:'+sha)
        else:
            sha=state['proposal']['proposal_sha256']
            note=('INDEPENDENT TECH LEAD REVIEW: evaluate this exact CTO lifecycle proposal, not code. '
                'Accept only unchanged approved U3 scope, preserved historical block, no manufactured Red, '
                'no product edits or dependency/release authorization. Review data: '+
                json.dumps(state['proposal'],sort_keys=True)+
                '\nDELIVERY_DEPLOYMENT_EVIDENCE_V1:'+sha+'\nDELIVERY_TYPED_DEPLOYMENT_EVIDENCE_V1:'+sha)
        return self.native.ensure_planning_start(self.settings,state['issue_id'],state['target'],
            config['request']['task_id'],observer.digest(dict(config=config,role=state['role'])),note,allow_create=True)
    def work_item(self,config,state):
        parent=self.issues.request('/issues/'+config['request']['issue_id'])
        contract=dict(state['proposal'],independent_review=state['review'],
                      source_sha=config['source_sha'],criteria=config['criteria'],
                      original_attempt_status='historically_blocked_not_homologated',
                      product_edits_allowed=False,dependency_activation_allowed=False)
        return self.issues.ensure(dict(title='Lifecycle reconciliation '+observer.digest(contract)[:12],
            description='VALIDATED TECHNICAL MAINTENANCE CONTRACT; not product execution approval.\n'+json.dumps(contract,sort_keys=True),
            parent_issue_id=parent['id'],project_id=parent.get('project_id'),stage=4,status='todo'))


def tick(b,*,effects=None,now=None):
    now=time.time() if now is None else now
    with b.db() as con:
        initialize(con)
        tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required={'qa_cleanup_followups','u3_product_intakes','test_decompositions'}
        if not required<=tables:return
        for row in con.execute('SELECT config,state FROM qa_cleanup_followups').fetchall():
            old_config,old_state=map(json.loads,row)
            if old_state.get('stage')!='diagnostic_recorded' or old_config.get('cause')!='historical_tdd_red_missing':continue
            records=old_state.get('diagnostics',[])
            if len(records)!=1 or records[0]['decision']['action']!='request_correction':continue
            coverage=con.execute('SELECT config,state FROM u3_product_intakes').fetchall()
            if len(coverage)!=1:raise ValueError('one exact coverage classification required')
            cfg,st=map(json.loads,coverage[0]);proof=cfg.get('proof',{})
            if (st.get('stage')!='coverage_classification_approved'
                    or proof.get('classification')!='existing_behavior_coverage_only'
                    or proof.get('previous_files_unchanged') is not True or proof.get('new_code_required') is not False):
                raise ValueError('verified existing-behavior classification required')
            root=cfg['certificate']['root']
            approved=json.loads(con.execute('SELECT config FROM test_decompositions WHERE source_task=?',(root,)).fetchone()[0])
            config=dict(request=dict(old_config['request'],task_id=records[0]['task_id'],issue_id=old_state['issue_id']),
                cause='existing_coverage_lifecycle_hold',source_sha=old_config['request']['source_sha'],
                diagnostic_receipt=records[0],coverage_classification_sha256=observer.digest(dict(config=cfg,state=st)),
                classification='existing_behavior_coverage_only',criteria={k:approved['criteria'][k] for k in ('C08','C09','C10')},
                historical_tdd_red=False,execution_authorized=False)
            prior=con.execute('SELECT config FROM u3_work_proposals WHERE source_task=?',(records[0]['task_id'],)).fetchone()
            if prior and json.loads(prior[0])!=config:raise ValueError('immutable work proposal evidence drift')
            state=dict(stage='issue_intent',role='cto_proposal',target=diagnostic.CTO,attempts=0,execution_authorized=False)
            con.execute('INSERT OR IGNORE INTO u3_work_proposals VALUES(?,?,?,?)',
                (records[0]['task_id'],json.dumps(config,sort_keys=True),json.dumps(state),now))
        row=con.execute('SELECT * FROM u3_work_proposals WHERE next_try<=? ORDER BY next_try LIMIT 1',(now,)).fetchone()
    if not row:return
    config,state=json.loads(row['config']),json.loads(row['state']);effects=effects or Effects(b)
    def save(delay=5):
        with b.db() as con:con.execute('UPDATE u3_work_proposals SET state=?,next_try=? WHERE source_task=?',
            (json.dumps(state,sort_keys=True),now+delay,row['source_task']))
    try:
        if state['stage']=='issue_intent':
            if not effects.ready(state['target']):save(30);return state
            issue=effects.issue(config,state['role']);state.update(stage='dispatch_intent',issue_id=issue['id'],identifier=issue['identifier']);save()
        if state['stage']=='dispatch_intent':
            if not effects.ready(state['target']):save(30);return state
            wake=effects.wake(config,state);state.update(stage='awaiting_proposal' if state['role']=='cto_proposal' else 'awaiting_review',
                wakeup_id=wake['id'],at=now);save()
        if state['stage'] in ('awaiting_proposal','awaiting_review'):
            task=effects.task(state)
            if task and task['status'] not in ('queued','running','dispatched'):
                if state['stage']=='awaiting_proposal':
                    state['proposal']=proposal(config,state,task)
                    if state['proposal']['proposal']['kind']=='retain_hold':
                        state.update(stage='technical_blocked',next_action='CTO retained hold; no identical retry');save(1e30);return state
                    state.update(stage='issue_intent',role='techlead_review',target=diagnostic.TECHLEAD,attempts=0);save();return state
                state['review']=review(config,state,task)
                if state['review']['decision']['decision']!='ACCEPT_EVIDENCE':
                    state.update(stage='changes_requested',next_action='CTO revises from independent findings; no identical resubmission');save(1e30);return state
                state['stage']='work_item_intent';save()
            elif now-state['at']>=1800:raise ValueError('work proposal/review deadline; no respawn')
        if state['stage']=='work_item_intent':
            issue=effects.work_item(config,state)
            state.update(stage='work_contract_validated',work_item=issue['identifier'],work_issue_id=issue['id'],
                next_action='Execute only fixed lifecycle reconciliation after controller policy validation; original TDD/release hold preserved')
            save(1e30);print(json.dumps(dict(event='u3_work_contract_validated',issue=issue['identifier'],execution_authorized=False)),flush=True);return state
        save()
    except Exception as error:
        state['attempts']+=1;state['category']=type(error).__name__
        if isinstance(error,(ValueError,json.JSONDecodeError,ValidationError)) or state['attempts']>=2:
            state.update(stage='technical_blocked',next_action='CTO diagnoses exact protocol/evidence failure; no identical retry');save(1e30)
        else:save(30)
    return state
