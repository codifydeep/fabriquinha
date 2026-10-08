"""Independent diagnosis -> fixed experiment -> independently reviewed plan.

No worker endpoint, arbitrary command, test edit or automatic delivery approval.
Remote Docker intents are persisted before writes and reconciled by exact name.
"""
import json
import time
from types import SimpleNamespace
try:
    import technical_remediation_plan as plans,remediation_red_reference as refs
    import handoffs,native,handoff_runtime,harness_qualification as jobs
except ImportError:
    from broker import technical_remediation_plan as plans,remediation_red_reference as refs
    from broker import handoffs,native,handoff_runtime,harness_qualification as jobs
from service_mode_request_scope_experiment import supported
from service_mode_harness_qualification import TEST,PRODUCT

IMAGE='sha256:2ed20c7d541c5738aeb413ef6dfbd58e04c0e4de32feb993762d8e3a1d22a715'


def config(proposal,peer,result,reference,previous,route,volume):
    supported(result)
    if (peer.get('stage')!='peer_reviewed' or peer.get('execution_authorized') is not False
            or peer.get('decision',{}).get('action')!='request_test_revision' or not peer.get('task_id')
            or result.get('operation')!='immutable_request_scope_experiment_v1'
            or result.get('status')!='experiment_only_not_approved'
            or any(result.get(k) is not False for k in
                ('snapshot_modified','assertions_modified','test_edits_authorized','delivery_approval','product_green'))
            or result['test_sha256']!=reference['red']['red']['test_sha256'].get(TEST)
            or reference['source_task']!=previous['source_task']
            or reference['execution_contract_sha256']!=plans.digest(previous)
            or proposal['reference_sha256']!=plans.digest(reference)
            or proposal['criteria']!=previous['criteria'] or proposal['criteria']!=reference['criteria']
            or proposal['original_depth']!=2 or previous['original_depth']!=2
            or len(previous['revision_lineage'])!=2
            or previous.get('amendment',{}).get('kind')=='request_scope'
            or route['issue_id']!=proposal['issue_id'] or route['issue_id']!=reference['issue_id']
            or route['author']!=previous['steps'][1]['owner'] or route['techlead']!=proposal['reviewer']
            or len({route[k] for k in ('author','reviewer','techlead','cto')})!=4
            or route['contract_sha256']!=previous['contract_sha256']):
        raise ValueError('exact distinct independently supported request-scope plan required')
    amendment=dict(operation='inherited_harness_contract_amendment_v1',kind='request_scope',
        previous_source=previous['source_task'],previous_execution_sha256=plans.digest(previous),
        previous_amendment_sha256=plans.digest(previous.get('amendment')),
        peer_task=peer['task_id'],peer_decision_sha256=plans.digest(peer['decision']),
        experiment_sha256=plans.digest(result),seed_red=reference['red'],
        original_depth=2,revision_depth_reset=False,attempt_limit=1,execution_authorized=False,
        required_gates=['request_scope_background_control','behavioral_negative_controls',
            'real_red_on_original_base','independent_test_review','full_green',
            'independent_product_review','pr_ci_same_sha','deploy_browser_qa_same_sha'])
    return dict(source_task=proposal['source_task'],source_issue=route['issue_id'],root_issue=previous['root_issue'],
        original_depth=2,revision_lineage=previous['revision_lineage'],cto=route['cto'],reviewer=route['techlead'],
        original_author=route['author'],contract_sha256=route['contract_sha256'],
        context_sha256=route['execution_context']['sha256'],criteria=proposal['criteria'],base=previous['base'],
        volume=volume,required_paths=proposal['required_paths'],
        diagnostic_task=proposal['cto_task'],diagnostic_wakeup=proposal['cto_wakeup'],amendment=amendment,
        diagnostic_snapshot_kind='completed_frozen_validation',
        experiment=dict(operation='request_scope_experiment_reference_v1',receipt_sha256=plans.digest(result),
            proof=dict(input_sha256={TEST:result['test_sha256'],PRODUCT:result['product_sha256']},
                facts=dict(original_failures=3,scoped_failures=0,background_control_tests=result['background_control']['tests'],
                    negative_controls=len(result['negative_controls']),source_manifest=result['manifest_sha256'],
                    historical_tests_changed=False))))


def payload(b,source,volume):
    image=SimpleNamespace(IMAGE=IMAGE,docker=b.docker)
    return dict(Image=IMAGE,User='10000:10000',Entrypoint=['python'],
        Cmd=['/service_mode_request_scope_experiment.py','/delivery'],NetworkDisabled=True,
        Env=jobs.image_environment(image),
        Labels={'delivery-kit.owner':b.OWNER,'delivery-kit.source-task':source,'delivery-kit.purpose':'request-scope-experiment'},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],
            SecurityOpt=['no-new-privileges'],Memory=268435456,NanoCpus=1000000000,PidsLimit=64,
            Mounts=[dict(Type='volume',Source=volume,Target='/delivery',ReadOnly=True)],
            Tmpfs={'/tmp':'rw,nosuid,nodev,size=32m,mode=1777'}))


def continue_approved(b,source,result):
    """Continue only an already authorized root and independently approved plan."""
    try:import remediation_execution as execution,remediation_admission as admission,remediation_dispatch as dispatch
    except ImportError:from broker import remediation_execution as execution,remediation_admission as admission,remediation_dispatch as dispatch
    with b.db() as con:
        row=con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()
        if not row:return
        config,state=map(json.loads,row)
        if state['stage']!='plan_approved':return
        if (config.get('amendment',{}).get('kind')!='request_scope'
                or config['amendment']['experiment_sha256']!=plans.digest(result)):
            raise ValueError('exact independently reviewed request-scope evidence required')
        previous=config['amendment']['previous_source']
        old=con.execute('SELECT intent FROM remediation_admissions WHERE source_task=?',(previous,)).fetchone()
        if (not old or json.loads(old[0]).get('root_issue')!=config['root_issue']
                or json.loads(old[0]).get('execution_contract_sha256')!=config['amendment']['previous_execution_sha256']):
            raise ValueError('preserved authorized root admission required')
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():return
    execution_state=execution.register(b,source)
    if execution_state['stage'] in ('r1_issue_intent','r1_issue_post_pending','r1_issue_observe'):
        execution.provision_issue(b,source)
        return
    if execution_state['stage']=='r1_provision_pending':
        try:import remediation_preparation
        except ImportError:from broker import remediation_preparation
        remediation_preparation.prepare(b,source)
        return
    if execution_state['stage']!='r1_base_qualified':return
    if not execution_state.get('r1_runtime'):
        try:import remediation_author_context
        except ImportError:from broker import remediation_author_context
        remediation_author_context.prepare(b,source)
        return
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='remediation_native_contexts'").fetchone():return
        presented=con.execute('SELECT state FROM remediation_native_contexts WHERE source_task=? AND step=?',(source,'R1')).fetchone()
        if not presented or json.loads(presented[0]).get('stage')!='published':return
    fx=admission.Effects(b);bound=dispatch.binding(b,source,'R1',fx)
    if bound and not bound['enabled']:
        with b.db() as con:
            exists=con.execute('SELECT 1 FROM remediation_admissions WHERE source_task=?',(source,)).fetchone()
        if not exists:admission.request(b,source)


def failed_experiment_handoff(data, state, peer_task):
    """One different diagnostic action; never repeat the experiment or edit tests."""
    if (state.get('stage') != 'blocked' or type(state.get('exit_code')) is not int
            or state['exit_code'] == 0 or not state.get('container_id')
            or not data.get('artifact_diagnosis') or not data.get('validation_failure')):
        raise ValueError('verified failed frozen experiment required')
    if data.get('unsupported_experiment_recovery'):
        raise ValueError('unsupported experiment diagnostic already consumed')
    result = json.loads(json.dumps(data))
    result['unsupported_experiment_recovery'] = dict(
        operation='failed_frozen_experiment_diagnosis_v1', attempt_limit=1,
        container_id=state['container_id'], exit_code=state['exit_code'],
        output_sha256=state['output_sha256'], cause='unknown',
        test_edits_authorized=False, delivery_approval=False, author_restarted=False)
    result.update(request_scope_experiment_state=state, trigger_task=peer_task,
        required_action='CTO reassess failed experiment: supported product correction or explicit technical hold; no test edits')
    result['diagnostic_revision'] = result.get('diagnostic_revision', '') + ':failed-experiment:' + state['container_id']
    for key in ('wakeup_id', 'recipient_task', 'dispatch_marker', 'dispatch_stage', 'dispatched_at', 'instruction', 'decision'):
        result.pop(key, None)
    return result


def publish_failed_experiment(b, proposal, peer, state, expected):
    """Observe the exact owned exited job. No start, replay or verdict authority."""
    source = proposal['source_task']
    info = b.docker('GET', '/containers/' + state['container_id'] + '/json')
    jobs.verify_job(info, expected)
    if info['Id'] != state['container_id'] or info['State']['Status'] != 'exited' or info['State']['ExitCode'] == 0:
        return
    raw = b.docker_stdout(info['Id'], include_stderr=True, limit=32768)
    observed = {**state, 'exit_code': info['State']['ExitCode'], 'output_sha256': plans.digest(raw)}
    with b.LOCK, b.db() as con:
        current = handoffs.load(con, source)
        if not current or current['stage'] != 'inherited_replan_required': return
        data = json.loads(current['data'])
        if data.get('unsupported_experiment_recovery'): return
        if data.get('inherited_test_replan') != proposal or data.get('inherited_peer_review') != peer:
            raise ValueError('exact independent failed-experiment lineage required')
        route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                      (proposal['issue_id'],)).fetchone()[0])
        updated = failed_experiment_handoff(data, observed, peer['task_id'])
        updated['target'] = route['cto']
        con.execute('UPDATE request_scope_experiments SET state=? WHERE source_task=?',
                    (json.dumps(observed, sort_keys=True), source))
        handoffs.save(con, source, proposal['issue_id'], 'diagnose_cto', route['cto'], updated, time.time())


def tick_one(b,proposal,peer):
    try:return advance(b,proposal,peer)
    except (ValueError,TypeError,KeyError) as error:
        source=proposal['source_task']
        with b.db() as con:
            exists=con.execute("SELECT 1 FROM sqlite_master WHERE name='request_scope_experiments'").fetchone()
            if not exists:raise
            row=con.execute('SELECT state FROM request_scope_experiments WHERE source_task=?',(source,)).fetchone()
            if not row:raise
            state={**json.loads(row[0]),'stage':'blocked','error_type':type(error).__name__,
                'required_action':'CTO diagnose rejected request-scope continuation; no identical retry'}
            con.execute('UPDATE request_scope_experiments SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
            current=handoffs.load(con,source);data=json.loads(current['data'])
            data.update(request_scope_experiment_state=state,required_action=state['required_action'])
            handoffs.save(con,source,proposal['issue_id'],current['stage'],current['owner'],data,time.time())


def advance(b,proposal,peer):
    if peer.get('stage')!='peer_reviewed' or peer.get('decision',{}).get('action')!='request_test_revision':return
    source=proposal['source_task'];issue=proposal['issue_id']
    with b.LOCK,b.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS request_scope_experiments(source_task TEXT PRIMARY KEY,identity TEXT,state TEXT)')
        current=handoffs.load(con,source)
        if not current or current['stage']!='inherited_replan_required':return
        data=json.loads(current['data']);diagnostic=data.get('completed_validation_diagnostic')
        if not diagnostic:return  # Preserve the older failed-execution/syntax lane.
        if data.get('inherited_test_replan')!=proposal or data.get('inherited_peer_review')!=peer:
            raise ValueError('current independent request-scope evidence drift')
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        snap=con.execute('SELECT volume,status FROM snapshots WHERE task_id=?',(source,)).fetchone()
        if not snap or snap['status']!='complete' or snap['volume']!=diagnostic['volume']:
            raise ValueError('complete exact frozen validation snapshot required')
        volume=snap['volume'];row=con.execute('SELECT identity,state FROM request_scope_experiments WHERE source_task=?',(source,)).fetchone()
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():return
    reference=refs.qualified(b,issue)
    if reference is None or plans.digest(reference)!=proposal['reference_sha256']:
        raise ValueError('unchanged approved origin required for request-scope experiment')
    labels=(b.docker('GET','/volumes/'+volume) or {}).get('Labels',{})
    if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=source:
        raise ValueError('owned frozen experiment volume required')
    expected=payload(b,source,volume);name=b.PREFIX+'-request-scope-'+source
    identity=dict(source_task=source,issue_id=issue,volume=volume,proposal_sha256=plans.digest(proposal),
        peer_task=peer['task_id'],peer_decision_sha256=plans.digest(peer['decision']),payload=expected)
    if row:
        stored,state=map(json.loads,row)
        if stored!=identity:raise ValueError('request-scope job identity drift')
        if state['stage']=='blocked':
            if state.get('container_id'):
                publish_failed_experiment(b,proposal,peer,state,expected)
            return
        if state['stage']=='plan_registered':
            continue_approved(b,source,state['result'])
            return
        create=False
    else:
        state=dict(stage='create_intent',at=time.time());create=True
        with b.db() as con:
            con.execute('INSERT INTO request_scope_experiments VALUES(?,?,?)',(source,json.dumps(identity,sort_keys=True),json.dumps(state,sort_keys=True)))
    def save(new):
        with b.db() as con:
            con.execute('UPDATE request_scope_experiments SET state=? WHERE source_task=?',(json.dumps(new,sort_keys=True),source))
        return new
    if state['stage']=='create_intent':
        info=b.docker('GET','/containers/'+name+'/json')
        if not info and create:
            b.docker('POST','/containers/create?name='+name,expected)
            info=b.docker('GET','/containers/'+name+'/json')
        if not info:
            if time.time()-state['at']>=600:save({**state,'stage':'blocked','required_action':'CTO reconcile uncertain experiment create; no repeated POST'})
            return
        jobs.verify_job(info,expected)
        state=save(dict(stage='start_intent',container_id=info['Id'],at=time.time()))
        b.docker('POST','/containers/'+info['Id']+'/start')
        return
    info=b.docker('GET','/containers/'+state['container_id']+'/json');jobs.verify_job(info,expected)
    if info['State']['Running']:return
    if info['State']['Status']!='exited':
        if time.time()-state['at']>=600:save({**state,'stage':'blocked','required_action':'CTO reconcile uncertain experiment start; no identical retry'})
        return
    if info['State']['ExitCode']!=0:
        save({**state,'stage':'blocked','required_action':'CTO diagnose unsupported request-scope experiment; no test edit authority'})
        return
    raw=b.docker_stdout(info['Id'],include_stderr=False,limit=32768);result=json.loads(raw)
    with b.db() as con:
        previous=json.loads(con.execute('SELECT contract FROM remediation_executions WHERE source_task=?',(reference['source_task'],)).fetchone()[0])
    base=b.issue_base(issue)
    if any(base[k]!=previous['base'][k] for k in ('base_sha','manifest_sha256')):
        raise ValueError('original recovery base drift')
    value=config(proposal,peer,result,reference,previous,route,volume)
    settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
    for tid,actor,wake,decision in ((proposal['cto_task'],route['cto'],proposal['cto_wakeup'],proposal['cto_decision']),
        (peer['task_id'],route['techlead'],peer['wakeup_id'],peer['decision'])):
        task=native.task_record(settings,tid,actor);reads=fx.read_evidence(task)
        if (task['status']!='completed' or task['issue_id']!=issue or task['wakeup_id']!=wake
                or fx.decision(task)!=decision or any(reads.get(p,{}).get('lines',0)<=0
                    or reads[p]['lines']!=reads[p]['total_lines'] for p in value['required_paths'])):
            raise ValueError('live independent full-read diagnostic decisions required')
    author=native.task_record(settings,source,route['author'])
    if author['status']!='completed' or author['issue_id']!=issue:raise ValueError('exact completed source required')
    with b.LOCK,b.db() as con:
        if handoffs.load(con,source)!=current:raise ValueError('handoff changed during experiment')
        plans.initialize(con)
        existing=con.execute('SELECT config FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()
        if existing and json.loads(existing[0])!=value:raise ValueError('immutable request-scope plan drift')
        con.execute('INSERT OR IGNORE INTO technical_remediation_plans VALUES(?,?,?)',
            (source,json.dumps(value,sort_keys=True),json.dumps(dict(stage='issue_intent',owner=value['cto'],execution_authorized=False,release_homologated=False))))
        route['enabled']=False;con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(route,sort_keys=True),issue))
        data.update(request_scope_experiment=dict(result=result,identity_sha256=plans.digest(identity)),
            required_action='CTO propose evidence-bound request-scope amendment; independent plan review required')
        handoffs.save(con,source,issue,'inherited_replan_required',route['cto'],data,time.time())
        con.execute('UPDATE request_scope_experiments SET state=? WHERE source_task=?',
            (json.dumps({**state,'stage':'plan_registered','result':result,'result_sha256':plans.digest(result)},sort_keys=True),source))
