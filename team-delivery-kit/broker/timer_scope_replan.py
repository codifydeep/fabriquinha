"""Measured timer misattribution -> CTO plan -> independent review, never edits.

Preserve failed request-scope experiments and prior approvals. New plans demand
new timer attribution controls; their registration is planning authority only.
"""
import json
import re
import time
try:
    import handoffs,native,handoff_runtime,technical_remediation_plan as plans,remediation_red_reference as refs
except ImportError:
    from broker import handoffs,native,handoff_runtime,technical_remediation_plan as plans,remediation_red_reference as refs
from service_mode_harness_qualification import TEST,PRODUCT


def observation(value):
    result=value['result'];report=result['original_report'];suite=result['original_suite']
    if (result.get('operation')!='immutable_harness_timer_observation_v1'
            or result.get('instrumentation_preserved_report') is not True
            or any(result.get(k) is not False for k in ('snapshot_modified','assertions_modified',
                'test_edits_authorized','product_green','delivery_approval'))
            or value.get('snapshot_readonly') is not True or value.get('network')!='none'
            or not re.fullmatch(r'sha256:[a-f0-9]{64}',value.get('image',''))
            or suite.get('tests')!=15 or suite.get('failures')!=2
            or any(suite.get(k)!=0 for k in ('errors','skipped','unexpected_successes','expected_failures'))
            or set(suite.get('failed_methods',[]))!={'test_no_timers_are_armed_for_the_probe',
                'test_pending_probe_shows_checking_then_terminal_demo'}
            or report.get('interval_count')!=1 or report.get('pending_interval_count')!=1
            or report.get('timer_count')!=0 or report.get('pending_timer_count')!=0
            or report.get('after_ok',{}).get('calls')!=1 or report.get('pending_observed',{}).get('calls')!=1
            or report.get('pending_issued')!=1 or report.get('mode_request_total')!=9):
        raise ValueError('exact immutable timer attribution observation required')
    timers=result['timer_observation']['timers'];captures=result['timer_observation']['captures']
    origins={line for timer in timers for line in timer['stack']}
    if (len(timers)!=9 or len(origins)!=1 or any(t['ms']!=2000 for t in timers)
            or sorted(t['load_id'] for t in timers)!=list(range(1,10))
            or not re.fullmatch(r'\s*at /delivery/app/static/app\.js:\d+:\d+',next(iter(origins),'') )
            or len(captures)!=16):
        raise ValueError('complete same-origin board timer observations required')
    for load in range(1,9):
        expected=[dict(kind='timeout',load_id=load,slice_start=0,total=0),
                  dict(kind='interval',load_id=load,slice_start=load-1,total=load)]
        if captures[(load-1)*2:load*2]!=expected:raise ValueError('exact per-load timer slices required')
    return dict(original_failures=2,probe_requests_per_load=1,initial_timeouts=0,pending_timeouts=0,
        counted_intervals_per_load=1,timer_origin=next(iter(origins)).strip(),
        historical_tests_changed=False,observation_only=True,timer_controls_required=True)


def config(value,reference,previous,route,data,task,reads):
    facts=observation(value);result=value['result']
    paths=sorted('/evidence/candidate/'+p for p in set(reference['readonly_tests'])|set(reference['editable_files']))
    if (value['source_task']!=data['source_task'] or value['issue_id']!=route['issue_id']
            or reference['issue_id']!=route['issue_id'] or reference['source_task']!=previous['source_task']
            or reference['execution_contract_sha256']!=plans.digest(previous)
            or previous['original_depth']!=2 or len(previous['revision_lineage'])!=2
            or previous.get('amendment',{}).get('kind')=='timer_provenance'
            or reference['criteria']!=previous['criteria'] or reference['original_depth']!=2
            or result['test_sha256']!=reference['red']['red']['test_sha256'].get(TEST)
            or len({route[k] for k in ('author','reviewer','techlead','cto')})!=4
            or route.get('enabled') is not True or route['author']!=previous['steps'][1]['owner']
            or route['contract_sha256']!=previous['contract_sha256']
            or task.get('id')!=data.get('recipient_task') or task.get('agent_id')!=route['cto']
            or task.get('issue_id')!=route['issue_id'] or task.get('status')!='completed'
            or task.get('wakeup_id')!=data.get('wakeup_id') or data.get('target')!=route['cto']
            or data.get('validation_failure',{}).get('phase')!='frozen_green'
            or data['validation_failure'].get('category')!='executed_test_failure'
            or data['validation_failure'].get('exit_code')!=1
            or data['validation_failure'].get('source_task')!=value['source_task']
            or data.get('decision',{}).get('action')!='escalate_cto'
            or data.get('decision',{}).get('optional_files')!=[] or not data.get('unsupported_experiment_recovery')
            or any(reads.get(p,{}).get('lines',0)<=0 or reads[p]['lines']!=reads[p].get('total_lines') for p in paths)):
        raise ValueError('unchanged inherited scope and complete independent CTO observation required')
    amendment=dict(operation='inherited_harness_contract_amendment_v1',kind='timer_provenance',
        previous_source=previous['source_task'],previous_execution_sha256=plans.digest(previous),
        previous_amendment_sha256=plans.digest(previous.get('amendment')),experiment_sha256=plans.digest(result),
        seed_red=reference['red'],original_depth=2,revision_depth_reset=False,attempt_limit=1,execution_authorized=False,
        required_gates=['legitimate_board_timer_control','probe_timer_behavioral_negative_controls',
            'preserved_methods_assertions','real_red_on_original_base','independent_test_review','full_green',
            'independent_product_review','pr_ci_same_sha','deploy_browser_qa_same_sha'])
    return dict(source_task=value['source_task'],source_issue=route['issue_id'],root_issue=previous['root_issue'],
        original_depth=2,revision_lineage=previous['revision_lineage'],cto=route['cto'],reviewer=route['techlead'],
        original_author=route['author'],contract_sha256=route['contract_sha256'],context_sha256=route['execution_context']['sha256'],
        criteria=reference['criteria'],base=previous['base'],volume=data['validation_failure']['volume'],required_paths=paths,
        diagnostic_task=task['id'],diagnostic_wakeup=task['wakeup_id'],amendment=amendment,
        diagnostic_snapshot_kind='completed_frozen_validation',diagnostic_read_evidence=reads,
        experiment=dict(operation='timer_attribution_observation_reference_v1',receipt_sha256=plans.digest(value),
            proof=dict(input_sha256={TEST:result['test_sha256'],PRODUCT:result['product_sha256']},facts=facts)))


def register(b,source):
    with b.LOCK,b.db() as con:
        plans.initialize(con)
        old=con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()
        if old:return json.loads(old['state'])
        row=handoffs.load(con,source)
        if not row or row['stage']!='technical_decision_required':raise ValueError('current CTO technical hold required')
        data=json.loads(row['data']);route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
        recorded=con.execute('SELECT receipt FROM frozen_harness_observations WHERE source_task=?',(source,)).fetchone()
        if not recorded:raise ValueError('durable real timer observation required')
        value=json.loads(recorded[0]);reference=refs.qualified(b,row['issue_id'])
        if not reference:raise ValueError('approved inherited original Red required')
        previous=json.loads(con.execute('SELECT contract FROM remediation_executions WHERE source_task=?',(reference['source_task'],)).fetchone()[0])
        fx=handoff_runtime.Effects(b,json.loads((b.STATE/'native.json').read_text()))
        if any(fx.settings['agents'].get(route[k])!=mode for k,mode in
               [('author','implementation'),('reviewer','review'),('techlead','planning'),('cto','planning')]):
            raise ValueError('independent configured planning roles required')
        task=native.task_record(fx.settings,data['recipient_task'],route['cto'])
        if fx.decision(task)!=data.get('decision'):raise ValueError('native CTO decision drift')
        candidate=config(value,reference,previous,route,data,task,fx.read_evidence(task))
        latest=con.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(row['issue_id'],)).fetchone()
        snap=con.execute('SELECT volume,status FROM snapshots WHERE task_id=?',(source,)).fetchone()
        if (not snap or snap['status']!='complete' or snap['volume']!=candidate['volume'] or latest[0]!=source
                or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
                or any(r['status'] not in ('completed','failed','cancelled','canceled') for r in native.issue_task_runs(fx.settings,row['issue_id']))):
            raise ValueError('idle latest immutable diagnosis required')
        labels=(b.docker('GET','/volumes/'+snap['volume']) or {}).get('Labels',{})
        if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=source:
            raise ValueError('owned frozen timer observation required')
        state=dict(stage='issue_intent',owner=route['cto'],execution_authorized=False,release_homologated=False)
        con.execute('INSERT INTO technical_remediation_plans VALUES(?,?,?)',(source,json.dumps(candidate,sort_keys=True),json.dumps(state,sort_keys=True)))
        route['enabled']=False;con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(route,sort_keys=True),row['issue_id']))
        data.update(timer_observation_plan=dict(receipt_sha256=plans.digest(value),execution_authorized=False),
                    required_action='CTO plan timer attribution repair; independent review and new timer controls required')
        handoffs.save(con,source,row['issue_id'],'inherited_replan_required',route['cto'],data,time.time())
        return state


def tick(b):
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='frozen_harness_observations'").fetchone():return
        con.execute('CREATE TABLE IF NOT EXISTS timer_plan_intakes(source_task TEXT PRIMARY KEY,state TEXT)')
        rows=con.execute("SELECT o.source_task,t.state FROM frozen_harness_observations o JOIN delivery_handoffs h USING(source_task) "
            "LEFT JOIN timer_plan_intakes t USING(source_task) WHERE h.stage='technical_decision_required'").fetchall()
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():return
    for row in rows:
        if row['state'] and json.loads(row['state']).get('stage')!='qualification_intent':continue
        source=row['source_task']
        with b.db() as con:
            con.execute('INSERT OR IGNORE INTO timer_plan_intakes VALUES(?,?)',(source,json.dumps(dict(stage='qualification_intent',at=time.time()))))
        # Registration has no remote write. A crash can safely reconcile its
        # atomic local plan insertion; existing plans are returned unchanged.
        try:state=register(b,source)
        except Exception as error:
            state=dict(stage='blocked',category=type(error).__name__,execution_authorized=False,
                required_action='CTO diagnose timer observation intake; no identical retry')
        with b.db() as con:
            con.execute('UPDATE timer_plan_intakes SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
            if state.get('stage')=='blocked':
                current=handoffs.load(con,source)
                data=json.loads(current['data'])
                data.update(timer_plan_intake=state,required_action=state['required_action'])
                handoffs.save(con,source,current['issue_id'],current['stage'],current['owner'],data,time.time())
    with b.db() as con:
        plans.initialize(con)
        ready=con.execute('SELECT p.source_task,p.config,p.state,o.receipt FROM technical_remediation_plans p '
            'JOIN frozen_harness_observations o USING(source_task)').fetchall()
    for row in ready:
        candidate,state,value=map(json.loads,(row['config'],row['state'],row['receipt']))
        if candidate.get('amendment',{}).get('kind')!='timer_provenance' or state.get('stage')!='plan_approved':continue
        observation(value)
        try:import request_scope_replan
        except ImportError:from broker import request_scope_replan
        request_scope_replan.continue_approved(b,row['source_task'],value['result'],kind='timer_provenance')
