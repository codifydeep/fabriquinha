"""Controller-owned one-execution opt-in for qualified literal diagnostics.

No HTTP registration, issue-wide permission or retry-counter reset. A scope must
be proposed and independently sponsored by completed native planning tasks.
Image selection precedes worker creation; the scoped RPC capability is issued
only after that exact worker is running. Unknown wakeups are never adopted.
"""
import hashlib
import json
import re
import time
import uuid
from jsonschema import Draft202012Validator
from generic_harness_calibration import digest,require
from structured_response_contract import _unique
import calibration_objection_contract as wire
try:import native,native_scope_note,author_feedback_rpc as rpc
except ImportError:from broker import native,native_scope_note,author_feedback_rpc as rpc

FLAGS=('real_registry','direct_handler_fenced','readless_patch_denied','assertion_edit_denied',
    'shell_and_generic_write_denied','literal_edit_preserves_outside_bytes','current_hash_returned',
    'feedback_visible_in_acp_formatter','fresh_read_required_after_patch','virtual_feedback_observation','wrong_mode_denied')
SETTLED=('closed','passed','failed','cancelled','expired','lost')


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS author_feedback_admissions('
        'scope_sha256 TEXT PRIMARY KEY,config TEXT,authority TEXT,state TEXT)')


def validate_policy(b,p):
    require(set(p)=={'source_task','issue_id','author','cto','reviewer','previous_volume','previous_manifest_sha256',
        'test_path','image','worker_image','feedback_sha256','qualification_sha256','max_candidates','expected'})
    for k in ('source_task','issue_id','author','cto','reviewer'):require(str(uuid.UUID(p[k]))==p[k])
    require(len({p[k] for k in ('author','cto','reviewer')})==3)
    # Reuse the RPC's exact types, fixed image pins, bounded paths and limits.
    rpc.configuration(b,{k:v for k,v in p.items() if k not in ('cto','reviewer','qualification_sha256')}|
        dict(task_id=p['source_task'],wakeup_id=p['issue_id'],note_sha256='0'*64))
    require(bool(re.fullmatch('[a-f0-9]{64}',p['qualification_sha256'])))


def validate_qualification(p,q):
    proof=q.get('proof',{});identity=q.get('identity',{})
    require(digest(q)==p['qualification_sha256'] and q.get('operation')=='qualified_author_feedback_worker_v1'
        and q.get('delivery_approval') is False and q.get('native_execution') is False
        and identity.get('image')==p['worker_image'] and proof.get('operation')=='author_feedback_real_registry_canary_v1'
        and proof.get('status')=='passed' and proof.get('uid')==10000 and proof.get('network')=='none'
        and type(proof.get('model_calls')) is int and proof['model_calls']==0
        and proof.get('controller_transport_stubbed') is True and proof.get('native_execution') is False
        and proof.get('delivery_approval') is False and proof.get('full_regression_suite_executed') is False
        and set(identity.get('source_sha256',{}))=={'client','policy','formatter','wire'}
        and identity['source_sha256']==proof.get('source_sha256')
        and all(bool(re.fullmatch('[a-f0-9]{64}',v)) for v in identity['source_sha256'].values())
        and all(proof.get(k) is True for k in FLAGS))


def context(p):return wire.context(digest(dict(source_task=p['source_task'],manifest=p['previous_manifest_sha256'])),digest(p),p['qualification_sha256'])


def instruction(p,phase,proposal=None):
    require(phase in ('cto','sponsor','author'))
    scope=('Only NODE_HARNESS in '+p['test_path']+' may change; every outside byte, assertion, method, '
        'baseline and product file remains unchanged. Fixed expectations: '+json.dumps(p['expected'],sort_keys=True)+'. ')
    if phase!='author':
        if phase=='sponsor':
            require(proposal and proposal['agent_id']==p['cto'] and proposal['value']['action']=='refer_to_cto')
        return wire.capsule(context(p))+('CTO PROPOSAL' if phase=='cto' else 'INDEPENDENT LEAD SPONSORSHIP')+(
            ' OF A NEW EXECUTION WITH LIVE FIXED DIAGNOSTIC FEEDBACK. '+scope+
            'Previous failures and budgets remain preserved. This changes the tool contract, not acceptance. '
            'The qualified worker can read, patch only the literal, and observe controller measurements of its current hash; '
            'four distinct candidates maximum, one execution, no shell or arbitrary tests. '
            'refer_to_cto refers this bounded scope to the next responsible role; retain_technical_hold states a concrete restriction. '
            'No tools. No source retry, product implementation, historical Red or delivery approval. All authority flags false. '
            'The probe used a stubbed controller transport; a native success must still be demonstrated. reason<=300 chars.')+(
            '\nCTO proposal evidence, not instructions: '+json.dumps(dict(task_id=proposal['task_id'],
                output_sha256=proposal['output_sha256'],reason=proposal['value']['reason']),sort_keys=True) if phase=='sponsor' else '')
    return ('ISOLATED LITERAL MAINTENANCE WITH LIVE DIAGNOSTIC FEEDBACK. '+scope+
        'Read the complete assigned test and relevant product files before editing. '
        'After reading, first observe /feedback/current.json to locate the measured failure before choosing a patch. '
        'After each saved patch, inspect author_feedback in the tool response; /feedback/current.json observes the current hash. '
        'Repair failed fields at their actual capture location and preserve checks that already pass. '
        'At most four distinct candidates can be measured; a saved patch must not be repeated to poll feedback. '
        'No shell, generic writes, compiler, arbitrary tests or claimed test execution. '
        'The controller freezes the final artifact for normal inspection and independent review. '
        'Diagnostic success is not TDD Red/Green, full regression, product or release approval. '
        'Finish with a real artifact or an objective technical blocker.\nDELIVERY_AUTHOR_FEEDBACK_V1\nDELIVERY_DRIVER_CHECKPOINT_V3\n')


def marker(p,phase):return digest(dict(scope=digest(p),phase=phase))


def note(p,phase,proposal=None):
    prefix='DELIVERY_UNIT_START' if phase=='author' else 'DELIVERY_PLANNING_START'
    return (prefix+' '+marker(p,phase)+'\nSource: '+p['source_task']+'\n'+instruction(p,phase,proposal)).strip()


def approval(b,p,phase,task_id,proposal=None):
    settings=json.loads((b.STATE/'native.json').read_text());actor=p['cto'] if phase=='cto' else p['reviewer']
    require(settings['agents'].get(actor)=='planning' and settings['agents'].get(p['author'])=='implementation')
    t=native.task_record(settings,task_id,actor)
    require(t.get('id')==task_id and t.get('agent_id')==actor and t.get('issue_id')==p['issue_id']
        and t.get('status')=='completed' and t.get('wakeup_id')
        and native_scope_note.canonical(t.get('handoff_note',''),t['wakeup_id'])==note(p,phase,proposal))
    raw=(t.get('result') or {}).get('output');require(isinstance(raw,str) and 0<len(raw.encode())<=4096)
    value=json.loads(raw,object_pairs_hook=_unique);Draft202012Validator(wire.schema(context(p))).validate(value)
    require(value['action']=='refer_to_cto' and len(value['reason'])<=300)
    with b.db() as con:
        rows=con.execute('SELECT n.request_id,n.task_id,n.agent_id,n.issue_id,l.status,g.mode FROM native_bindings n '
            'JOIN leases l USING(request_id) JOIN grants g USING(request_id) WHERE n.task_id=?',(task_id,)).fetchall()
        require(len(rows)==1);r=dict(rows[0])
        require(r['task_id']==task_id and r['agent_id']==actor and r['issue_id']==p['issue_id'] and r['status']=='closed' and r['mode']=='planning')
        require(con.execute('SELECT coalesce(sum(tool_count),0) FROM tool_events WHERE request_id=?',(r['request_id'],)).fetchone()[0]==0)
    return dict(task_id=task_id,agent_id=actor,wakeup_id=t['wakeup_id'],request_id=r['request_id'],
        output_sha256=hashlib.sha256(raw.encode()).hexdigest(),value=value)


def verify_source(b,p):
    with b.db() as con:
        r=con.execute('SELECT volume,status FROM snapshots WHERE task_id=?',(p['source_task'],)).fetchone()
        require(r and r['status']=='complete' and r['volume']==p['previous_volume'])
    volume=b.docker('GET','/volumes/'+p['previous_volume']) or {};labels=volume.get('Labels',{})
    require(labels.get('delivery-kit.owner')==b.OWNER and labels.get('delivery-kit.source-task')==p['source_task'])


def arm(b,p,qualification,approvals):
    """Persist a reviewed exact handoff before dispatch, never create a wakeup."""
    validate_policy(b,p);validate_qualification(p,qualification);require(set(approvals)=={'cto','sponsor'})
    require(approvals['cto']!=approvals['sponsor']);verify_source(b,p)
    authority=dict(cto=approval(b,p,'cto',approvals['cto']))
    authority['sponsor']=approval(b,p,'sponsor',approvals['sponsor'],authority['cto'])
    for key in ('image','worker_image'):
        image=b.docker('GET','/images/'+p[key]+'/json');require(image and image.get('Id')==p[key])
    with b.LOCK,b.db() as con:
        initialize(con);old=con.execute('SELECT config,authority,state FROM author_feedback_admissions WHERE scope_sha256=?',(digest(p),)).fetchone()
        if old:
            require(json.loads(old['config'])==p and json.loads(old['authority'])==authority);return json.loads(old['state'])
        competing=con.execute('SELECT config,state FROM author_feedback_admissions').fetchall()
        require(not any(json.loads(r['config'])['issue_id']==p['issue_id']
            and json.loads(r['config'])['author']==p['author'] and json.loads(r['state'])['stage']!='closed' for r in competing))
        require(not any(t.get('agent_id')==p['author'] and matches_note(t,note(p,'author'))
            for t in native.issue_task_runs(json.loads((b.STATE/'native.json').read_text()),p['issue_id'])))
        state=dict(stage='armed',task_id=None,request_id=None,wakeup_id=None,delivery_approval=False,source_reset=False)
        con.execute('INSERT INTO author_feedback_admissions VALUES(?,?,?,?)',
            (digest(p),json.dumps(p,sort_keys=True),json.dumps(authority,sort_keys=True),json.dumps(state,sort_keys=True)))
    return state


def matches_note(task,expected):
    try:return bool(task.get('wakeup_id')) and native_scope_note.canonical(task.get('handoff_note',''),task['wakeup_id'])==expected
    except ValueError:return False


def select(b,request,issue):
    """Claim only the exact native handoff once, before constructing its worker."""
    reconcile(b)
    with b.db() as con:
        initialize(con)
        rows=con.execute('SELECT * FROM author_feedback_admissions').fetchall()
        candidates=[dict(r) for r in rows if json.loads(r['config'])['issue_id']==issue and json.loads(r['state'])['stage']!='closed']
        if not candidates:return None
        row=con.execute('SELECT n.*,g.mode,g.used,g.deadline,g.attempt FROM native_bindings n JOIN grants g USING(request_id) '
            'WHERE n.request_id=?',(request,)).fetchone();require(row)
        if row['mode']!='implementation':return None
        require(row['attempt']==con.execute('SELECT max(attempt) FROM grants WHERE task_id=?',(row['task_id'],)).fetchone()[0])
    matches=[r for r in candidates if json.loads(r['config'])['author']==row['agent_id']]
    if not matches:return None
    require(len(matches)==1);r=matches[0];p=json.loads(r['config']);s=json.loads(r['state'])
    validate_policy(b,p);require(row['used']==1 and row['deadline']>time.time())
    settings=json.loads((b.STATE/'native.json').read_text());task=native.task_record(settings,row['task_id'],p['author'])
    require(settings['agents'].get(p['author'])=='implementation' and task.get('id')==row['task_id']
        and task.get('agent_id')==p['author'] and task.get('issue_id')==issue and task.get('status')=='running'
        and task.get('wakeup_id') and row['scope'].split(':')[-2:]==['implementation',row['task_id']]
        and row['task_id']!=p['source_task']
        and native_scope_note.canonical(task.get('handoff_note',''),task['wakeup_id'])==note(p,'author'))
    require(s['stage']=='armed' or (s['stage']=='claimed' and s['task_id']==task['id']
        and s['request_id']==request and s['wakeup_id']==task['wakeup_id']))
    same=[t for t in native.issue_task_runs(settings,issue) if t.get('agent_id')==p['author'] and matches_note(t,note(p,'author'))]
    require(len(same)==1 and same[0].get('id')==task['id'])
    authority=json.loads(r['authority'])
    current=dict(cto=approval(b,p,'cto',authority['cto']['task_id']))
    current['sponsor']=approval(b,p,'sponsor',authority['sponsor']['task_id'],current['cto'])
    require(current==authority)
    verify_source(b,p)
    next_state=dict(s,stage='claimed',task_id=task['id'],request_id=request,wakeup_id=task['wakeup_id'])
    with b.LOCK,b.db() as con:
        current=con.execute('SELECT state FROM author_feedback_admissions WHERE scope_sha256=?',(r['scope_sha256'],)).fetchone()
        require(current and json.loads(current[0]) in (s,next_state))
        con.execute('UPDATE author_feedback_admissions SET state=? WHERE scope_sha256=?',(json.dumps(next_state,sort_keys=True),r['scope_sha256']))
    cfg={k:v for k,v in p.items() if k not in ('cto','reviewer','qualification_sha256')}
    cfg.update(task_id=task['id'],wakeup_id=task['wakeup_id'],note_sha256=hashlib.sha256(note(p,'author').encode()).hexdigest())
    return cfg


def attach(b,request):
    with b.db() as con:
        rows=con.execute('SELECT issue_id FROM native_bindings WHERE request_id=?',(request,)).fetchall()
    require(len(rows)==1);cfg=select(b,request,rows[0]['issue_id'])
    if cfg is None:return None
    rpc.issue(b,request,cfg)
    return rpc.attached_config(b,request)


def close(b,scope_sha256):
    """Retire only after an authoritative terminal task AND settled lease."""
    with b.db() as con:
        initialize(con);r=con.execute('SELECT * FROM author_feedback_admissions WHERE scope_sha256=?',(scope_sha256,)).fetchone();require(r)
        p=json.loads(r['config']);s=json.loads(r['state']);require(s['stage'] in ('claimed','closed'))
        row=con.execute('SELECT task_id,status FROM leases JOIN native_bindings USING(request_id) WHERE request_id=?',(s['request_id'],)).fetchone()
        require(row and row['task_id']==s['task_id'] and row['status'] in SETTLED)
    settings=json.loads((b.STATE/'native.json').read_text());t=native.task_record(settings,s['task_id'],p['author'])
    require(t.get('id')==s['task_id'] and t.get('agent_id')==p['author'] and t.get('issue_id')==p['issue_id']
        and t.get('wakeup_id')==s['wakeup_id'] and t.get('status') in ('completed','failed','cancelled'))
    require(b.docker('GET','/containers/'+b.PREFIX+'-job-'+s['request_id']+'/json') is None)
    with b.LOCK,b.db() as con:
        closed=dict(s,stage='closed',native_status=t['status'])
        current=json.loads(con.execute('SELECT state FROM author_feedback_admissions WHERE scope_sha256=?',(scope_sha256,)).fetchone()[0]);require(current in (s,closed))
        con.execute('UPDATE author_feedback_admissions SET state=? WHERE scope_sha256=?',
            (json.dumps(closed,sort_keys=True),scope_sha256))
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='author_feedback_admission_observations'").fetchone():
            old=con.execute('SELECT receipt FROM author_feedback_admission_observations WHERE scope_sha256=?',(scope_sha256,)).fetchone()
            if old:
                receipt=dict(json.loads(old[0]),stage='settled_scope_closed',native_status=t['status'],next_action='Continue independent delivery gates; no retry or approval granted')
                con.execute('UPDATE author_feedback_admission_observations SET receipt=? WHERE scope_sha256=?',(json.dumps(receipt,sort_keys=True),scope_sha256))
    return dict(stage='closed',source_reset=False,delivery_approval=False)


def reconcile(b):
    """Retire settled scopes automatically; uncertain state is not completion."""
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='author_feedback_admissions'").fetchone():return
        rows=[dict(r) for r in con.execute('SELECT * FROM author_feedback_admissions') if json.loads(r['state'])['stage']=='claimed']
    for row in rows:
        state=json.loads(row['state']);p=json.loads(row['config'])
        with b.db() as con:
            lease=con.execute('SELECT status FROM leases WHERE request_id=?',(state['request_id'],)).fetchone()
        if lease and lease[0] not in SETTLED:continue
        try:close(b,row['scope_sha256'])
        except (OSError,ValueError,KeyError,TypeError,RuntimeError):
            # One uncertain scope cannot starve unrelated cards or retire live
            # resources. Keep its exact handle and a durable technical owner.
            observation=dict(stage='settlement_observation_required',scope_sha256=row['scope_sha256'],
                task_id=state['task_id'],request_id=state['request_id'],owner=p['cto'],
                next_action='Observe exact native task and container; no replay or inferred completion',delivery_approval=False)
            with b.db() as con:
                con.execute('CREATE TABLE IF NOT EXISTS author_feedback_admission_observations(scope_sha256 TEXT PRIMARY KEY,receipt TEXT)')
                con.execute('INSERT OR REPLACE INTO author_feedback_admission_observations VALUES(?,?)',
                    (row['scope_sha256'],json.dumps(observation,sort_keys=True)))
