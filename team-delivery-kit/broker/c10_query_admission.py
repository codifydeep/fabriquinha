"""Once-only QUERY admission after a new evidence-grounded readonly CTO decision."""
import copy
import hashlib
import json
from pathlib import Path
import re
import time
import uuid
try:
    import c10_checkpoint_contract as gates,c10_syntax_recovery as syntax
    import maintenance_delivery as delivery,native,handoff_runtime,admission_controls_spike
except ImportError:
    from broker import c10_checkpoint_contract as gates,c10_syntax_recovery as syntax
    from broker import maintenance_delivery as delivery,native,handoff_runtime,admission_controls_spike


def prepare_intake(state):
    available=state.get('c10_decomposition',{}).get('checkpoint_contract_available',{})
    if (state.get('c10_query_intake') or state.get('c10_checkpoints')
            or state.get('stage')!='blocked' or state.get('category')!='c10_decomposition_semantic_contradiction'
            or state['c10_decomposition'].get('author_scope_authorized') is not False
            or available.get('schema')!=gates.SCHEMA):
        raise ValueError('new QUERY contract after rejected decomposition required')
    seed=state['c10_decomposition']['current_seed']
    if (seed['task_id']!=state['author_task'] or seed['snapshot']!=state['snapshot']
            or seed['validation']!=state['validation']):
        raise ValueError('exact unchanged current QUERY seed required')
    revised=copy.deepcopy(state)
    revised['c10_query_intake']={'seed':seed,'prior_receipt':revised.pop('functional_diagnosis_receipt'),
        'prior_diagnosis':state['functional_diagnosis'],'attempt_limit':1,
        'author_scope_authorized':False,'delivery_approval':False,'at':time.time()}
    note=('CTO READONLY NEW QUERY ONLY GATE ADMISSION. Read all four files completely. '
        'This is NOT another broad C10/STATUS plan: the controller now has separate '
        'QUERY and STATUS validation gates. Decide ONLY if the frozen QUERY correction '
        'is supported. Source facts to verify: tests/test_incremental_u3.py lines '
        '512/515/528/531 resolve bare arrays; product app.js397 consumes data.items. '
        'Therefore do NOT claim that gamma/current-stale rendering already works. '
        'QUERY gate permits exactly wrapping those four unchanged fixture arrays as '
        '{items:[...]}, with no other byte changed. STATUS534-536 stays untouched '
        'and blocked. Controller runs full259 tests: only missing status_genA_urls '
        'in C10 may remain as an ERROR. That is PARTIAL, not Green or approval. '
        'No combined rewrite, status implementation, C09 changes or CEO technical '
        'question. Decide from source, not from the preceding rejected reasoning. '
        'If supported, action=request_test_revision, optional_files=[], reason starts '
        'exactly DRIVER_OBSERVATION: and states QUERY, TEST path, 512/515/528/531, '
        'items envelopes, STATUS blocked, 259, status_genA_urls and PARTIAL. Target '
        '350chars, maximum900. Otherwise action=escalate_cto, reason=UNRESOLVED: '
        'with concrete contradiction. Immutable reads only, no writes, terminal, '
        'approval, model/cap change. A valid decision is NOT automatic author admission.\n'
        'DELIVERY_CURRENT_HARNESS_DIAGNOSIS_V1\nDELIVERY_STRUCTURED_DECISION_V1:technical\n'
        'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\n'
        'DELIVERY_DETERMINISTIC_READ_V1\n'+
        ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in delivery.paths()))
    revised['functional_diagnosis']=dict(state['functional_diagnosis'],note=note,at=time.time())
    revised.update(stage='maintenance_functional_diagnosis_dispatch',category='c10_new_query_gate_intake',delivery_approval=False)
    return revised


def qualify_authority(state):
    intake=state['c10_query_intake'];report=state['functional_diagnosis_receipt'];seed=intake['seed']
    cert=report['certificate'];decision=report['decision'];reason=decision.get('reason','')
    terms=('QUERY','tests/test_incremental_u3.py','512','515','528','531','items','STATUS','259','status_genA_urls','PARTIAL')
    if (intake.get('attempt_limit')!=1 or report.get('classification')!='DRIVER_OBSERVATION'
            or decision.get('action')!='request_test_revision' or decision.get('optional_files')!=[]
            or not isinstance(reason,str) or not reason.startswith('DRIVER_OBSERVATION: ')
            or any(t not in reason for t in terms) or not 1<=len(reason)<=1200
            or not re.search(r'STATUS.{0,40}(?:blocked|not authorized|untouched)',reason,re.I)
            or re.search(r'(?:already|still)\s+(?:works|work|passes|pass)',reason,re.I)
            or cert.get('snapshot')!=seed['snapshot']['volume']
            or cert.get('test_sha256')!=seed['validation']['test_sha256']
            or cert.get('decision_sha256')!=hashlib.sha256(json.dumps(decision,sort_keys=True).encode()).hexdigest()
            or not cert.get('task_id') or seed['snapshot']!=state['snapshot'] or seed['validation']!=state['validation']):
        raise ValueError('exact new QUERY-only CTO authority required')
    return report


def author_note(state):
    cp=state['c10_checkpoints'];seed=cp['seed']
    return ('ISOLATED QUERY-ONLY HARNESS CHECKPOINT. Scope '+cp['scope_id']+'. '
        'Read /workspace/tests/test_incremental_u3.py completely. Use surgical_test_edit '
        'typed V4 FILE line ranges. In ONE edit, wrap only the four existing bare-array '
        'responses at absolute lines512,515,528,531 as {items:[...]}; keep every fixture '
        'value and all whitespace outside these insertions. Use FOUR one-line ranges '
        '512-512,515-515,528-528,531-531 and expected_sha256='+seed['validation']['test_sha256']+'. '
        'Do not alter C10STATUS, callbacks, closures, C09, preamble, assertions, product '
        'or discovery; no generic writes, shell, Red, approvals or tool-approval requests. '
        'One author attempt, no replay of consumed scopes. Stop after a successful edit; '
        'the controller snapshots and runs full259 tests. ONLY missing status_genA_urls '
        'in C10 is expected PARTIAL. That is NOT Green or delivery. STATUS remains blocked '
        'and needs separate authority. Final<=32768bytes. Never fabricate results.\n'
        'DELIVERY_DRIVER_CHECKPOINT_V3\n')


def prepare_authorization(config,state,remaining):
    if (state.get('c10_checkpoints') or state.get('stage')!='blocked'
            or state.get('category')!='maintenance_diagnosis_driver_observation'
            or config['author']==config['cto'] or remaining<48
            or state.get('c10_decomposition',{}).get('checkpoint_contract_available',{}).get('phase_author_capability_installed') is not True):
        raise ValueError('idle new QUERY admission with independent CTO and48-call reserve required')
    authority=qualify_authority(state)
    seed=state['c10_query_intake']['seed'];guard=state['staged']['driver_guard'];proof=guard['qualification']
    try:import harness_repair_task as h
    except ImportError:from broker import harness_repair_task as h
    if (state['staged'].get('current')!=2 or not h.checkpoint_passed(seed['validation']) or proof.get('worker_image')!=guard.get('worker_image')
            or proof.get('status')!='passed' or proof.get('schema')!='surgical-driver-registry-probe-v3'
            or proof.get('uid')!=10000 or proof.get('network')!='none' or proof.get('delivery_approval') is not False
            or not re.fullmatch(r'sha256:[a-f0-9]{64}',guard.get('worker_image',''))
            or any(proof.get(k) is not True for k in syntax.FLAGS)):
        raise ValueError('qualified frozen surgical worker and valid QUERY seed required')
    revised=copy.deepcopy(state)
    prior={k:revised.pop(k) for k in ('functional_correction','functional_fragment_recovery','c10_syntax_recovery') if k in revised}
    cp={'schema':gates.SCHEMA,'phase':'QUERY','seed':seed,'authority':authority,'prior':prior,
        'scope_id':hashlib.sha256(('QUERY:'+authority['certificate']['task_id']+':'+seed['validation']['test_sha256']).encode()).hexdigest(),
        'qualification':proof,'worker_image':guard['worker_image'],'attempt_limit':1,
        'admission_code_sha256':gates.sha(Path(__file__).read_bytes()),
        'author_scope_authorized':True,'status_scope_authorized':False,'delivery_approval':False,'at':time.time()}
    revised['c10_checkpoints']=cp;cp['note_sha256']=hashlib.sha256(author_note(revised).encode()).hexdigest()
    revised['c10_query_intake']['author_scope_authorized']=True
    revised.update(stage='checkpoint_dispatch_intent',category='c10_query_phase_authorized',delivery_approval=False)
    return revised


def seed_binding(state,receipt):
    cp=state.get('c10_checkpoints',{})
    if (cp.get('schema')!=gates.SCHEMA or cp.get('phase')!='QUERY' or cp.get('attempt_limit')!=1
            or cp.get('author_scope_authorized') is not True or cp.get('status_scope_authorized') is not False
            or cp.get('seed')!=receipt or cp.get('authority')!=qualify_authority(state)):
        raise ValueError('exact admitted QUERY seed required')
    return True


def select(config,state,task):
    cp=state['c10_checkpoints'];seed_binding(state,cp['seed'])
    note=author_note(state)
    proof=cp.get('qualification',{});expected_scope=hashlib.sha256(('QUERY:'+cp['authority']['certificate']['task_id']+':'+cp['seed']['validation']['test_sha256']).encode()).hexdigest()
    if (state.get('stage')!='awaiting_author' or task.get('agent_id')!=config['author']
            or task.get('issue_id')!=state['issue_id'] or task.get('wakeup_id')!=state.get('wakeup_id')
            or not (task.get('id') or task.get('task_id')) or note not in (task.get('handoff_note') or '')
            or hashlib.sha256(note.encode()).hexdigest()!=cp.get('note_sha256')
            or cp.get('qualification')!=state['staged']['driver_guard']['qualification']
            or cp.get('admission_code_sha256')!=gates.sha(Path(__file__).read_bytes())
            or cp.get('scope_id')!=expected_scope or cp.get('worker_image')!=proof.get('worker_image')
            or not re.fullmatch(r'sha256:[a-f0-9]{64}',cp.get('worker_image',''))
            or proof.get('status')!='passed' or proof.get('schema')!='surgical-driver-registry-probe-v3'
            or proof.get('network')!='none' or proof.get('uid')!=10000 or proof.get('delivery_approval') is not False
            or any(proof.get(k) is not True for k in syntax.FLAGS)):
        raise ValueError('exact new QUERY author wakeup and persisted contract required')
    return {'worker_image':cp['worker_image'],'surgical':{'path':'/workspace/tests/test_incremental_u3.py',
        'expected_sha256':cp['seed']['validation']['test_sha256'],'protocol':'typed_driver_lines_v4'}}


def idle(b,con,fx,settings,state,minimum):
    if (con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
            or fx.remaining_calls()<minimum or any(t.get('status') in ('queued','dispatched','running')
            for t in native.issue_task_runs(settings,state['issue_id']))):
        raise ValueError('idle native/worker scope and budget reserve required')


def inspect_seed(b,state):
    """Fixed readonly source evidence, not a repair or product test run."""
    seed=state['c10_decomposition']['current_seed'];volume=seed['snapshot']['volume']
    labels=b.docker('GET','/volumes/'+volume)['Labels']
    if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=seed['task_id']:
        raise ValueError('owned unchanged QUERY snapshot required')
    image=b.docker('GET','/containers/'+b.PREFIX+'-execution-broker-1/json')['Image']
    name=b.PREFIX+'-query-admission-probe-'+uuid.uuid4().hex[:12]
    labels={'delivery-kit.owner':b.OWNER,'com.docker.compose.project':b.PREFIX,'com.docker.compose.service':'query-admission-probe'}
    code=('from pathlib import Path;import json,c10_checkpoint_contract as g;'
        'root=Path("/seed");raw,files=g.snapshots.manifest(root);'
        'source=g.snapshots.product.regular_within(root,g.snapshots.TEST);'
        'app=g.snapshots.product.regular_within(root,"app/static/app.js");'
        'candidate=g.query_candidate(source);g.verify_bytes("QUERY",source,candidate);'
        'print(json.dumps({"test_sha256":g.sha(source),"manifest_sha256":g.sha(raw),'
        '"prospective_query_sha256":g.sha(candidate),"app_consumes_items":b"renderItems(data.items || [])" in app,'
        '"contract_sha256":g.sha(Path(g.__file__).read_bytes()),"writes_applied":False}))')
    try:
        b.docker('POST','/containers/create?name='+name,dict(Image=image,User='10000:10000',Entrypoint=['python'],Cmd=['-c',code],
            Env=['PYTHONPATH=/','PYTHONDONTWRITEBYTECODE=1'],NetworkDisabled=True,Labels=labels,
            HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
                Memory=134217728,PidsLimit=32,Mounts=[dict(Type='volume',Source=volume,Target='/seed',ReadOnly=True)])))
        b.docker('POST','/containers/'+name+'/start');deadline=time.time()+20
        while time.time()<deadline:
            info=b.docker('GET','/containers/'+name+'/json')
            if not info['State']['Running']:
                if info['State']['ExitCode']!=0:raise ValueError('fixed QUERY source probe failed')
                proof=json.loads(b.docker_stdout(name,limit=4096));break
            time.sleep(.2)
        else:raise TimeoutError('QUERY probe deadline')
    finally:
        info=b.docker('GET','/containers/'+name+'/json')
        if info and info['Config'].get('Labels')==labels:b.docker('DELETE','/containers/'+info['Id']+'?force=true')
    if (proof.get('test_sha256')!=seed['validation']['test_sha256']
            or proof.get('manifest_sha256')!=seed['validation']['manifest_sha256']
            or proof.get('app_consumes_items') is not True or proof.get('writes_applied') is not False
            or proof.get('contract_sha256')!=gates.sha(Path(gates.__file__).read_bytes())):
        raise ValueError('actual frozen QUERY facts required')
    return proof


def register_intake(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('c10_query_intake'):return {'stage':state['stage'],'reused':True,'author_authorized':False}
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        idle(b,con,fx,settings,state,56)
        revised=prepare_intake(state);proof=inspect_seed(b,state)
        revised['c10_query_intake']['seed_probe']=proof
        revised['c10_decomposition']['checkpoint_contract_available']['phase_author_capability_installed']=True
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'author_authorized':False,'status_authorized':False}


def arm(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('c10_checkpoints'):return {'stage':state['stage'],'reused':True,'delivery_approval':False}
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        idle(b,con,fx,settings,state,48)
        try:import harness_repair_task as h
        except ImportError:from broker import harness_repair_task as h
        report=state['functional_diagnosis_receipt'];task=native.task_record(settings,report['certificate']['task_id'],config['cto'])
        decision=fx.decision(task);cert=h.qualify_diagnosis(config,state,task,decision,fx.read_evidence(task))
        if delivery.qualify_functional_decision(state,decision,cert)!=report:raise ValueError('actual new CTO evidence required')
        if inspect_seed(b,state)!=state['c10_query_intake']['seed_probe']:raise ValueError('source facts changed after CTO intake')
        revised=prepare_authorization(config,state,fx.remaining_calls())
        if b.docker('GET','/images/'+revised['c10_checkpoints']['worker_image']+'/json')['Id']!=revised['c10_checkpoints']['worker_image']:
            raise ValueError('qualified QUERY worker image missing')
        trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(state['issue_id'],)).fetchone()[0])
        if trial.get('harness_maintenance_only') is not True:raise ValueError('isolated maintenance-only route required')
        trial['maintenance_seed']={'source':source,'receipt':revised['c10_checkpoints']['seed']}
        con.execute('UPDATE test_revision_trials SET config=? WHERE issue_id=?',(json.dumps(trial,sort_keys=True),state['issue_id']))
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'phase':'QUERY','attempt_limit':1,'status_authorized':False,'delivery_approval':False}


def prepare_suite_recovery(state,stored):
    """Only revalidate a frozen output rejected before any functional suite ran."""
    if (state.get('c10_query_validation_recovery') or state.get('stage')!='blocked'
            or state.get('category')!='c10_checkpoint_validation_failed'
            or stored.get('task_id')!=state['author_task'] or stored.get('status')!='failed'
            or stored.get('manifest_sha256')!=state['validation']['manifest_sha256']
            or json.loads(stored['receipt']).get('failure') is not None):
        raise ValueError('exact unconsumed structural-only QUERY rejection required')
    gates.phase_state(state,'QUERY')
    seed=state['c10_checkpoints']['seed']
    seed_binding(dict(state,snapshot=seed['snapshot'],validation=seed['validation']),seed)
    if any(state['validation'].get(k) is not True for k in ('source_changed','node_syntax_valid',
            'python_syntax_valid','non_driver_ast_preserved','test_methods_preserved')):
        raise ValueError('preserved valid frozen QUERY output required')
    revised=copy.deepcopy(state)
    revised['c10_query_validation_recovery']={'prior_run':stored,'prior_category':state['category'],
        'snapshot':state['snapshot'],'validation':state['validation'],
        'scope_receipt':state['c10_checkpoints']['scope_receipt'],'attempt_limit':1,
        'reason':'fixed_comparison_of_whitespace_inside_inserted_items_envelopes',
        'retry_authorized':False,'delivery_approval':False,'at':time.time()}
    revised.update(stage='maintenance_suite_pending',category='c10_query_frozen_validation_recovery',delivery_approval=False)
    return revised


def resume_suite(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('c10_query_validation_recovery'):return {'stage':state['stage'],'reused':True,'author_restarted':False}
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        idle(b,con,fx,settings,state,0)
        task=native.task_record(settings,state['author_task'],config['author'])
        if task.get('status')!='completed' or task.get('wakeup_id')!=state['wakeup_id'] or task.get('issue_id')!=state['issue_id']:
            raise ValueError('exact completed QUERY author required')
        seed=state['c10_checkpoints']['seed'];diagnosed=dict(state,snapshot=seed['snapshot'],validation=seed['validation'])
        report=state['c10_checkpoints']['authority'];cto=native.task_record(settings,report['certificate']['task_id'],config['cto'])
        try:import harness_repair_task as h
        except ImportError:from broker import harness_repair_task as h
        decision=fx.decision(cto);cert=h.qualify_diagnosis(config,diagnosed,cto,decision,fx.read_evidence(cto))
        if delivery.qualify_functional_decision(diagnosed,decision,cert)!=report:raise ValueError('original QUERY CTO authority drift')
        stored=con.execute('SELECT * FROM maintenance_suite_runs WHERE task_id=?',(state['author_task'],)).fetchone()
        if not stored:raise ValueError('durable original failed validation required')
        delivery.validate_maintenance(b,config,state,execute_suite=False)
        revised=prepare_suite_recovery(state,dict(stored))
        con.execute('DELETE FROM maintenance_suite_runs WHERE task_id=?',(state['author_task'],))
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'author_restarted':False,'model_calls_required':0,'delivery_approval':False}


def accept_stored_partial(b,source):
    """Qualify an existing actual log; never rerun tests or convert failure to Green."""
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('c10_query_partial_reclassification'):return {'stage':state['stage'],'reused':True,'suite_reexecuted':False}
        if state.get('stage')!='blocked' or state.get('category')!='c10_checkpoint_acceptance_failed' or not state.get('c10_query_validation_recovery'):
            raise ValueError('exact actual QUERY acceptance block required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        idle(b,con,fx,settings,state,0)
        stored=con.execute('SELECT * FROM maintenance_suite_runs WHERE task_id=?',(state['author_task'],)).fetchone()
        if not stored or stored['status']!='failed' or stored['manifest_sha256']!=state['validation']['manifest_sha256']:
            raise ValueError('durable exact failed QUERY suite required')
        failure=state['suite_failure']
        if json.loads(stored['receipt']).get('failure')!=failure:raise ValueError('actual suite receipt drift')
        output=con.execute('SELECT output FROM frozen_suite_failures WHERE task_id=? AND output_sha256=?',
            (state['author_task'],failure['output_sha256'])).fetchone()
        if not output:raise ValueError('actual full-suite log required')
        delivery.validate_maintenance(b,config,state,execute_suite=False)
        partial=gates.partial_receipt(state,failure,output[0])
        state['c10_query_partial_reclassification']={'prior_run':dict(stored),'prior_category':state['category'],
            'output_sha256':failure['output_sha256'],'reason':'accept_exact_runner_diagnostic_read_files_metadata',
            'suite_reexecuted':False,'author_restarted':False,'delivery_approval':False,'at':time.time()}
        state['c10_checkpoints']['query_receipt']=partial
        state.update(stage='blocked',category='c10_query_partial_requires_status_admission',owner=config['cto'],delivery_approval=False)
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
    return {'stage':state['stage'],'category':state['category'],'result':'PARTIAL','suite_reexecuted':False,
        'author_restarted':False,'status_authorized':False,'delivery_approval':False}
