"""Bounded R1 review feedback -> fresh independently reviewed recovery plan.

Never replaces Red, review state, execution contracts or revision ancestry.
The new plan still needs CTO/TL approval and every R1/R2/R3 delivery gate.
"""
import json
import time
import hashlib

try:
    import technical_remediation_plan as plans, remediation_runtime_guard as guard
    import handoffs, native, handoff_runtime, test_review_replan_certificate as certificate
    import test_revision_review as reviews
except ImportError:
    from broker import technical_remediation_plan as plans, remediation_runtime_guard as guard
    from broker import handoffs, native, handoff_runtime, test_review_replan_certificate as certificate
    from broker import test_revision_review as reviews


def configuration(previous, execution, route, red, state, proof, base):
    previous_round=previous.get('r1_feedback',{}).get('round',0)
    if type(previous_round) is not int or not 0<=previous_round<2:
        raise ValueError('R1 feedback exhausted; CTO experiment required')
    round_number=previous_round+1
    diagnosis=state.get('rejection_diagnosis',{})
    if (type(round_number) is not int or not 1<=round_number<=2
            or previous.get('original_depth')!=2 or len(previous.get('revision_lineage',[]))!=2
            or previous.get('baseline_edits_allowed') is not False
            or previous.get('historical_snapshots_editable') is not False
            or previous.get('release_homologated') is not False
            or execution.get('stage')!='r1_base_qualified' or execution.get('r1_gate')
            or execution.get('execution_authorized') is not False
            or execution.get('issue_id')!=route.get('issue_id')
            or execution.get('superseded_by_feedback')
            or route.get('test_first') is not True or route.get('enabled') is not True
            or route.get('author')!=previous['steps'][0]['owner']
            or len({route.get(k) for k in ('author','reviewer','techlead','cto')})!=4
            or any(not route.get(k) for k in ('author','reviewer','techlead','cto'))
            or route.get('contract_sha256')!=previous.get('contract_sha256')
            or state.get('status')!='blocked' or state.get('decision',{}).get('action')!='reject_test_revision'
            or diagnosis.get('status')!='revision_required'
            or diagnosis.get('decision',{}).get('action')!='request_test_revision'
            or proof!=state.get('technical_replan_certificate')
            or proof.get('operation')!='qualified_immutable_test_cto_replan_v1'
            or any(proof.get(k) is not False for k in ('baseline_edits_allowed','delivery_approval','green_evidence'))
            or proof.get('issue_id')!=route['issue_id'] or proof.get('source_task')!=red.get('task_id')
            or proof.get('decision_task')!=diagnosis.get('decision_task')
            or proof.get('independent_review_task')!=state.get('review_task')
            or state.get('review_task') in (red.get('task_id'),diagnosis.get('decision_task'))
            or proof.get('manifest_sha256')!=red.get('red',{}).get('manifest_sha256')
            or state.get('manifest_sha256')!=proof.get('manifest_sha256')
            or red.get('issue_id')!=route['issue_id'] or red.get('volume')!=state.get('candidate_volume')
            or set(red.get('red',{}).get('test_sha256',{}))!=set(previous['steps'][0]['editable_files'])
            or any(base.get(k)!=previous['base'][k] for k in ('base_sha','manifest_sha256'))):
        raise ValueError('bounded exact rejected R1 and independent CTO sponsorship required')
    feedback=dict(operation='remediation_r1_review_feedback_v1',round=round_number,
        previous_source=previous['source_task'],previous_execution_sha256=plans.digest(previous),
        previous_run=previous['run_id'],review_task=state['review_task'],
        review_decision_sha256=plans.digest(state['decision']),certificate=proof,
        original_depth=2,revision_depth_reset=False,attempt_limit=2,execution_authorized=False)
    # Planning reads the new immutable candidate. The already verified CTO
    # certificate preserves complete reads of candidate AND previous delivery.
    paths=sorted('/evidence/candidate/'+p for p in red['red']['test_sha256'])
    return dict(source_task=red['task_id'],source_issue=route['issue_id'],
        root_issue=previous['root_issue'],original_depth=2,revision_lineage=previous['revision_lineage'],
        cto=route['cto'],reviewer=route['techlead'],original_author=route['author'],
        contract_sha256=route['contract_sha256'],context_sha256=route['execution_context']['sha256'],
        criteria=previous['criteria'],base=base,volume=red['volume'],required_paths=paths,
        diagnostic_task=diagnosis['decision_task'],diagnostic_wakeup=diagnosis['wakeup_id'],
        diagnostic_decision=diagnosis['decision'],
        intake_kind='rejected_remediation_r1_v1',r1_feedback=feedback,
        experiment=dict(operation='immutable_r1_review_reference_v1',
            proof=dict(input_sha256=red['red']['test_sha256'],facts=dict(
                review_rejected=True,cto_revision_required=True,historical_tests_changed=False))))


def validate_parent(con, config):
    feedback=config['r1_feedback']
    row=con.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',
        (feedback['previous_source'],)).fetchone()
    if not row:raise ValueError('preserved previous R1 execution required')
    previous,execution=map(json.loads,row)
    review=con.execute('SELECT state FROM test_revision_trials WHERE issue_id=?',(config['source_issue'],)).fetchone()
    red=con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(config['source_issue'],)).fetchone()
    if not review or not red:raise ValueError('immutable rejected R1 and review required')
    state=json.loads(review[0]);red=json.loads(red[0])
    if (plans.digest(previous)!=feedback['previous_execution_sha256']
            or previous['run_id']!=feedback['previous_run']
            or execution.get('superseded_by_feedback')!=dict(source_task=config['source_task'],config_sha256=plans.digest(config))
            or previous.get('original_depth')!=config.get('original_depth') or config.get('original_depth')!=2
            or previous['revision_lineage']!=config['revision_lineage'] or previous['criteria']!=config['criteria']
            or previous['root_issue']!=config['root_issue']
            or previous['contract_sha256']!=config['contract_sha256']
            or feedback['round']!=previous.get('r1_feedback',{}).get('round',0)+1
            or state.get('decision',{}).get('action')!='reject_test_revision'
            or state.get('review_task')!=feedback['review_task']
            or plans.digest(state.get('decision'))!=feedback['review_decision_sha256']
            or state.get('technical_replan_certificate')!=feedback['certificate']
            or state.get('rejection_diagnosis',{}).get('decision')!=config['diagnostic_decision']
            or red['task_id']!=config['source_task'] or red['volume']!=config['volume']
            or red['red']['test_sha256']!=config['experiment']['proof']['input_sha256']
            or any(previous['base'][k]!=config['base'][k] for k in ('base_sha','manifest_sha256'))):
        raise ValueError('immutable original R1 feedback lineage drift')


def register(b, issue):
    with b.LOCK:
        qualified=guard.qualified(b,issue)
        if qualified is None:return None
        old_source,previous,execution=guard.lookup(b,issue)
        with b.db() as con:
            plans.initialize(con)
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
            red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()[0])
            row=handoffs.load(con,red['task_id'])
            state=json.loads(con.execute('SELECT state FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()[0])
            prior=con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(red['task_id'],)).fetchone()
            if prior:
                if json.loads(prior[0]).get('intake_kind')!='rejected_remediation_r1_v1':
                    raise ValueError('foreign R1 feedback registration')
                return json.loads(prior[1])
            if (not row or row['stage']!='test_revision_required'
                    or json.loads(row['data']).get('technical_replan_certificate')!=state.get('technical_replan_certificate')
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()):
                return None
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        task=native.task_record(settings,state['rejection_diagnosis']['decision_task'],route['cto'])
        decision=fx.decision(task);reads=fx.read_evidence(task)
        reviews.validate_evidence(b,route,state,decision)
        proof=certificate.qualify(route,state,red,task,decision,reads)
        reviewer=native.task_record(settings,state['review_task'],route['techlead'])
        author=native.task_record(settings,red['task_id'],route['author'])
        if (reviewer.get('status')!='completed' or reviewer.get('issue_id')!=issue
                or reviewer.get('wakeup_id')!=state.get('wakeup_id')
                or author.get('status')!='completed' or author.get('issue_id')!=issue
                or fx.decision(reviewer)!=state['decision']
                or any(r.get('status') in ('queued','dispatched','running') for r in native.issue_task_runs(settings,issue))):
            raise ValueError('closed live independent R1 review and CTO decision required')
        reviews.validate_evidence(b,route,state,state['decision'])
        labels=(b.docker('GET','/volumes/'+red['volume']) or {}).get('Labels',{})
        if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.test-first-task')!=red['task_id']:
            raise ValueError('unchanged controller-owned rejected Red required')
        config=configuration(previous,execution,route,red,state,proof,b.issue_base(issue))
        pending=dict(stage='issue_intent',owner=route['cto'],execution_authorized=False,release_homologated=False)
        with b.db() as con:
            if (handoffs.load(con,red['task_id'])!=row
                    or json.loads(con.execute('SELECT state FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()[0])!=state
                    or json.loads(con.execute('SELECT state FROM remediation_executions WHERE source_task=?',(old_source,)).fetchone()[0])!=execution
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()):
                raise ValueError('R1 feedback changed before registration')
            con.execute('INSERT INTO technical_remediation_plans VALUES(?,?,?)',
                (red['task_id'],json.dumps(config,sort_keys=True),json.dumps(pending,sort_keys=True)))
            route['enabled']=False
            con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(route,sort_keys=True),issue))
            execution={**execution,'superseded_by_feedback':dict(source_task=red['task_id'],config_sha256=plans.digest(config))}
            con.execute('UPDATE remediation_executions SET state=? WHERE source_task=?',(json.dumps(execution,sort_keys=True),old_source))
            admission=con.execute('SELECT state FROM remediation_admissions WHERE source_task=?',(old_source,)).fetchone()
            if admission:
                old=json.loads(admission[0]);held={**old,'stage':'blocked','category':'superseded_by_r1_feedback',
                    'owner':route['cto'],'superseded_admission':old,'next_source':red['task_id']}
                con.execute('UPDATE remediation_admissions SET state=? WHERE source_task=?',(json.dumps(held,sort_keys=True),old_source))
            data=json.loads(row['data']);data['r1_feedback_plan']=dict(config_sha256=plans.digest(config),execution_authorized=False)
            handoffs.save(con,red['task_id'],issue,'technical_decision_required',route['cto'],data,time.time(),commit=False)
        return pending


def tick(b):
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='remediation_executions'").fetchone():return
        con.execute('CREATE TABLE IF NOT EXISTS remediation_r1_feedback_holds(issue_id TEXT PRIMARY KEY,state TEXT)')
        issues=[json.loads(r[0]).get('issue_id') for r in con.execute('SELECT state FROM remediation_executions')
            if json.loads(r[0]).get('stage')=='r1_base_qualified' and not json.loads(r[0]).get('superseded_by_feedback')]
    for issue in issues:
        if not issue:continue
        with b.db() as con:
            if con.execute('SELECT 1 FROM remediation_r1_feedback_holds WHERE issue_id=?',(issue,)).fetchone():continue
            row=con.execute('SELECT stage,data FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(issue,)).fetchone()
        if row and row[0]=='test_revision_required' and json.loads(row[1]).get('technical_replan_certificate'):
            try:register(b,issue)
            except Exception as error:
                if isinstance(error,(TimeoutError,ConnectionError)) or type(error).__name__ in ('URLError','DockerOperationTimeout','BudgetStatusUnavailable'):continue
                hold=dict(stage='technical_hold',owner=json.loads(row[1]).get('target'),
                    category=type(error).__name__,error_sha256=hashlib.sha256(str(error).encode()).hexdigest(),
                    required_action='CTO diagnose feedback intake or execute a new evidence-producing SPIKE; no identical retry',
                    execution_authorized=False,delivery_approval=False)
                with b.db() as con:
                    current=con.execute('SELECT stage,data FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(issue,)).fetchone()
                    if not current or tuple(current)!=tuple(row):continue
                    con.execute('INSERT OR IGNORE INTO remediation_r1_feedback_holds VALUES(?,?)',(issue,json.dumps(hold,sort_keys=True)))
                    data=json.loads(row[1]);data['r1_feedback_hold']=hold
                    data['required_action']=hold['required_action']
                    handoffs.save(con,data['source_task'],issue,'test_revision_blocked',hold['owner'],data,time.time(),commit=False)
