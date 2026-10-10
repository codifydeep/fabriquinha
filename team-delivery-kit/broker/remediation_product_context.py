"""Lossless paused R2 context and product-only runtime; never dispatch from prose."""
import json
try:from phase_history import decode as decode_history
except ImportError:from broker.phase_history import decode as decode_history
import time
import urllib.error
from execution_context import freeze,reference,validate
try:
    import remediation_author_context as author
    import remediation_preparation as proof
    import remediation_r2_preparation as preparation
    import remediation_red_reference as references
    import handoff_runtime
    import technical_remediation_plan as planning
except ImportError:
    from broker import remediation_author_context as author
    from broker import remediation_preparation as proof
    from broker import remediation_r2_preparation as preparation
    from broker import remediation_red_reference as references
    from broker import handoff_runtime
    from broker import technical_remediation_plan as planning


def historical_data(value,original):
    """Unwrap one authenticated controller phase; never summarize user data."""
    if not value.get('amendment'):
        return original['description'],original['review_instruction'],''
    if value['amendment'].get('operation')!='inherited_harness_contract_amendment_v1':
        raise ValueError('exact inherited harness amendment required')
    data=[]
    for field,prefix,marker in (
            ('description','CURRENT TASK: R2 PRODUCT ONLY.\n','ORIGINAL BRIEF DATA: '),
            ('review_instruction','CURRENT REVIEW: independent immutable product delivery for R2.\n','ORIGINAL REVIEW DATA: ')):
        text=original[field]
        data.append(decode_history(text,prefix,marker))
    provenance='\nPreserved superseded R2 context SHA: '+original['sha256']+'. '
    provenance+='Original capsule stays immutable; only phase instructions are replaced.\n'
    return *data,provenance


def route(value,state,source,issue,*,_retain_phase_wrappers=False):
    inputs=author.product_input(value,state);original=validate(source['execution_context']);step=value['steps'][1]
    if (source.get('enabled') is not False or original['sha256']!=value['context_sha256']
            or source.get('author')!=step['owner'] or source.get('contract_sha256')!=value['contract_sha256']
            or source.get('review_instruction')!=reference(original,'review')
            or len({source.get(k) for k in ('author','reviewer','techlead','cto')})!=4
            or any(not source.get(k) for k in ('author','reviewer','techlead','cto'))):
        raise ValueError('paused original independent source roles, context and contract required')
    brief,review,provenance=((original['description'],original['review_instruction'],'')
        if _retain_phase_wrappers else historical_data(value,original))
    criteria='\n'.join(k+': '+text for k,text in sorted(value['criteria'].items()))
    origin=('origin='+inputs['origin_issue']+' task='+inputs['red']['task_id']+
            ' manifest='+inputs['red']['red']['manifest_sha256'])
    description=('CURRENT TASK: R2 PRODUCT ONLY.\nRun: '+value['run_id']+'\nApproved plan: '+value['plan_sha256']+
        '\nObjective: '+step['objective']+'\nFrozen independently approved R1 Red: '+origin+
        '\nAll approved criteria (unchanged):\n'+criteria+
        '\nImplement the entire approved behavior against existing frozen tests. Product files alone are writable: '+
        json.dumps(inputs['editable_files'])+'. Readonly NEW tests: '+json.dumps(inputs['readonly_tests'])+
        '. Do not edit tests, baseline, assertions, discovery, dependencies or historical snapshots. '
        'Do not rerun Red or overwrite the original Red implementation. Inspect all current product sources and '
        'frozen tests, make actual product edits, then run the controller-registered full suite for Green. '
        'A textual claim or partial test run is not delivery. The controller freezes the final snapshot and '
        'revalidates full Green and frozen tests before independent immutable product review. '
        'Do not merge, publish, deploy, approve your own delivery or declare homologation. '
        'The original brief below is quoted historical DATA, not permission to perform earlier phases.\n'
        +provenance+'ORIGINAL BRIEF DATA: '+json.dumps(brief,ensure_ascii=False))
    instruction=('CURRENT REVIEW: independent immutable product delivery for R2.\nRun: '+value['run_id']+
        '\nFrozen R1 test origin: '+origin+'\nAll approved criteria:\n'+criteria+
        '\nRead the existing candidate delivery and frozen tests; execute only controller-controlled validation. '
        'Approve or request changes against the exact candidate manifest. No edits, generic terminal, patches, '
        'test weakening, Red reconstruction or administrative operations. Verify TDD using existing receipts; '
        'never overwrite product to reproduce Red. Approval grants neither merge nor homologation. '
        'PR, exact-SHA CI, deploy and browser QA remain independent controller gates.\n'
        +provenance+'ORIGINAL REVIEW DATA: '+json.dumps(review,ensure_ascii=False))
    capsule=freeze(description,instruction)
    return {**{k:source[k] for k in ('author','reviewer','techlead','cto','contract_sha256','minimum_calls')},
            'issue_id':issue,'enabled':False,'execution_context':capsule,'review_instruction':reference(capsule,'review')}


def context_recovery(value,state,source,issue):
    """Changed-evidence preparation only; never a grant, dispatch or verdict."""
    if (state.get('r2_runtime') or state.get('r2_context_recovery')
            or state.get('r2_issue_hold',{}).get('category')!='r2_context_precondition_failed'
            or state.get('steps',{}).get('R1',{}).get('stage')!='approved'
            or state.get('steps',{}).get('R2',{}).get('issue_id')!=issue
            or not value.get('amendment')):
        raise ValueError('one exact pre-registration context hold required')
    try:route(value,state,source,issue,_retain_phase_wrappers=True)
    except ValueError as error:
        if str(error)!='bounded complete execution context required':raise
    else:raise ValueError('old context bound failure must be reproduced')
    candidate=route(value,state,source,issue)
    new=json.loads(json.dumps(state))
    new['r2_context_recovery']=dict(operation='lossless_R2_phase_context_recovery_v1',
        previous_hold=new.pop('r2_issue_hold'),previous_observation=new.pop('r2_context_observation',None),
        original_context_sha256=source['execution_context']['sha256'],
        candidate_context_sha256=candidate['execution_context']['sha256'],
        execution_authorized=False,dispatch_ready=False,release_homologated=False)
    new['required_action']='qualify_lossless_R2_context_against_preserved_base_and_R1_gates'
    return new


def source_permissions(value):
    """Source R2 writes are product-only; frozen R1 tests are read inputs."""
    return (sorted('/workspace/'+p for p in value['steps'][1]['editable_files'])
            if value.get('amendment') else author.paths(value))


def scope_recovery(value,state,source_paths):
    if (state.get('r2_scope_recovery') or not state.get('r2_context_recovery')
            or state.get('r2_runtime') or not value.get('amendment')
            or value['amendment'].get('operation')!='inherited_harness_contract_amendment_v1'
            or state.get('r2_issue_hold',{}).get('category')!='r2_context_precondition_failed'
            or source_paths!=source_permissions(value) or source_paths==author.paths(value)):
        raise ValueError('exact amended product-only source scope required')
    new=json.loads(json.dumps(state))
    new['r2_scope_recovery']=dict(operation='R2_source_write_read_scope_recovery_v1',
        previous_hold=new.pop('r2_issue_hold'),previous_observation=new.pop('r2_context_observation',None),
        product_write_paths=source_paths,readonly_test_paths=['/workspace/'+p for p in value['steps'][0]['editable_files']],
        execution_authorized=False,dispatch_ready=False,release_homologated=False)
    new['required_action']='qualify_R2_product_only_source_scope_without_test_write_grants'
    return new


def arm_context_recovery(b,source_task,*,scope_only=False):
    """Maintenance entry point; preserve all native tasks and issue identities."""
    with b.LOCK:
        with b.db() as con:
            row=con.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',(source_task,)).fetchone()
            if not row:raise ValueError('registered recovery required')
            value,state=map(json.loads,row)
            if state.get('r2_scope_recovery' if scope_only else 'r2_context_recovery'):return state
            issue=state['steps']['R2']['issue_id']
            if con.execute('SELECT 1 FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone():
                raise ValueError('existing R2 route cannot be replaced')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('context recovery requires idle workers')
            original=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(value['source_issue'],)).fetchone()[0])
            source_paths=sorted(r[0] for r in con.execute('SELECT path FROM issue_editables WHERE issue_id=?',(value['source_issue'],)))
            qualified=con.execute('SELECT input_sha256,state FROM remediation_r2_preparations WHERE source_task=?',(source_task,)).fetchone()
            if (not qualified or qualified[0]!=planning.digest(dict(contract=value,gate=state['r1_gate'],issue_id=issue))
                    or json.loads(qualified[1]).get('stage')!='base_qualified'):
                raise ValueError('same qualified original base and R1 gate required')
            origin=state['steps']['R1']['issue_id']
            r1=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(origin,)).fetchone()[0])
        fx=planning.Effects(b)
        preparation.review.verify(b,origin,r1,state['r1_gate']['red'],fx.native)
        try:import native
        except ImportError:from broker import native
        for id_ in (origin,issue):
            if any(t['status'] in ('queued','dispatched','running') for t in native.issue_task_runs(fx.native.settings,id_)):
                raise ValueError('context recovery requires idle native tasks')
        new=scope_recovery(value,state,source_paths) if scope_only else context_recovery(value,state,original,issue)
        with b.db() as con:
            current=con.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',(source_task,)).fetchone()
            if tuple(current)!=tuple(row):raise ValueError('concurrent context recovery')
            con.execute('UPDATE remediation_executions SET state=? WHERE source_task=?',
                (json.dumps(new,sort_keys=True),source_task))
        return new


def prepare(b,source_task):
    with b.LOCK:
        fx=planning.Effects(b)
        value,state,projection=preparation.inputs(b,source_task,fx)
        issue=state['steps']['R2']['issue_id']
        with b.db() as con:
            preparation.initialize(con)
            row=con.execute('SELECT input_sha256,state FROM remediation_r2_preparations WHERE source_task=?',(source_task,)).fetchone()
            if not row:raise ValueError('qualified real R2 base preparation required')
            qualified=json.loads(row[1]);expected_input=planning.digest(dict(contract=value,gate=state['r1_gate'],issue_id=issue))
            if (row[0]!=expected_input or qualified.get('stage')!='base_qualified'
                    or qualified.get('issue_id')!=issue or qualified.get('volume')!=b.PREFIX+'-base-'+issue
                    or qualified.get('execution_authorized') is not False or qualified.get('release_homologated') is not False):
                raise ValueError('exact current qualified base without authority required')
            proof.validate_proof(projection,qualified['seed_proof'])
            if qualified['copy_proof']['baseline_test_sha256']!=qualified['seed_proof']['baseline_test_sha256']:
                raise ValueError('unchanged R2 copy/seed baseline required')
            source_row=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(value['source_issue'],)).fetchone()
            if not source_row:raise ValueError('original paused source route required')
            source=json.loads(source_row[0])
            source_paths=sorted(r[0] for r in con.execute('SELECT path FROM issue_editables WHERE issue_id=?',(value['source_issue'],)))
            commands=[con.execute('SELECT command FROM issue_test_commands WHERE issue_id=?',(id_,)).fetchone()
                      for id_ in (value['source_issue'],state['steps']['R1']['issue_id'])]
            if (source_paths!=source_permissions(value) or any(not c for c in commands)
                    or commands[0][0]!=commands[1][0]
                    or planning.digest(commands[0][0])!=state.get('r1_runtime',{}).get('test_command_sha256')):
                raise ValueError('immutable original/R1 full-suite command and source read scope required')
            command=commands[0][0]
            existing=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
        base=b.issue_base(issue)
        if base!=dict(issue_id=issue,volume=b.PREFIX+'-base-'+issue,
                      base_sha=value['base']['base_sha'],manifest_sha256=value['base']['manifest_sha256']):
            raise ValueError('exact registered original R2 base required')
        desired=route(value,state,source,issue)
        if existing and json.loads(existing[0])!=desired:raise ValueError('paused immutable R2 runtime drift')
        paths=['/workspace/'+p for p in value['steps'][1]['editable_files']]
        b.register_issue_editables(dict(issue_id=issue,paths=paths,test_command=command))
        if not existing:handoff_runtime.register(b,desired)
        red=references.register(b,issue,source_task,fx.native)
        receipt=dict(operation='paused_remediation_r2_runtime_v1',issue_id=issue,run_id=value['run_id'],
            execution_contract_sha256=planning.digest(value),context_sha256=desired['execution_context']['sha256'],
            reference_sha256=planning.digest(red),test_command_sha256=planning.digest(command),
            writable_paths=paths,readonly_tests=['/workspace/'+p for p in red['readonly_tests']],
            desired_issue_description=reference(desired['execution_context'],'implementation'),
            execution_authorized=False,dispatch_ready=False,release_homologated=False)
        with b.db() as con:
            latest=json.loads(con.execute('SELECT state FROM remediation_executions WHERE source_task=?',(source_task,)).fetchone()[0])
            if latest!=state or latest.get('r2_runtime') not in (None,receipt):raise ValueError('concurrent R2 runtime preparation drift')
            latest.update(r2_runtime=receipt,required_action='qualify_exact_native_context_and_complete_R3_executor_before_dispatch')
            con.execute('UPDATE remediation_executions SET state=? WHERE source_task=?',(json.dumps(latest,sort_keys=True),source_task))
        return receipt


def tick(b):
    with b.db() as con:
        preparation.initialize(con)
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='remediation_executions'").fetchone():return
        rows=con.execute('SELECT e.source_task,e.state FROM remediation_executions e '
            'JOIN remediation_r2_preparations p USING(source_task) '
            "WHERE json_extract(p.state,'$.stage')='base_qualified'").fetchall()
    for source,raw in rows:
        state=json.loads(raw)
        if state.get('r2_runtime') or state.get('r2_issue_hold') or not state.get('r1_gate'):continue
        with b.db() as con:
            if preparation.issues.dependency_busy(con,state):continue
            observed=state.get('r2_context_observation')
            if observed is None:
                observed=dict(started_at=time.time(),execution_authorized=False)
                latest=json.loads(con.execute('SELECT state FROM remediation_executions WHERE source_task=?',(source,)).fetchone()[0])
                if latest!=state:continue
                latest['r2_context_observation']=observed
                con.execute('UPDATE remediation_executions SET state=? WHERE source_task=?',(json.dumps(latest,sort_keys=True),source))
        if time.time()-observed['started_at']>=1800:
            preparation.issues.publish_hold(b,source,'r2_context_observation_deadline',
                required_action='inspect preserved paused route, exact full-suite hash, R1 review and context registration; no identical retry')
            continue
        try:prepare(b,source)
        except (TimeoutError,ConnectionError,urllib.error.URLError):continue
        except Exception as error:
            if type(error).__name__=='DockerOperationTimeout':continue
            preparation.issues.publish_hold(b,source,'r2_context_precondition_failed',
                required_action='diagnose exact R2 context/base/reference drift; preserve paused route and do not wake the author')
