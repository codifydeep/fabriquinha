"""Explicit once-only author scope for a verified non-executing queue event plan."""
import copy
import json
from pathlib import Path
import time
try:
    import c10_event_plan as event,c10_status_admission as status
except ImportError:
    from broker import c10_event_plan as event,c10_status_admission as status


def authority(state):
    intake=state['c10_event_plan_intake'];report=state['functional_diagnosis_receipt']
    shadow=dict(state,snapshot=intake['seed']['snapshot'],validation=intake['seed']['validation'])
    proof=event.validate(shadow,report)
    if proof!=intake.get('verification'):raise ValueError('exact verified event authority required')
    return report


def scope(cp):
    return status.gates.sha(('STATUS-EVENT:'+cp['failed_task']+':'+
        cp['authority']['certificate']['decision_sha256']+':'+cp['seed']['validation']['test_sha256']+
        ':'+cp['admission_code_sha256']+':'+cp['event_admission_sha256']).encode())


def prepare(config,state,remaining):
    if (state.get('c10_event_author') or state.get('stage')!='blocked'
            or state.get('category')!='c10_event_plan_verified' or remaining<48
            or config['author']==config['cto'] or state.get('delivery_approval') is not False):
        raise ValueError('new verified event scope and48-call reserve required')
    report=authority(state);old=state['c10_checkpoints'];status.gates.phase_state(state,'STATUS')
    if (old.get('atomic_contract')!='c10-status-observations-v1'
            or old.get('seed')!=state['c10_status_intake']['seed']
            or old.get('query_receipt')!=state['c10_status_intake']['query_receipt']
            or old['qualification']!=state['staged']['driver_guard']['qualification']):
        raise ValueError('exact consumed atomic scope and original QUERY lineage required')
    revised=copy.deepcopy(state);cp=copy.deepcopy(old)
    for key in ('scope_receipt','final_receipt'):cp.pop(key,None)
    cp.update(authority=report,failed_task=state['author_task'],event_plan_contract='queue-event-plan-v1',
        event_admission_sha256=status.gates.sha(Path(__file__).read_bytes()),
        admission_code_sha256=status.gates.sha(Path(status.__file__).read_bytes()),at=time.time())
    cp['scope_id']=scope(cp)
    revised.update(c10_checkpoints=cp,author_task=cp['seed']['task_id'],
        snapshot=cp['seed']['snapshot'],validation=cp['seed']['validation'])
    cp['note_sha256']=status.gates.sha(status.author_note(revised).encode())
    revised['c10_event_author']={'prior_checkpoint':old,'failed_snapshot':state['snapshot'],
        'failed_validation':state['validation'],'failed_task':state['author_task'],
        'authority':report,'checkpoint':copy.deepcopy(cp),'attempt_limit':1,
        'author_authorized':True,'delivery_approval':False,'at':time.time()}
    revised.update(stage='checkpoint_dispatch_intent',category='c10_event_plan_author_authorized',delivery_approval=False)
    return revised


def binding(state,receipt):
    cp=state['c10_checkpoints'];saved=state.get('c10_event_author',{})
    if (cp.get('event_plan_contract')!='queue-event-plan-v1' or cp.get('attempt_limit')!=1
            or saved.get('author_authorized') is not True or saved.get('checkpoint')!=cp
            or cp.get('seed')!=receipt or receipt!=state['c10_status_intake']['seed']
            or cp.get('query_receipt')!=state['c10_status_intake']['query_receipt']
            or cp.get('authority')!=authority(state) or cp.get('scope_id')!=scope(cp)
            or cp.get('event_admission_sha256')!=status.gates.sha(Path(__file__).read_bytes())
            or cp.get('admission_code_sha256')!=status.gates.sha(Path(status.__file__).read_bytes())):
        raise ValueError('exact admitted event scope and seed required')
    return True


def arm(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        event.recovery.admission_controls_spike.verify_current(con,config)
        if state.get('c10_event_author'):return {'stage':state['stage'],'reused':True,'delivery_approval':False}
        settings=json.loads((b.STATE/'native.json').read_text());fx=event.recovery.handoff_runtime.Effects(b,settings)
        event.recovery.query.idle(b,con,fx,settings,state,48)
        report=authority(state);task=status.native.task_record(settings,report['certificate']['task_id'],config['cto'])
        try:import harness_repair_task as h
        except ImportError:from broker import harness_repair_task as h
        decision=fx.decision(task);cert=h.qualify_diagnosis(config,state,task,decision,fx.read_evidence(task))
        if status.delivery.qualify_functional_decision(state,decision,cert)!=report:
            raise ValueError('actual independent structured CTO submission required')
        if event.recovery.replay(b,state)!=state['c10_event_plan_intake']['trace']:
            raise ValueError('exact observed failed snapshot required')
        if status.inspect_seed(b,state)!=state['c10_status_intake']['seed_probe']:
            raise ValueError('original QUERY seed changed')
        image=state['c10_checkpoints']['worker_image']
        proof=status.worker_probe(b,image,'/line_probe.py')
        proof['atomic_status']=status.worker_probe(b,image,'/status_probe.py');proof['worker_image']=image
        if proof!=state['c10_checkpoints']['qualification']:
            raise ValueError('actual unchanged atomic worker qualification required')
        revised=prepare(config,state,fx.remaining_calls())
        trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(state['issue_id'],)).fetchone()[0])
        if trial.get('harness_maintenance_only') is not True:raise ValueError('isolated maintenance-only route required')
        trial['maintenance_seed']={'source':source,'receipt':revised['c10_checkpoints']['seed']}
        con.execute('UPDATE test_revision_trials SET config=? WHERE issue_id=?',(json.dumps(trial,sort_keys=True),state['issue_id']))
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'scope_id':revised['c10_checkpoints']['scope_id'],
        'attempt_limit':1,'delivery_approval':False}
