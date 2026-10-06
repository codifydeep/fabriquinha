"""One small real edit on the preserved STATUS snapshot, not a full regeneration."""
import copy,json,time
from pathlib import Path
import c10_micro_drain as micro
try:
    import c10_event_author as author,c10_event_plan as event,c10_status_admission as status
except ImportError:
    from broker import c10_event_author as author,c10_event_plan as event,c10_status_admission as status

FLAGS=('readless_edit_denied','comment_before_write_denied','outside_before_write_denied',
    'direct_handler_fenced','generic_write_and_terminal_denied','exact_recipe_applied',
    'all_other_bytes_preserved','stale_edit_denied','proxy_marker_schema_preserved','credentials_absent')


def scope(cp):
    return status.gates.sha(('STATUS-MICRO:'+cp['failed_task']+':'+cp['authority']['certificate']['decision_sha256']+
        ':'+cp['execution_seed']['validation']['test_sha256']+':'+cp['micro_code_sha256']+
        ':'+cp['worker_image']+':'+cp['admission_code_sha256']).encode())


def note(state):
    cp=state['c10_checkpoints']
    return ('STATUS MICRO OPERATION, NOT FULL CODE GENERATION. Read the entire '
        '/workspace/tests/test_incremental_u3.py freshly. This is the preserved '
        'REAL STATUS delivery, not the three-line placeholder. CTO explicitly '
        'selected '+cp['micro_resolver']+' to resolve remaining gamma AFTER the '
        'existing stale-status DOM observation. Call surgical_test_edit ONCE '
        'with path=/workspace/tests/test_incremental_u3.py, expected_sha256='+
        cp['execution_seed']['validation']['test_sha256']+', ONE edits element '
        'start_line=551,end_line=551,new=the exact executable value in the tool schema. '
        'Do not describe operations or write comments. The schema pins an executable '
        'recipe: resolve the real stale request with items:[], flush, then measure '
        'pending.length. Every existing event, DOM observation, test, assertion and '
        'all other file bytes remain unchanged. No code generation, terminal, generic '
        'write, Red, fabricated tests or approvals. Stop after a verified actual '
        'tool result; controller freezes output, runs full259 and independent review. '
        'No delivery claim.\nDELIVERY_DRIVER_CHECKPOINT_V3\n')


def prepare(config,state,proof,remaining):
    if (state.get('c10_micro_recovery') or state.get('stage')!='blocked'
            or state.get('category')!='unchanged_functional_driver' or remaining<48
            or config['author']==config['cto'] or not state.get('c10_event_author')
            or state.get('delivery_approval') is not False):
        raise ValueError('one unchanged failed event author and48-call reserve required')
    report=author.authority(state);old=state['c10_checkpoints']
    if (state['validation']['test_sha256']!=old['seed']['validation']['test_sha256']
            or state['validation']['manifest_sha256']!=old['seed']['validation']['manifest_sha256']):
        raise ValueError('exact unwritten author output required')
    seed=dict(state['c10_event_plan_intake']['seed'],checkpoint=2)
    original=state['c10_event_author']['prior_checkpoint']
    shadow=dict(state,snapshot=seed['snapshot'],validation=seed['validation'],c10_checkpoints=original)
    status.gates.phase_state(shadow,'STATUS')
    audit=proof.get('micro_drain',{})
    if (proof.get('schema')!='surgical-driver-registry-probe-v3' or proof.get('status')!='passed'
            or proof.get('network')!='none' or proof.get('uid')!=10000
            or any(proof.get(k) is not True for k in status.syntax.FLAGS)
            or audit.get('schema')!='surgical-micro-drain-probe-v1' or audit.get('status')!='passed'
            or audit.get('uid')!=10000 or audit.get('network')!='none' or audit.get('model_calls')!=0
            or audit.get('delivery_approval') is not False or any(audit.get(k) is not True for k in FLAGS)):
        raise ValueError('actual new micro worker qualification required')
    revised=copy.deepcopy(state);cp=copy.deepcopy(old)
    for key in ('scope_receipt','final_receipt','atomic_contract','event_plan_contract'):cp.pop(key,None)
    cp.update(micro_contract='status-drain-v1',micro_resolver=state['c10_event_plan_intake']['verification']['plan']['drain']['operation'],
        execution_seed=seed,authority=report,failed_task=state['author_task'],qualification=proof,
        worker_image=proof['worker_image'],micro_code_sha256=status.gates.sha(Path(micro.__file__).read_bytes()),
        admission_code_sha256=status.gates.sha(Path(__file__).read_bytes()),at=time.time())
    cp['scope_id']=scope(cp);revised.update(c10_checkpoints=cp,author_task=seed['task_id'],snapshot=seed['snapshot'],validation=seed['validation'])
    cp['note_sha256']=status.gates.sha(note(revised).encode())
    revised['staged']['driver_guard'].update(qualification=proof,worker_image=proof['worker_image'])
    revised['c10_micro_recovery']={'failed_task':state['author_task'],'failed_snapshot':state['snapshot'],
        'failed_validation':state['validation'],'prior_checkpoint':old,'checkpoint':copy.deepcopy(cp),
        'attempt_limit':1,'delivery_approval':False,'at':time.time()}
    revised.update(stage='checkpoint_dispatch_intent',category='c10_micro_author_authorized',delivery_approval=False)
    return revised


def binding(state,receipt):
    cp=state['c10_checkpoints']
    if (cp.get('micro_contract')!='status-drain-v1' or cp.get('attempt_limit')!=1
            or cp!=state.get('c10_micro_recovery',{}).get('checkpoint') or cp['execution_seed']!=receipt
            or cp['authority']!=author.authority(state) or cp['scope_id']!=scope(cp)
            or cp['seed']!=state['c10_status_intake']['seed']
            or cp['query_receipt']!=state['c10_status_intake']['query_receipt']
            or cp['admission_code_sha256']!=status.gates.sha(Path(__file__).read_bytes())
            or cp['micro_code_sha256']!=status.gates.sha(Path(micro.__file__).read_bytes())):
        raise ValueError('exact micro scope and preserved original QUERY lineage required')
    return True


def select(config,state,task):
    cp=state['c10_checkpoints'];binding(state,cp['execution_seed'])
    if (state.get('stage')!='awaiting_author' or task.get('agent_id')!=config['author']
            or task.get('issue_id')!=state['issue_id'] or task.get('wakeup_id')!=state['wakeup_id']
            or note(state) not in (task.get('handoff_note') or '')
            or status.gates.sha(note(state).encode())!=cp['note_sha256']
            or cp['qualification']!=state['staged']['driver_guard']['qualification']):
        raise ValueError('exact micro author task required')
    return {'worker_image':cp['worker_image'],'surgical':{'path':'/workspace/tests/test_incremental_u3.py',
        'expected_sha256':cp['execution_seed']['validation']['test_sha256'],
        'protocol':'typed_driver_lines_v4','drain_resolver':cp['micro_resolver']}}


def arm(b,source,image):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        event.recovery.admission_controls_spike.verify_current(con,config)
        if state.get('c10_micro_recovery'):return {'stage':state['stage'],'reused':True,'delivery_approval':False}
        settings=json.loads((b.STATE/'native.json').read_text());fx=event.recovery.handoff_runtime.Effects(b,settings)
        event.recovery.query.idle(b,con,fx,settings,state,48)
        task=status.native.task_record(settings,state['author_task'],config['author'])
        if task.get('status')!='completed' or task.get('wakeup_id')!=state['wakeup_id']:raise ValueError('actual unwritten native author required')
        messages=status.native.task_messages(settings,task['id'])
        calls=[m for m in messages if m.get('type')=='tool_use' and m.get('tool')=='surgical_test_edit']
        if len(calls)!=2:raise ValueError('two actual comment-only rejected proposals required')
        for call in calls:
            args=call['input'];results=[m for m in messages if m.get('type')=='tool_result' and m.get('call_id')==call['call_id']]
            if (args.get('path')!='/workspace/tests/test_incremental_u3.py'
                    or args.get('expected_sha256')!=state['c10_checkpoints']['seed']['validation']['test_sha256']
                    or len(args.get('edits',[]))!=1 or not args['edits'][0].get('new','').lstrip().startswith('//')
                    or '\n' in args['edits'][0].get('new','') or len(results)!=1
                    or results[0].get('output_truncated') is not False
                    or 'surgical_edit_rejected:status_atomic_shape_required:' not in results[0].get('output','')):
                raise ValueError('exact native comment-only rejection evidence required')
        report=author.authority(state);seed=state['c10_event_plan_intake']['seed']
        shadow=dict(state,author_task=seed['task_id'],snapshot=seed['snapshot'],validation=seed['validation'])
        cto=status.native.task_record(settings,report['certificate']['task_id'],config['cto'])
        try:import harness_repair_task as h
        except ImportError:from broker import harness_repair_task as h
        decision=fx.decision(cto);cert=h.qualify_diagnosis(config,shadow,cto,decision,fx.read_evidence(cto))
        if status.delivery.qualify_functional_decision(shadow,decision,cert)!=report:raise ValueError('actual current CTO choice required')
        if event.recovery.replay(b,shadow)!=state['c10_event_plan_intake']['trace']:raise ValueError('preserved real STATUS source drift')
        proof=status.worker_probe(b,image,'/line_probe.py');proof['micro_drain']=status.worker_probe(b,image,'/micro_probe.py');proof['worker_image']=image
        revised=prepare(config,state,proof,fx.remaining_calls())
        trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(state['issue_id'],)).fetchone()[0])
        if trial.get('harness_maintenance_only') is not True:raise ValueError('isolated maintenance route required')
        trial['maintenance_seed']={'source':source,'receipt':revised['c10_checkpoints']['execution_seed']}
        con.execute('UPDATE test_revision_trials SET config=? WHERE issue_id=?',(json.dumps(trial,sort_keys=True),state['issue_id']))
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'scope_id':revised['c10_checkpoints']['scope_id'],'attempt_limit':1,'delivery_approval':False}
