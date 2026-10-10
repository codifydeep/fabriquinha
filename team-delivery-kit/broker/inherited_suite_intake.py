"""One source-bound planning intake for a failed inherited frozen suite.

An exhausted diagnostic cannot adjudicate by itself. Reuse the existing typed
CTO plan / independent TL review / immutable R1-R2-R3 execution chain instead
of selecting a product-specific experiment from a prose decision.
"""
import copy
import hashlib
import json
import time
from pathlib import PurePosixPath
try:
    import technical_remediation_plan as plans, diagnostic_evidence_context as memory
    import remediation_red_reference as references, handoffs, native, handoff_runtime
except ImportError:
    from broker import technical_remediation_plan as plans, diagnostic_evidence_context as memory
    from broker import remediation_red_reference as references, handoffs, native, handoff_runtime


def configuration(row, route, previous, reference, task, binding, decision, reads):
    data=json.loads(row['data']);failure=data.get('validation_failure',{})
    context=data.get('diagnostic_evidence_context',{})
    proof=memory.verify_context(context,row['source_task'],failure,data.get('adjudication_spike',{}))
    capsule=plans.validate_capsule(route['execution_context'])
    tests=reference.get('red',{}).get('red',{}).get('test_sha256',{})
    files=sorted(set(failure.get('diagnostic_read_files',[]))|set(tests))
    for path in files:
        p=PurePosixPath(path)
        if p.is_absolute() or '..' in p.parts or '\\' in path or str(p)!=path:
            raise ValueError('canonical immutable evidence paths required')
    paths=['/evidence/candidate/'+p for p in files]
    previous_paths=['/evidence/previous/'+p for p in sorted(tests)]
    if (row['stage']!='technical_decision_required' or row['owner']!=route.get('cto')
            or data.get('source_task')!=row['source_task'] or data.get('source_status')!='completed'
            or route.get('issue_id')!=row['issue_id'] or not route.get('enabled')
            or len({route.get(k) for k in ('author','reviewer','techlead','cto')})!=4
            or any(not route.get(k) for k in ('author','reviewer','techlead','cto'))
            or data.get('target')!=route['cto'] or task.get('id')!=data.get('recipient_task')
            or task.get('agent_id')!=route['cto'] or task.get('issue_id')!=row['issue_id']
            or task.get('status')!='completed' or task.get('wakeup_id')!=data.get('wakeup_id')
            or binding.get('status')!='closed' or binding.get('task_id')!=task['id']
            or binding.get('agent_id')!=route['cto'] or binding.get('issue_id')!=row['issue_id']
            or binding.get('scope','').split(':')[-2:]!=['planning',task['id']]
            or decision!=data.get('decision') or decision.get('action')!='escalate_cto'
            or decision.get('optional_files')!=[] or not isinstance(decision.get('reason'),str)
            or not 1<=len(decision['reason'])<=1200
            or not data.get('unsupported_experiment_recovery')
            or failure.get('category')!='executed_test_failure'
            or failure.get('phase')!='frozen_green' or failure.get('exit_code')!=1 or not failure.get('failures')
            or data.get('completed_validation_diagnostic',{}).get('failure')!=failure
            or data['completed_validation_diagnostic'].get('status')!='diagnostic_only_not_approved'
            or reference.get('issue_id')!=row['issue_id'] or reference.get('origin_issue')==row['issue_id']
            or reference.get('source_task')!=previous.get('source_task')
            or reference.get('execution_contract_sha256')!=plans.digest(previous)
            or reference.get('criteria')!=previous.get('criteria')
            # R2 capsules contain a losslessly JSON-quoted original brief, not
            # the root Acceptance list. Bind the exact qualified route instead
            # of reparsing text from inside that quoted wrapper.
            or reference.get('route_sha256')!=plans.digest({k:v for k,v in route.items() if k!='enabled'})
            or reference.get('original_depth')!=2 or previous.get('original_depth')!=2
            or len(previous.get('revision_lineage',[]))!=2
            or previous.get('amendment',{}).get('kind')=='inherited_frozen_suite'
            or previous.get('baseline_edits_allowed') is not False
            or previous.get('historical_snapshots_editable') is not False
            or previous.get('release_homologated') is not False
            or route['author']!=previous['steps'][1]['owner']
            or route['contract_sha256']!=previous.get('contract_sha256')
            or not tests or not paths or len(paths)>32
            or any(type(reads.get(p,{}).get('lines')) is not int or reads[p]['lines']<=0
                or reads[p]['lines']!=reads[p].get('total_lines') for p in paths+previous_paths)):
        raise ValueError('exact completed inherited-suite technical hold and full evidence required')
    amendment=dict(operation='inherited_harness_contract_amendment_v1',kind='inherited_frozen_suite',
        previous_source=previous['source_task'],previous_execution_sha256=plans.digest(previous),
        previous_amendment_sha256=plans.digest(previous.get('amendment')),
        seed_red=reference['red'],experiment_sha256=context['proof_sha256'],
        original_depth=2,revision_depth_reset=False,attempt_limit=1,execution_authorized=False,
        required_gates=['preserved_methods_assertions','behavioral_negative_controls',
            'real_red_on_original_base','independent_test_review','full_green',
            'independent_product_review','pr_ci_same_sha','deploy_browser_qa_same_sha'])
    return copy.deepcopy(dict(source_task=row['source_task'],source_issue=row['issue_id'],
        root_issue=previous['root_issue'],original_depth=2,revision_lineage=previous['revision_lineage'],
        cto=route['cto'],reviewer=route['techlead'],original_author=route['author'],
        contract_sha256=route['contract_sha256'],context_sha256=capsule['sha256'],
        criteria=previous['criteria'],base=previous['base'],volume=failure['volume'],required_paths=paths,
        diagnostic_task=task['id'],diagnostic_wakeup=task['wakeup_id'],
        diagnostic_read_evidence={p:reads[p] for p in paths+previous_paths},
        diagnostic_snapshot_kind='completed_frozen_validation',
        intake_kind='exhausted_frozen_suite_v1',historical_failure=failure,
        preserved_source_attempts=data.get('attempts'),amendment=amendment,
        experiment=dict(operation='inherited_failed_suite_planning_reference_v1',
            proof=dict(input_sha256=tests,facts=dict(tests_executed=proof['suite']['tests'],
                failures=failure['failures'],tracing_observations_equal=True,
                runtime_assertion_observations=proof['observations'],
                diagnostic_proof_sha256=context['proof_sha256'],
                test_defect_proven=False,historical_tests_changed=False)))))


def qualify(b, source):
    """Observe only; no worker creation, test run, budget change or grant."""
    with b.db() as c:
        row=handoffs.load(c,source)
        if not row:raise ValueError('current inherited-suite source required')
        data=json.loads(row['data'])
        route=json.loads(c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
        if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():
            raise ValueError('idle inherited-suite scope required')
        snapshot=c.execute('SELECT volume,status FROM snapshots WHERE task_id=?',(source,)).fetchone()
        archived=c.execute('SELECT receipt FROM frozen_suite_failures WHERE task_id=?',(source,)).fetchone()
        diagnostic=c.execute('SELECT receipt FROM completed_validation_diagnoses WHERE source_task=?',(source,)).fetchone()
        bindings=c.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',
            (data.get('recipient_task'),)).fetchall()
        if not snapshot or not archived or not diagnostic or len(bindings)!=1:
            raise ValueError('durable frozen evidence and exact closed diagnostic required')
        failure=data.get('validation_failure',{})
        if (snapshot['status']!='complete' or snapshot['volume']!=failure.get('volume')
                or any(failure.get(k)!=v for k,v in json.loads(archived[0]).items())
                or json.loads(diagnostic[0])!=data.get('completed_validation_diagnostic')):
            raise ValueError('archived inherited failure identity drift')
        checks=c.execute("SELECT identity,state FROM validation_jobs WHERE json_extract(identity,'$.task')=? "
            "AND json_extract(identity,'$.kind')='green'",(source,)).fetchall()
    reference=references.qualified(b,row['issue_id'])
    if reference is None:raise ValueError('approved inherited Red required')
    with b.db() as c:
        previous=json.loads(c.execute('SELECT contract FROM remediation_executions WHERE source_task=?',
            (reference['source_task'],)).fetchone()[0])
        admission=c.execute('SELECT intent FROM remediation_admissions WHERE source_task=?',
            (previous['source_task'],)).fetchone()
        if (not admission or json.loads(admission[0]).get('root_issue')!=previous['root_issue']
                or json.loads(admission[0]).get('execution_contract_sha256')!=plans.digest(previous)):
            raise ValueError('already authorized unchanged recovery root required')
        author_bindings=c.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',
            (source,)).fetchall()
        latest=c.execute('SELECT task_id FROM native_bindings WHERE issue_id=? AND agent_id=? ORDER BY rowid DESC LIMIT 1',
            (row['issue_id'],route['author'])).fetchone()
        if (len(author_bindings)!=1 or author_bindings[0]['status']!='closed'
                or author_bindings[0]['agent_id']!=route['author'] or not latest or latest[0]!=source):
            raise ValueError('current closed author execution required')
    settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
    task=native.task_record(settings,data['recipient_task'],route['cto'])
    author=native.task_record(settings,source,route['author'])
    if (author.get('status')!='completed' or author.get('issue_id')!=row['issue_id']
            or any(t.get('status') in ('queued','running','dispatched') for t in native.issue_task_runs(settings,row['issue_id']))):
        raise ValueError('closed native inherited-suite scope required')
    labels=(b.docker('GET','/volumes/'+snapshot['volume']) or {}).get('Labels',{})
    if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=source:
        raise ValueError('controller-owned immutable candidate required')
    verified=[]
    for identity,state in checks:
        try:
            verify_hash_receipt(json.loads(identity),json.loads(state),source,snapshot['volume'],
                reference['red'],b.IMAGE,b.OWNER)
        except (ValueError,KeyError,TypeError):continue
        verified.append(identity)
    if len(verified)!=1:raise ValueError('one archived exact test-byte verification required; do not rerun')
    value=configuration(row,route,previous,reference,task,dict(bindings[0]),fx.decision(task),fx.read_evidence(task))
    return row,route,value


def verify_hash_receipt(identity, state, source, volume, red, image, owner):
    """Consume a completed byte check, not a functional Green or new Docker job."""
    try:import validation_job
    except ImportError:from broker import validation_job
    payload=identity['payload'];host=payload['HostConfig'];result=state.get('result',{})
    env=dict(item.split('=',1) for item in payload.get('Env',[]))
    mounts=host.get('Mounts',[])
    expected=[dict(Type='volume',Source=volume,Target='/delivery',ReadOnly=True),
              dict(Type='volume',Source=red['volume'],Target='/red',ReadOnly=True)]
    if (identity.get('task')!=source or identity.get('kind')!='green' or state.get('stage')!='complete'
            or payload.get('Image')!=image or payload.get('Entrypoint')!=['python']
            or payload.get('Cmd')!=['/test_first_verify.py'] or payload.get('NetworkDisabled') is not True
            or host.get('ReadonlyRootfs') is not True or host.get('NetworkMode')!='none' or mounts!=expected
            or payload.get('Labels',{}).get('delivery-kit.owner')!=owner
            or payload['Labels'].get('delivery-kit.source-task')!=source
            or set(env)!={'TEST_FIRST_TEST_HASHES','TEST_FIRST_RED_MANIFEST_SHA256'}
            or json.loads(env['TEST_FIRST_TEST_HASHES'])!=red['red']['test_sha256']
            or env['TEST_FIRST_RED_MANIFEST_SHA256']!=red['red']['manifest_sha256']
            or type(result.get('exit_code')) is not int or result['exit_code']!=0
            or result.get('approval') is not False or not isinstance(result.get('output'),str)
            or hashlib.sha256(result['output'].encode()).hexdigest()!=result.get('output_sha256')
            or result.get('validation_contract_sha256')!=validation_job.digest(identity)):
        raise ValueError('source-bound archived immutable test-byte check required')


def register(b, source):
    """Atomic once-only planning transition. Supervisor owns all native effects."""
    with b.LOCK:
        try:import controller_maintenance
        except ImportError:from broker import controller_maintenance
        with b.db() as c:
            plans.initialize(c)
            if controller_maintenance.current(c):raise ValueError('maintenance blocks new planning intake')
            prior=c.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()
            if prior:
                if json.loads(prior[0]).get('amendment',{}).get('kind')!='inherited_frozen_suite':
                    raise ValueError('foreign remediation plan already registered')
                return json.loads(prior[1])
        row,route,value=qualify(b,source)
        state=dict(stage='issue_intent',owner=value['cto'],execution_authorized=False,release_homologated=False)
        with b.db() as c:
            if not c.in_transaction:c.execute('BEGIN IMMEDIATE')
            current=handoffs.load(c,source)
            actual=json.loads(c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
            if (controller_maintenance.current(c) or current!=row or actual!=route or c.execute(
                    "SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):
                raise ValueError('inherited-suite scope changed before planning')
            c.execute('INSERT INTO technical_remediation_plans VALUES(?,?,?)',
                (source,json.dumps(value,sort_keys=True),json.dumps(state,sort_keys=True)))
            disabled={**route,'enabled':False}
            c.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(disabled,sort_keys=True),row['issue_id']))
            data=json.loads(row['data']);data.update(technical_remediation_plan=dict(
                source_task=source,original_depth=2,execution_authorized=False),
                required_action='CTO propose evidence-bound generic recovery; independent TL plan review required')
            handoffs.save(c,source,row['issue_id'],'technical_decision_required',route['cto'],data,time.time(),commit=False)
        return state


def validate_parent(con, config):
    """Recheck durable ancestry before the existing executor grants authority."""
    amendment=config['amendment']
    parent=con.execute('SELECT contract FROM remediation_executions WHERE source_task=?',
        (amendment['previous_source'],)).fetchone()
    admission=con.execute('SELECT intent FROM remediation_admissions WHERE source_task=?',
        (amendment['previous_source'],)).fetchone()
    failure=con.execute('SELECT receipt FROM frozen_suite_failures WHERE task_id=?',
        (config['source_task'],)).fetchone()
    if not parent or not admission or not failure:raise ValueError('preserved authorized parent required')
    value=json.loads(parent[0]);intent=json.loads(admission[0]);archive=json.loads(failure[0])
    if (amendment.get('kind')!='inherited_frozen_suite' or amendment.get('execution_authorized') is not False
            or plans.digest(value)!=amendment['previous_execution_sha256']
            or intent.get('execution_contract_sha256')!=plans.digest(value)
            or intent.get('root_issue')!=config['root_issue'] or value.get('root_issue')!=config['root_issue']
            or value.get('original_depth')!=config.get('original_depth') or config.get('original_depth')!=2
            or value['revision_lineage']!=config['revision_lineage'] or value['criteria']!=config['criteria']
            or value['base']!=config['base'] or value['contract_sha256']!=config['contract_sha256']
            or any(config['historical_failure'].get(k)!=v for k,v in archive.items())):
        raise ValueError('immutable inherited planning parent drift')


def tick(b):
    try:import controller_maintenance
    except ImportError:from broker import controller_maintenance
    with b.db() as c:
        plans.initialize(c)
        if controller_maintenance.current(c):return
        if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():return
        rows=c.execute("SELECT source_task,data FROM delivery_handoffs WHERE stage='technical_decision_required'").fetchall()
    for source,raw in rows:
        data=json.loads(raw)
        if (data.get('technical_remediation_plan') or not data.get('unsupported_experiment_recovery')
                or not data.get('diagnostic_evidence_context') or data.get('decision',{}).get('action')!='escalate_cto'):
            continue
        try:register(b,source)
        except (ValueError,KeyError,TypeError):
            # Preserve the technical hold. No alternative recipe, native write
            # or authority is inferred from failed qualification.
            continue
