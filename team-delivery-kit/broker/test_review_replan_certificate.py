"""Certify an accepted immutable-test diagnosis, never fabricate Green evidence."""
import hashlib
import json
import re


def qualify(route,state,red,task,decision,reads,initial=False):
    diagnosis=state.get('rejection_diagnosis',{})
    paths=sorted('/evidence/'+tree+'/'+name for tree in
        (('candidate',) if initial else ('candidate','previous'))
        for name in route.get('test_first_files',[]))
    if (not paths or state.get('status')!='blocked' or state.get('evidence_policy')!=1
            or state.get('terminal_contract')!='typed-review-v1'
            or state.get('source_task')!=red['task_id']
            or state.get('manifest_sha256')!=red['red']['manifest_sha256']
            or not re.fullmatch(r'[a-f0-9]{64}',state.get('manifest_sha256',''))
            or not state.get('review_task') or state['review_task'] in (task.get('id'),red['task_id'])
            or diagnosis.get('status')!='revision_required' or diagnosis.get('decision_task')!=task.get('id')
            or diagnosis.get('decision')!=decision or diagnosis.get('target')!=route['cto']
            or task.get('status')!='completed' or task.get('issue_id')!=route['issue_id']
            or task.get('agent_id')!=route['cto'] or task.get('wakeup_id')!=diagnosis.get('wakeup_id')
            or route['cto'] in (route['author'],route['techlead'])
            or decision.get('action')!='request_test_revision' or decision.get('optional_files')!=[]
            or not isinstance(decision.get('reason'),str) or not 1<=len(decision['reason'])<=1200
            or not isinstance(decision.get('findings'),list) or not 1<=len(decision['findings'])<=3
            or any(type(reads.get(p,{}).get('lines')) is not int or reads[p]['lines']<=0
                or reads[p]['lines']!=reads[p].get('total_lines') for p in paths)):
        raise ValueError('accepted independent complete immutable-test diagnosis required')
    return dict(version='immutable-test-review-replan-v1',operation='qualified_immutable_test_cto_replan_v1',
        issue_id=route['issue_id'],source_task=red['task_id'],decision_task=task['id'],
        output_sha256=hashlib.sha256(json.dumps(decision,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        manifest_sha256=state['manifest_sha256'],independent_review_task=state['review_task'],
        read_contract='complete-lines-v2',required_read_paths=paths,read_evidence={p:reads[p] for p in paths},
        baseline_edits_allowed=False,delivery_approval=False,green_evidence=False)


def reconcile(b,issue,operation):
    """Reobserve one accepted decision under maintenance; no native replay."""
    try:import native,handoff_runtime,controller_maintenance,test_revision_review
    except ImportError:from broker import native,handoff_runtime,controller_maintenance,test_revision_review
    with b.LOCK,b.db() as con:
        barrier=controller_maintenance.current(con)
        if not barrier or barrier['stage']!='sealed' or barrier['operation_id']!=operation:
            raise ValueError('exact sealed maintenance required')
        config,state=map(json.loads,con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone())
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()[0])
        settings=json.loads((b.STATE/'native.json').read_text())
        task=native.task_record(settings,state['rejection_diagnosis']['decision_task'],route['cto'])
        fx=handoff_runtime.Effects(b,settings);decision=fx.decision(task)
        test_revision_review.validate_evidence(b,route,state,decision)
        proof=qualify(route,state,red,task,decision,fx.read_evidence(task),config.get('initial_review',False))
        if state.get('technical_replan_certificate') not in (None,proof):raise ValueError('replan certificate drift')
        state['technical_replan_certificate']=proof
    test_revision_review._save_rejection(b,route,state)
    return dict(qualified=True,decision_task=task['id'],model_calls=0,delivery_approval=False,green_evidence=False)
