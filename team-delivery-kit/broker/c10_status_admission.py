"""Distinct once-only STATUS authority on an actually executed QUERY partial."""
import copy
import hashlib
import json
from pathlib import Path
import re
import time
import uuid
try:
    import c10_checkpoint_contract as gates,c10_query_admission as query,c10_syntax_recovery as syntax
    import maintenance_delivery as delivery,native,handoff_runtime,admission_controls_spike
except ImportError:
    from broker import c10_checkpoint_contract as gates,c10_query_admission as query,c10_syntax_recovery as syntax
    from broker import maintenance_delivery as delivery,native,handoff_runtime,admission_controls_spike


def verified_partial(state,output):
    cp=gates.phase_state(state,'QUERY');partial=cp.get('query_receipt',{})
    actual=gates.partial_receipt(state,partial['full_suite_failure'],output)
    if actual!=partial:raise ValueError('exact durable actual QUERY partial required')
    return partial


def prepare_intake(state,output):
    if (state.get('c10_status_intake') or state.get('stage')!='blocked'
            or state.get('category')!='c10_query_partial_requires_status_admission'):
        raise ValueError('unconsumed QUERY partial required for STATUS intake')
    partial=verified_partial(state,output);revised=copy.deepcopy(state)
    seed={'task_id':state['author_task'],'snapshot':state['snapshot'],'validation':state['validation'],'checkpoint':2}
    revised['c10_status_intake']={'seed':seed,'query_receipt':partial,'prior_query':state['c10_checkpoints'],
        'prior_diagnosis':state['functional_diagnosis'],'prior_receipt':revised.pop('functional_diagnosis_receipt'),
        'attempt_limit':1,'author_scope_authorized':False,'delivery_approval':False,'at':time.time()}
    note=('CTO READONLY DISTINCT STATUS GATE. Read all four files completely. '
        'QUERY is now an ACTUAL PARTIAL: full259 ran, C09 passed, only C10 '
        'KeyError status_genA_urls. QUERY fixture envelopes are frozen and cannot be '
        'repaired again. Decide from current source how to replace ONLY '
        'tests/test_incremental_u3.py lines534-536 (C10STATUS placeholder). '
        'Preserve existing outer closure line537 and all bytes outside this window. '
        'Exercise real filter-open then filter-completed events, observe deferred '
        'issued URLs into status_genA_urls/status_genB_urls, resolve CURRENT COMPLETED '
        'then STALE OPEN with valid items envelopes and flush after resolutions. '
        'Populate rendered_after_current_status/rendered_after_stale_status from '
        'actual DOM and final pending_left=pending.length after draining requests. '
        'deferred is the hold-mode marker, NOT the pending request queue. '
        'Do not fabricate constants, query reports, Red, assertions or test results. '
        'Inspect pending request/event APIs and confirm this fits the existing closure. '
        'Full259 Green then independent review are required; no approval now. '
        'If supported action=request_test_revision, optional_files=[], reason starts '
        'exactly DRIVER_OBSERVATION: and gives the concrete STATUS plan, TEST path, '
        '534-536, filter-open/filter-completed, status_genA_urls/status_genB_urls, '
        'items, pending_left=pending.length, QUERY frozen,259 and independent review. Maximum900chars. '
        'Otherwise escalate_cto with UNRESOLVED: and concrete contradiction. '
        'No writes, terminal, model/cap change or CEO technical question.\n'
        'DELIVERY_CURRENT_HARNESS_DIAGNOSIS_V1\nDELIVERY_STRUCTURED_DECISION_V1:technical\n'
        'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\n'
        'DELIVERY_DETERMINISTIC_READ_V1\n'+
        ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in delivery.paths()))
    revised['functional_diagnosis']=dict(author_task=seed['task_id'],snapshot=seed['snapshot'],
        validation=seed['validation'],failure=partial['full_suite_failure'],
        failure_origin='actual_query_partial_full_suite',attempt_limit=1,note=note,at=time.time())
    revised.update(stage='maintenance_functional_diagnosis_dispatch',category='c10_distinct_status_intake',delivery_approval=False)
    return revised


def qualify_authority(state):
    intake=state['c10_status_intake'];seed=intake['seed'];report=state['functional_diagnosis_receipt']
    cert=report['certificate'];decision=report['decision'];reason=decision.get('reason','')
    terms=('STATUS','tests/test_incremental_u3.py','534-536','filter-open','filter-completed',
        'status_genA_urls','status_genB_urls','items','pending_left','pending.length','QUERY','259')
    partial=intake['query_receipt']
    if (intake.get('attempt_limit')!=1 or report.get('classification')!='DRIVER_OBSERVATION'
            or decision.get('action')!='request_test_revision' or decision.get('optional_files')!=[]
            or not isinstance(reason,str) or not reason.startswith('DRIVER_OBSERVATION: ')
            or any(t not in reason for t in terms) or not 1<=len(reason)<=1200
            or not re.search(r'QUERY.{0,30}(?:frozen|unchanged|untouched)',reason,re.I)
            or not re.search(r'independent.{0,20}review',reason,re.I)
            or cert.get('task_id')==intake['prior_query']['authority']['certificate']['task_id']
            or not cert.get('task_id') or cert.get('snapshot')!=seed['snapshot']['volume']
            or cert.get('test_sha256')!=seed['validation']['test_sha256']
            or cert.get('decision_sha256')!=gates.sha(json.dumps(decision,sort_keys=True).encode())
            or seed['snapshot']!=state['snapshot'] or seed['validation']!=state['validation']
            or partial.get('result')!='PARTIAL' or partial.get('green') is not False
            or partial.get('delivery_approval') is not False or partial.get('author_scope_authorized') is not False
            or partial.get('source_task')!=seed['task_id'] or partial.get('snapshot')!=seed['snapshot']
            or partial.get('validation')!=seed['validation']):
        raise ValueError('distinct exact STATUS CTO authority and actual QUERY lineage required')
    return report


def author_note(state):
    cp=state['c10_checkpoints'];digest=cp['seed']['validation']['test_sha256']
    if cp.get('micro_contract'):
        try:import c10_micro_recovery as recovery
        except ImportError:from broker import c10_micro_recovery as recovery
        return recovery.note(state)
    if cp.get('atomic_contract'):
        return ('ATOMIC COMPLETE STATUS EXPERIMENT. Scope '+cp['scope_id']+'. Read the '
            'ENTIRE /workspace/tests/test_incremental_u3.py. Submit ONE edits element '
            'start_line=534,end_line=536,new=<MULTILINE FULL EXPERIMENT> using '
            'expected_sha256='+digest+'. These three ORIGINAL lines are a replacement '
            'WINDOW, not a limit of three new lines. Write the WHOLE plan in new, '
            'including both real clicks, both calls.slice(...).map(...) URL reports, '
            'two STATUS items resolutions, flush callbacks with both renderedTitles() '
            'reports and out.pending_left=pending.length. '+
            ('AFTER the stale-status DOM observation, execute the verified event-plan '
             'drain of /feedback?q=gamma using its named real resolver with {items:[]}, '
             'then flush, then measure final pending.length. Never change prior DOM '
             'reports or clear the queue. ' if cp.get('event_plan_contract') else '')+
            'Preserve outer line537. '
            'Three one-line starters or missing observations are rejected BEFORE '
            'writing. Correct incomplete proposals using that feedback, never repeat '
            'identical proposals. Qualified CTO plan: '+cp['authority']['decision']['reason']+
            ' QUERY/C09/product/preamble/assertions/all other bytes stay frozen. '
            'Final<=32768bytes. No terminal, generic writes, Red or approvals. '
            'Stop only after the complete atomic edit succeeds; controller requires '
            'all259 Green and independent review. No delivery claim.\n'
            'DELIVERY_DRIVER_CHECKPOINT_V3\n')
    return ('ISOLATED STATUS-ONLY HARNESS CHECKPOINT. Scope '+cp['scope_id']+'. '
        'Read /workspace/tests/test_incremental_u3.py completely. Use ONE '
        'surgical_test_edit typed V4 FILE line range534-536 with expected_sha256='+digest+'. '
        'Replace only C10STATUS placeholder. Existing outer closure line537 and every '
        'other byte are frozen, including QUERY/C09/product/assertions/preamble. '
        'Execute the qualified CTO plan: '+cp['authority']['decision']['reason']+' '
        'Measure actual DOM rendered_after_current_status/rendered_after_stale_status; '
        'final pending_left must measure pending.length after draining real issued '
        'requests, not fabricated values. Concise code: seed30158bytes, final<=32768. '
        'One author attempt, no replay of consumed scopes, generic writes, shell, Red, '
        'approvals or tool-approval requests. Stop after successful edit. Controller '
        'freezes output and runs all259 tests; only all Green followed by independent '
        'review can accept maintenance. No delivery or homologation claim.\n'
        'DELIVERY_DRIVER_CHECKPOINT_V3\n')


def prepare_authorization(config,state,remaining):
    if (state.get('c10_checkpoints',{}).get('phase')!='QUERY' or state.get('stage')!='blocked'
            or state.get('category')!='maintenance_diagnosis_driver_observation'
            or config['author']==config['cto'] or remaining<48):
        raise ValueError('distinct idle STATUS admission and48-call reserve required')
    authority=qualify_authority(state);intake=state['c10_status_intake'];guard=state['staged']['driver_guard'];proof=guard['qualification']
    if (state['staged'].get('current')!=2 or intake['prior_query']!=state['c10_checkpoints']
            or proof.get('worker_image')!=guard.get('worker_image') or proof.get('status')!='passed'
            or proof.get('schema')!='surgical-driver-registry-probe-v3' or proof.get('uid')!=10000
            or proof.get('network')!='none' or proof.get('delivery_approval') is not False
            or not re.fullmatch(r'sha256:[a-f0-9]{64}',guard.get('worker_image',''))
            or any(proof.get(k) is not True for k in syntax.FLAGS)):
        raise ValueError('frozen QUERY seed and qualified worker required')
    revised=copy.deepcopy(state)
    cp={'schema':gates.SCHEMA,'phase':'STATUS','seed':intake['seed'],'authority':authority,
        'prior_query':intake['prior_query'],'query_receipt':intake['query_receipt'],
        'scope_id':gates.sha(('STATUS:'+authority['certificate']['task_id']+':'+intake['seed']['validation']['test_sha256']).encode()),
        'qualification':proof,'worker_image':guard['worker_image'],'attempt_limit':1,
        'admission_code_sha256':gates.sha(Path(__file__).read_bytes()),'author_scope_authorized':True,
        'status_scope_authorized':True,'delivery_approval':False,'at':time.time()}
    revised['c10_checkpoints']=cp;cp['note_sha256']=gates.sha(author_note(revised).encode())
    revised['c10_status_intake']['author_scope_authorized']=True
    revised.update(stage='checkpoint_dispatch_intent',category='c10_status_phase_authorized',delivery_approval=False)
    return revised


def seed_binding(state,receipt):
    cp=state.get('c10_checkpoints',{})
    if cp.get('micro_contract'):
        try:import c10_micro_recovery as recovery
        except ImportError:from broker import c10_micro_recovery as recovery
        return recovery.binding(state,receipt)
    if cp.get('event_plan_contract'):
        try:import c10_event_author as events
        except ImportError:from broker import c10_event_author as events
        return events.binding(state,receipt)
    if (cp.get('schema')!=gates.SCHEMA or cp.get('phase')!='STATUS' or cp.get('attempt_limit')!=1
            or cp.get('author_scope_authorized') is not True or cp.get('status_scope_authorized') is not True
            or cp.get('seed')!=receipt or cp.get('authority')!=qualify_authority(state)
            or cp.get('query_receipt')!=state['c10_status_intake']['query_receipt']
            or cp.get('prior_query')!=state['c10_status_intake']['prior_query']
            or cp.get('admission_code_sha256')!=gates.sha(Path(__file__).read_bytes())):
        raise ValueError('exact admitted STATUS seed required')
    return True


def scope_id(cp):
    if cp.get('event_plan_contract'):
        try:import c10_event_author as events
        except ImportError:from broker import c10_event_author as events
        return events.scope(cp)
    if cp.get('atomic_contract'):
        if cp['atomic_contract']!='c10-status-observations-v1' or not cp.get('failed_task'):
            raise ValueError('exact changed atomic recovery contract required')
        return gates.sha(('STATUS-ATOMIC:'+cp['failed_task']+':'+cp['authority']['certificate']['decision_sha256']+
            ':'+cp['seed']['validation']['test_sha256']+':'+cp['admission_code_sha256']).encode())
    return gates.sha(('STATUS:'+cp['authority']['certificate']['task_id']+':'+cp['seed']['validation']['test_sha256']).encode())


def select(config,state,task):
    cp=state['c10_checkpoints']
    if cp.get('micro_contract'):
        try:import c10_micro_recovery as recovery
        except ImportError:from broker import c10_micro_recovery as recovery
        return recovery.select(config,state,task)
    seed_binding(state,cp['seed']);note=author_note(state);proof=cp['qualification']
    expected=scope_id(cp)
    if (state.get('stage')!='awaiting_author' or task.get('agent_id')!=config['author']
            or task.get('issue_id')!=state['issue_id'] or task.get('wakeup_id')!=state.get('wakeup_id')
            or not (task.get('id') or task.get('task_id')) or note not in (task.get('handoff_note') or '')
            or gates.sha(note.encode())!=cp.get('note_sha256') or cp.get('scope_id')!=expected
            or proof!=state['staged']['driver_guard']['qualification'] or cp.get('worker_image')!=proof.get('worker_image')
            or proof.get('status')!='passed' or proof.get('network')!='none' or proof.get('uid')!=10000
            or any(proof.get(k) is not True for k in syntax.FLAGS)):
        raise ValueError('exact STATUS author wakeup required')
    surgical={'path':'/workspace/tests/test_incremental_u3.py',
        'expected_sha256':cp['seed']['validation']['test_sha256'],'protocol':'typed_driver_lines_v4'}
    if cp.get('atomic_contract'):
        saved='c10_event_author' if cp.get('event_plan_contract') else 'c10_status_atomic_recovery'
        if cp!=state.get(saved,{}).get('checkpoint'):
            raise ValueError('exact persistent atomic recovery required')
        atomic=proof.get('atomic_status',{})
        if (atomic.get('schema')!='surgical-status-atomic-probe-v1' or atomic.get('status')!='passed'
                or atomic.get('uid')!=10000 or atomic.get('network')!='none' or atomic.get('model_calls')!=0
                or atomic.get('delivery_approval') is not False
                or any(atomic.get(k) is not True for k in ATOMIC_FLAGS)):
            raise ValueError('actual atomic worker qualification required')
        surgical['atomic_contract']=cp['atomic_contract']
    return {'worker_image':cp['worker_image'],'surgical':surgical}


ATOMIC_FLAGS=('partial_before_write_denied','incomplete_observations_denied','direct_handler_fenced',
    'fresh_process_before_write_denied','whole_multiline_accepted','narrow_schema',
    'outside_window_preserved','stale_edit_denied','credentials_absent')


def prepare_atomic_recovery(config,state,proof,remaining):
    if (state.get('c10_status_atomic_recovery') or state.get('stage')!='blocked'
            or state.get('category')!='c10_checkpoint_acceptance_failed'
            or state.get('c10_checkpoints',{}).get('phase')!='STATUS' or remaining<48
            or config['author']==config['cto']):
        raise ValueError('one distinct failed STATUS recovery with48-call reserve required')
    old=state['c10_checkpoints'];gates.phase_state(state,'STATUS');atomic=proof.get('atomic_status',{})
    if (old.get('atomic_contract') or proof.get('status')!='passed' or proof.get('schema')!='surgical-driver-registry-probe-v3'
            or proof.get('network')!='none' or proof.get('uid')!=10000 or proof.get('delivery_approval') is not False
            or not re.fullmatch(r'sha256:[a-f0-9]{64}',proof.get('worker_image',''))
            or any(proof.get(k) is not True for k in syntax.FLAGS)
            or atomic.get('status')!='passed' or atomic.get('schema')!='surgical-status-atomic-probe-v1'
            or atomic.get('uid')!=10000 or atomic.get('network')!='none' or atomic.get('model_calls')!=0
            or atomic.get('delivery_approval') is not False or any(atomic.get(k) is not True for k in ATOMIC_FLAGS)):
        raise ValueError('actual new atomic worker qualification required')
    revised=copy.deepcopy(state);seed=old['seed']
    revised.update(snapshot=seed['snapshot'],validation=seed['validation'],author_task=seed['task_id'])
    qualify_authority(revised)  # Same independent technical plan, exact original QUERY seed.
    cp=copy.deepcopy(old)
    for key in ('scope_receipt','final_receipt'):cp.pop(key,None)
    cp.update(qualification=proof,worker_image=proof['worker_image'],failed_task=state['author_task'],
        atomic_contract='c10-status-observations-v1',admission_code_sha256=gates.sha(Path(__file__).read_bytes()),at=time.time())
    cp['scope_id']=scope_id(cp);revised['c10_checkpoints']=cp
    revised['staged']['driver_guard']=dict(revised['staged']['driver_guard'],qualification=proof,worker_image=proof['worker_image'])
    cp['note_sha256']=gates.sha(author_note(revised).encode())
    revised['c10_status_atomic_recovery']={'prior_checkpoint':old,'failed_task':state['author_task'],
        'failed_snapshot':state['snapshot'],'failed_validation':state['validation'],'failed_suite':state['suite_failure'],
        'prior_stage':state['stage'],'prior_category':state['category'],'checkpoint':copy.deepcopy(cp),
        'attempt_limit':1,'identical_retry_authorized':False,'delivery_approval':False,'at':time.time()}
    revised.update(stage='checkpoint_dispatch_intent',category='c10_status_atomic_changed_contract',delivery_approval=False)
    return revised


def inspect_seed(b,state):
    seed=state['c10_status_intake']['seed'];volume=seed['snapshot']['volume']
    labels=b.docker('GET','/volumes/'+volume)['Labels']
    if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=seed['task_id']:
        raise ValueError('owned actual QUERY snapshot required')
    image=b.docker('GET','/containers/'+b.PREFIX+'-execution-broker-1/json')['Image']
    name=b.PREFIX+'-status-admission-probe-'+uuid.uuid4().hex[:12]
    labels={'delivery-kit.owner':b.OWNER,'com.docker.compose.project':b.PREFIX,'com.docker.compose.service':'status-admission-probe'}
    code=('from pathlib import Path;import json,c10_checkpoint_contract as g;'
        'root=Path("/seed");raw,files=g.snapshots.manifest(root);'
        'source=g.snapshots.product.regular_within(root,g.snapshots.TEST);lines=source.splitlines(keepends=True);'
        'candidate=b"".join(lines[:533]+[b"// readonly scope probe\\n"]+lines[536:]);'
        'g.verify_bytes("STATUS",source,candidate);'
        'print(json.dumps({"test_sha256":g.sha(source),"manifest_sha256":g.sha(raw),'
        '"bytes":len(source),"contract_sha256":g.sha(Path(g.__file__).read_bytes()),"writes_applied":False}))')
    try:
        b.docker('POST','/containers/create?name='+name,dict(Image=image,User='10000:10000',Entrypoint=['python'],Cmd=['-c',code],
            Env=['PYTHONPATH=/','PYTHONDONTWRITEBYTECODE=1'],NetworkDisabled=True,Labels=labels,
            HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
                Memory=134217728,PidsLimit=32,Mounts=[dict(Type='volume',Source=volume,Target='/seed',ReadOnly=True)])))
        b.docker('POST','/containers/'+name+'/start');deadline=time.time()+20
        while time.time()<deadline:
            info=b.docker('GET','/containers/'+name+'/json')
            if not info['State']['Running']:
                if info['State']['ExitCode']!=0:raise ValueError('fixed STATUS source probe failed')
                proof=json.loads(b.docker_stdout(name,limit=4096));break
            time.sleep(.2)
        else:raise TimeoutError('STATUS probe deadline')
    finally:
        info=b.docker('GET','/containers/'+name+'/json')
        if info and info['Config'].get('Labels')==labels:b.docker('DELETE','/containers/'+info['Id']+'?force=true')
    if (proof.get('test_sha256')!=seed['validation']['test_sha256']
            or proof.get('manifest_sha256')!=seed['validation']['manifest_sha256']
            or proof.get('writes_applied') is not False or proof.get('bytes')!=seed['validation']['bytes']
            or proof.get('contract_sha256')!=gates.sha(Path(gates.__file__).read_bytes())):
        raise ValueError('actual frozen STATUS seed required')
    return proof


def register_intake(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('c10_status_intake'):return {'stage':state['stage'],'reused':True,'author_authorized':False}
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        query.idle(b,con,fx,settings,state,56)
        partial=state['c10_checkpoints']['query_receipt'];failure=partial['full_suite_failure']
        row=con.execute('SELECT output FROM frozen_suite_failures WHERE task_id=? AND output_sha256=?',
            (state['author_task'],failure['output_sha256'])).fetchone()
        if not row:raise ValueError('durable QUERY failure log missing')
        revised=prepare_intake(state,row[0]);revised['c10_status_intake']['seed_probe']=inspect_seed(b,revised)
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'author_authorized':False,'status_authorized':False}


def arm(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('c10_checkpoints',{}).get('phase')=='STATUS':return {'stage':state['stage'],'reused':True,'delivery_approval':False}
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        query.idle(b,con,fx,settings,state,48)
        try:import harness_repair_task as h
        except ImportError:from broker import harness_repair_task as h
        report=state['functional_diagnosis_receipt'];task=native.task_record(settings,report['certificate']['task_id'],config['cto'])
        decision=fx.decision(task);cert=h.qualify_diagnosis(config,state,task,decision,fx.read_evidence(task))
        if delivery.qualify_functional_decision(state,decision,cert)!=report:raise ValueError('actual distinct CTO evidence required')
        if inspect_seed(b,state)!=state['c10_status_intake']['seed_probe']:raise ValueError('source facts changed after STATUS intake')
        partial=state['c10_checkpoints']['query_receipt'];failure=partial['full_suite_failure']
        row=con.execute('SELECT output FROM frozen_suite_failures WHERE task_id=? AND output_sha256=?',
            (state['author_task'],failure['output_sha256'])).fetchone()
        if not row or verified_partial(state,row[0])!=state['c10_status_intake']['query_receipt']:
            raise ValueError('actual QUERY partial lineage drift')
        revised=prepare_authorization(config,state,fx.remaining_calls())
        if b.docker('GET','/images/'+revised['c10_checkpoints']['worker_image']+'/json')['Id']!=revised['c10_checkpoints']['worker_image']:
            raise ValueError('qualified STATUS worker image missing')
        trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(state['issue_id'],)).fetchone()[0])
        if trial.get('harness_maintenance_only') is not True:raise ValueError('isolated maintenance-only route required')
        trial['maintenance_seed']={'source':source,'receipt':revised['c10_checkpoints']['seed']}
        con.execute('UPDATE test_revision_trials SET config=? WHERE issue_id=?',(json.dumps(trial,sort_keys=True),state['issue_id']))
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'phase':'STATUS','attempt_limit':1,'delivery_approval':False}


def worker_probe(b,image,script):
    if script not in ('/line_probe.py','/status_probe.py','/micro_probe.py'):raise ValueError('fixed qualification operation required')
    if b.docker('GET','/images/'+image+'/json')['Id']!=image:raise ValueError('immutable qualified image required')
    name=b.PREFIX+'-status-worker-probe-'+uuid.uuid4().hex[:12]
    labels={'delivery-kit.owner':b.OWNER,'com.docker.compose.project':b.PREFIX,'com.docker.compose.service':'status-worker-probe'}
    try:
        b.docker('POST','/containers/create?name='+name,dict(Image=image,User='0:0',Entrypoint=['python'],Cmd=[script],
            Env=['PYTHONPATH=/','PYTHONDONTWRITEBYTECODE=1'],NetworkDisabled=True,Labels=labels,
            HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],CapAdd=['SETUID','SETGID'],SecurityOpt=['no-new-privileges'],
                Memory=536870912,PidsLimit=64,Tmpfs={'/workspace':'rw,size=16m,mode=1777','/tmp':'rw,size=64m,mode=1777'})))
        b.docker('POST','/containers/'+name+'/start');deadline=time.time()+45
        while time.time()<deadline:
            info=b.docker('GET','/containers/'+name+'/json')
            if not info['State']['Running']:
                if info['State']['ExitCode']!=0:raise ValueError('fixed actual worker qualification failed')
                output=b.docker_stdout(name,limit=8192);proof=json.loads(output.strip().splitlines()[-1]);break
            time.sleep(.2)
        else:raise TimeoutError('worker qualification deadline')
    finally:
        info=b.docker('GET','/containers/'+name+'/json')
        if info and info['Config'].get('Labels')==labels:b.docker('DELETE','/containers/'+info['Id']+'?force=true')
    return proof


def arm_atomic_recovery(b,source,image):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('c10_status_atomic_recovery'):return {'stage':state['stage'],'reused':True,'delivery_approval':False}
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        query.idle(b,con,fx,settings,state,48)
        if state.get('stage')!='blocked' or state.get('category')!='c10_checkpoint_acceptance_failed':
            raise ValueError('actual failed STATUS required')
        task=native.task_record(settings,state['author_task'],config['author'])
        if task.get('status')!='completed' or task.get('wakeup_id')!=state['wakeup_id'] or task.get('issue_id')!=state['issue_id']:
            raise ValueError('exact consumed native STATUS execution required')
        messages=native.task_messages(settings,task['id'])
        uses=[m for m in messages if m.get('type')=='tool_use' and m.get('tool')=='surgical_test_edit']
        if len(uses)!=1:raise ValueError('one actual partial STATUS edit required')
        args=uses[0].get('input',{});seed=state['c10_checkpoints']['seed']
        expected=[{'start_line':534,'end_line':534,'new':"                          click(byId['filter-open']);"},
            {'start_line':535,'end_line':535,'new':'                          const genAIdx = calls.length - 1;'},
            {'start_line':536,'end_line':536,'new':"                          click(byId['filter-completed']);"}]
        if (args.get('path')!='/workspace/tests/test_incremental_u3.py' or args.get('expected_sha256')!=seed['validation']['test_sha256']
                or args.get('edits')!=expected):raise ValueError('actual three incomplete starters required')
        results=[m for m in messages if m.get('type')=='tool_result' and m.get('call_id')==uses[0].get('call_id')]
        if len(results)!=1 or results[0].get('output_truncated') is not False or 'verified:** True' not in results[0].get('output',''):
            raise ValueError('complete successful partial edit receipt required')
        failure=state['suite_failure'];row=con.execute('SELECT output FROM frozen_suite_failures WHERE task_id=? AND output_sha256=?',
            (state['author_task'],failure['output_sha256'])).fetchone()
        try:import suite_failure as sf,harness_repair_task as h
        except ImportError:from broker import suite_failure as sf,harness_repair_task as h
        core=dict(failure);diagnostics=core.pop('diagnostic_read_files',None)
        if (not row or diagnostics!=['app/static/app.js','app/static/index.html','tests/test_incremental_u3.py']
                or core!=sf.evidence(1,row[0],state['author_task'],state['snapshot']['volume'])
                or core['tests_executed']!=259 or len(core['failures'])!=1 or core['failures'][0]['test']!=gates.C10
                or re.findall(r"(?m)^KeyError: '([^']+)'$",row[0])!=['status_genA_urls']):
            raise ValueError('actual full259 incomplete STATUS failure required')
        shadow=dict(state,snapshot=seed['snapshot'],validation=seed['validation'],author_task=seed['task_id'])
        report=state['c10_checkpoints']['authority'];cto=native.task_record(settings,report['certificate']['task_id'],config['cto'])
        decision=fx.decision(cto);cert=h.qualify_diagnosis(config,shadow,cto,decision,fx.read_evidence(cto))
        if delivery.qualify_functional_decision(shadow,decision,cert)!=report:raise ValueError('same exact technical authority required')
        if inspect_seed(b,state)!=state['c10_status_intake']['seed_probe']:raise ValueError('original QUERY seed drift')
        proof=worker_probe(b,image,'/line_probe.py');proof['atomic_status']=worker_probe(b,image,'/status_probe.py');proof['worker_image']=image
        revised=prepare_atomic_recovery(config,state,proof,fx.remaining_calls())
        revised['c10_status_atomic_recovery']['partial_edit_call_id']=uses[0]['call_id']
        trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(state['issue_id'],)).fetchone()[0])
        if trial.get('harness_maintenance_only') is not True:raise ValueError('isolated maintenance route required')
        trial['maintenance_seed']={'source':source,'receipt':seed}
        con.execute('UPDATE test_revision_trials SET config=? WHERE issue_id=?',(json.dumps(trial,sort_keys=True),state['issue_id']))
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'phase':'STATUS-ATOMIC','attempt_limit':1,'delivery_approval':False}


def prepare_queue_diagnosis(state,output):
    """A new functional observation, not a replay of the partial-edit recovery."""
    if (state.get('c10_status_queue_intake') or state.get('stage')!='blocked'
            or state.get('category')!='c10_checkpoint_acceptance_failed'
            or state.get('c10_checkpoints',{}).get('atomic_contract')!='c10-status-observations-v1'):
        raise ValueError('unconsumed actual atomic STATUS queue failure required')
    gates.phase_state(state,'STATUS')
    try:import suite_failure as sf
    except ImportError:from broker import suite_failure as sf
    failure=state['suite_failure'];core=dict(failure);diagnostics=core.pop('diagnostic_read_files',None)
    if (diagnostics!=['app/static/app.js','app/static/index.html','tests/test_incremental_u3.py']
            or core!=sf.evidence(1,output,state['author_task'],state['snapshot']['volume'])
            or core['tests_executed']!=259 or core['exception_types']!=['AssertionError']
            or len(core['failures'])!=1 or core['failures'][0]['test']!=gates.C10
            or not re.search(r'(?m)^AssertionError: 1 != 0 : every issued request must be resolved by the harness$',output)
            or re.findall(r'(?m)^FAILED \(([^)]+)\)$',output)!=['failures=1']):
        raise ValueError('exact all259 sole pending1 assertion required')
    revised=copy.deepcopy(state)
    revised['c10_status_queue_intake']={'failed_task':state['author_task'],'snapshot':state['snapshot'],
        'validation':state['validation'],'failure':failure,'prior_diagnosis':state['functional_diagnosis'],
        'prior_receipt':revised.pop('functional_diagnosis_receipt'),'attempt_limit':1,
        'author_scope_authorized':False,'delivery_approval':False,'at':time.time()}
    note=('CTO READONLY NEW FUNCTIONAL QUEUE EVIDENCE. Read all four files completely. '
        'The actual atomic STATUS experiment was submitted in ONE multiline edit; '
        'full259 tests ran and only C10 now FAILS: pending_left=1, expected0. '
        'All earlier URL/current-stale rendering assertions were reached and passed. '
        'This is NOT the old missing-status metadata error or a tool/infra failure. '
        'Identify the REAL outstanding held GET from issuance order across QUERY, '
        'negative-control loadFeedback/input(delta), and status filter clicks. '
        'Explain why two status resolutions leave one held request and propose '
        'bounded real resolveOldest/resolveNewest plus flush handling which drains '
        'actual issued requests without falsifying observations. Never pending=[],'
        'pending.length=0, out.pending_left=0 or weaken any assertion. Do not edit '
        'QUERY/C09/product/preamble/tests or discard actual request promises. '
        'Review the complete candidate against original source; cannot approve '
        'or automatically admit another worker. If diagnosis supported use '
        'request_test_revision, optional_files=[], DRIVER_OBSERVATION: reason with '
        'concrete queue cause and experiment. Otherwise escalate_cto, UNRESOLVED: '
        'with missing evidence. Max1100chars. No CEO technical question, terminal, '
        'writes, cap/model change or success claim.\n'
        'DELIVERY_CURRENT_HARNESS_DIAGNOSIS_V1\nDELIVERY_STRUCTURED_DECISION_V1:technical\n'
        'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\n'
        'DELIVERY_DETERMINISTIC_READ_V1\n'+''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in delivery.paths()))
    revised['functional_diagnosis']=dict(author_task=state['author_task'],snapshot=state['snapshot'],
        validation=state['validation'],failure=failure,failure_origin='actual_atomic_status_queue_assertion',note=note,
        attempt_limit=1,at=time.time())
    revised.update(stage='maintenance_functional_diagnosis_dispatch',category='c10_status_queue_cto_intake',delivery_approval=False)
    return revised


def register_queue_diagnosis(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('c10_status_queue_intake'):return {'stage':state['stage'],'reused':True,'author_authorized':False}
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        query.idle(b,con,fx,settings,state,56)
        failure=state['suite_failure'];row=con.execute('SELECT output FROM frozen_suite_failures WHERE task_id=? AND output_sha256=?',
            (state['author_task'],failure['output_sha256'])).fetchone()
        if not row:raise ValueError('actual queue failure output required')
        revised=prepare_queue_diagnosis(state,row[0])
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'author_authorized':False,'delivery_approval':False}
