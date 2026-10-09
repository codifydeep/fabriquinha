"""Native CTO/Tech Lead scope-plan execution; never install or grant edits.

Intents precede native effects. Exact wakeup markers reconcile unknown POST
acknowledgments. Terminal failures remain visible, without identical respawns.
This adapter is not enabled by importing it: runtime installation must also
provide exact immutable planning mounts and a qualified contract installer.
"""
import hashlib
import json
from artifact_read_evidence import coverage
from product_scope_contract import instruction
try:
    from . import product_scope_ledger as ledger, native, read_stream_receipts
except ImportError:
    import product_scope_ledger as ledger
    import native, read_stream_receipts


def observed_hashes(messages,expected):
    reads=coverage(messages,include_content=True)
    hashes={}
    for path,sha in expected.items():
        receipt=reads.get('/evidence/candidate/'+path,{})
        if (not receipt or receipt.get('lines')!=receipt.get('total_lines')
                or not receipt.get('line_content')):
            raise ValueError('complete task-bound dependency read required')
        text='\n'.join(receipt['line_content'][i] for i in range(1,receipt['total_lines']+1))
        # Numbered line transport does not retain the final newline. Both byte
        # candidates must still match the already verified snapshot SHA exactly.
        if sha not in {hashlib.sha256(value.encode()).hexdigest() for value in (text,text+'\n')}:
            raise ValueError('observed dependency bytes differ from frozen snapshot')
        hashes[path]=sha
    return hashes


def terminal_output(task):
    text=(task.get('result') or {}).get('output')
    if not isinstance(text,str) or not 1<=len(text.encode())<=5000:
        raise ValueError('bounded actual structured native result required')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate native decision field')
            result[key]=value
        return result
    value=json.loads(text,object_pairs_hook=unique,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite decision')))
    if not isinstance(value,dict):raise ValueError('native structured object required; no prose recovery')
    return value


class NativeEffects:
    def __init__(self,b):
        self.b=b
        self.settings=json.loads((b.STATE/'native.json').read_text())

    def verify_binding(self,state):
        """Only a current failed immutable delivery can sponsor this plan."""
        b=self.b;c=state['context']
        with b.db() as con:
            try:import controller_maintenance
            except ImportError:from broker import controller_maintenance
            if controller_maintenance.current(con):raise ValueError('scope execution paused for maintenance')
            row=con.execute('SELECT source_task,stage,data FROM delivery_handoffs WHERE issue_id=? '
                'AND stage<>? ORDER BY updated DESC LIMIT 1',(c['issue_id'],'superseded')).fetchone()
            route=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(c['issue_id'],)).fetchone()
            snap=con.execute('SELECT volume,status FROM snapshots WHERE task_id=?',(c['source_task'],)).fetchone()
            if not row or not route or not snap:raise ValueError('current immutable scope sponsor required')
            data=json.loads(row[2]);route=json.loads(route[0]);failure=data.get('validation_failure') or {}
            if (row[0]!=c['source_task'] or row[1]!='technical_decision_required' or snap[1]!='complete'
                    or route.get('enabled') is not True or route['contract_sha256']!=c['contract_sha256']
                    or any(route[k]!=c[v] for k,v in (('author','author'),('cto','cto'),('techlead','reviewer')))
                    or failure.get('category')!='executed_test_failure'
                    or failure.get('source_task')!=c['source_task'] or failure.get('volume')!=snap[0]
                    or failure.get('output_sha256')!=c['failure_output_sha256']
                    or any(failure.get('diagnostic_source_hashes',{}).get(p)!=sha
                           for p,sha in c['eligible_code_sha256'].items())):
                raise ValueError('scope sponsor identity or evidence drift')
            if con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) "
                "WHERE n.issue_id=? AND l.status IN ('creating','starting','running') LIMIT 1",
                (c['issue_id'],)).fetchone():
                # Observation of the selected planning task is allowed; its
                # read-only lease does not grant implementation capacity.
                active=con.execute("SELECT DISTINCT n.agent_id FROM native_bindings n JOIN leases l USING(request_id) "
                    "WHERE n.issue_id=? AND l.status IN ('creating','starting','running')",(c['issue_id'],)).fetchall()
                if any(r[0] not in (c['cto'],c['reviewer']) for r in active):
                    raise ValueError('author must remain inactive during scope review')
            jobs=con.execute('SELECT identity,state FROM validation_jobs').fetchall()
        qualified=False
        for raw_identity,raw_state in jobs:
            identity=json.loads(raw_identity);job=json.loads(raw_state)
            if identity.get('task')!=c['source_task'] or identity.get('kind')!='structure':continue
            payload=identity.get('payload') or {};result=job.get('result') or {}
            if (job.get('stage')!='complete' or result.get('exit_code')!=0
                    or payload.get('Image')!=b.OFFLINE_IMAGE
                    or not any(m.get('Source')==snap[0] and m.get('ReadOnly') is True
                        for m in payload.get('HostConfig',{}).get('Mounts',[]))):continue
            output=result.get('output','')
            if hashlib.sha256(output.encode()).hexdigest()!=result.get('output_sha256'):continue
            proof=json.loads(output)
            if (proof.get('manifest_sha256')==c['snapshot_sha256'] and proof.get('baseline_tests_intact') is True
                    and proof.get('new_test_sha256')==c['frozen_test_sha256']
                    and all(proof.get('diagnostic_file_sha256',{}).get(p)==sha
                            for p,sha in c['eligible_code_sha256'].items())):qualified=True
        if not qualified:raise ValueError('qualified current validator snapshot inventory required')
        volume=b.docker('GET','/volumes/'+snap[0]);labels=(volume or {}).get('Labels',{})
        if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=c['source_task']:
            raise ValueError('owned immutable delivery snapshot required')
        source=native.task_record(self.settings,c['source_task'],c['author'])
        if source.get('status')!='completed' or source.get('issue_id')!=c['issue_id']:
            raise ValueError('completed original author task required')

    def wake(self,state,phase,marker,note,*,allow_create=True):
        c=state['context'];actor=c['cto'] if phase=='proposal' else c['reviewer']
        return native.ensure_planning_start(self.settings,c['issue_id'],actor,c['source_task'],marker,note,
                                           allow_create=allow_create)

    def task(self,identifier,actor):return native.task_record(self.settings,identifier,actor)

    def read_hashes(self,task,expected):
        with self.b.db() as con:durable=read_stream_receipts.load(con,task['id'])
        messages=read_stream_receipts.merge([],durable)
        # Do not substitute UI projections for controller-bound full read pages.
        return observed_hashes(messages,expected)

    def delivery_reads(self,task):
        with self.b.db() as con:durable=read_stream_receipts.load(con,task['id'])
        # Only task/request-bound full handler results are authoritative. Model
        # statements and truncated UI transcripts cannot substitute inspection.
        return coverage(read_stream_receipts.merge([],durable))


def save(b,before,after):
    with b.LOCK,b.db() as con:return ledger.save_transition(con,before,after)


def dispatch_note(state,phase):
    if phase not in ('proposal','review'):raise ValueError('known scope dispatch phase required')
    c=state['context']
    marker=ledger.policy.digest(dict(plan=state['key'],phase=phase,proposal=state.get('proposal_sha256')))
    wire_context={k:c[k] for k in ('issue_id','source_task','contract_sha256','snapshot_sha256',
        'failure_output_sha256','eligible_code_sha256','frozen_test_sha256')}
    note=instruction(phase,wire_context,state.get('proposal_sha256') if phase=='review' else None)
    if phase=='review':note+='\nExact proposal data: '+ledger.encoded(state['proposal'])
    if len(note)>3800:raise ValueError('bounded scope planning instruction required')
    return marker,note


def prompt(b,task,effects=None):
    """Present only the authenticated scope protocol, not historical work notes."""
    identifier=task.get('task_id') or task.get('id');actor=task.get('agent_id');issue=task.get('issue_id')
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='product_scope_plans'").fetchone():
            raise ValueError('registered scope planning prompt required')
        states=[json.loads(r[0]) for r in con.execute('SELECT data FROM product_scope_plans')]
    matches=[]
    for state in states:
        if state['context']['issue_id']!=issue:continue
        phase='proposal' if actor==state['context']['cto'] else 'review' if actor==state['context']['reviewer'] else None
        if not phase or state['stage']!=('awaiting_proposal' if phase=='proposal' else 'awaiting_review'):continue
        marker,note=dispatch_note(state,phase)
        exact='DELIVERY_PLANNING_START '+marker+'\nSource: '+state['context']['source_task']+'\n'+note
        if task.get('handoff_note')==exact:matches.append((state,phase,marker,note,exact))
    if len(matches)!=1:raise ValueError('one exact active scope planning prompt required')
    state,phase,marker,note,exact=matches[0];dispatch=state.get('dispatch',{}).get(phase)
    if not dispatch or dispatch['marker']!=marker:raise ValueError('persisted scope prompt dispatch required')
    fx=effects or NativeEffects(b)
    fx.verify_binding(state)
    wake=fx.wake(state,phase,marker,note,allow_create=False)
    if (not wake or task.get('wakeup_id')!=wake.get('id') or wake.get('last_task_id')!=identifier
            or dispatch.get('wakeup_id') not in (None,wake['id'])):
        raise ValueError('exact existing scope prompt wakeup and task required')
    return exact


def mounts(b,request_id,effects=None):
    """A native request sees only its registered immutable sponsor, read-only.

    Wakeup observation uses allow_create=False: worker construction may never
    create planning tasks. A persisted dispatch intent handles lost POST acks.
    """
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='product_scope_plans'").fetchone():
            return []
        plans=[json.loads(r[0]) for r in con.execute('SELECT data FROM product_scope_plans')]
        if not plans:return []
        binding=con.execute('SELECT task_id,issue_id,agent_id FROM native_bindings WHERE request_id=?',
                            (request_id,)).fetchone()
        if not binding:return []
    task_id,issue,actor=tuple(binding)
    plans=[s for s in plans if s['context']['issue_id']==issue and actor in
           (s['context']['cto'],s['context']['reviewer'])]
    if not plans:return []
    fx=effects or NativeEffects(b)
    task=fx.task(task_id,actor)
    if task.get('id')!=task_id or task.get('issue_id')!=issue or task.get('agent_id')!=actor:
        raise ValueError('scope mount native task identity drift')
    note=task.get('handoff_note') or ''
    if 'DELIVERY_PRODUCT_SCOPE_V1:' not in note:
        # An older independent technical diagnosis for the same actor is not
        # implicitly a scope-plan execution. Keep its own mount mechanism.
        return []
    matches=[]
    for state in plans:
        phase='proposal' if actor==state['context']['cto'] else 'review'
        if state['stage']!=('awaiting_proposal' if phase=='proposal' else 'awaiting_review'):continue
        dispatch=state.get('dispatch',{}).get(phase)
        if not dispatch:continue
        marker,instruction_text=dispatch_note(state,phase)
        exact='DELIVERY_PLANNING_START '+marker+'\nSource: '+state['context']['source_task']+'\n'+instruction_text
        if dispatch['marker']==marker and note==exact:matches.append((state,phase,marker,instruction_text))
    if len(matches)!=1 or task.get('status') not in ('queued','running'):
        raise ValueError('one active exact scope mount registration required')
    state,phase,marker,instruction_text=matches[0]
    fx.verify_binding(state)
    wake=fx.wake(state,phase,marker,instruction_text,allow_create=False)
    if (not wake or task.get('wakeup_id')!=wake.get('id')
            or state['dispatch'][phase].get('wakeup_id') not in (None,wake.get('id'))):
        raise ValueError('scope mount wakeup identity drift')
    with b.db() as con:
        if ledger.load(con,state['key'])!=state:raise ValueError('scope mount registration changed')
        snapshot=con.execute('SELECT volume,status FROM snapshots WHERE task_id=?',
                             (state['context']['source_task'],)).fetchone()
    if not snapshot or snapshot[1]!='complete':raise ValueError('complete scope sponsor snapshot required')
    volume=b.docker('GET','/volumes/'+snapshot[0]);labels=(volume or {}).get('Labels',{})
    if (labels.get('delivery-kit.owner')!=b.OWNER
            or labels.get('delivery-kit.source-task')!=state['context']['source_task']):
        raise ValueError('scope mount volume ownership drift')
    return [dict(Type='volume',Source=snapshot[0],Target='/evidence/candidate',ReadOnly=True)]


def tick(b,key,effects=None):
    fx=effects or NativeEffects(b)
    with b.LOCK,b.db() as con:state=ledger.load(con,key)
    if state['stage'] in ('blocked','plan_approved','changes_requested'):return state
    if state['stage'] not in ('awaiting_proposal','awaiting_review'):
        raise ValueError('known scope execution phase required')
    fx.verify_binding(state)
    phase='proposal' if state['stage']=='awaiting_proposal' else 'review'
    c=state['context'];actor=c['cto'] if phase=='proposal' else c['reviewer']
    marker,note=dispatch_note(state,phase)
    dispatch=state.get('dispatch',{}).get(phase)
    if not dispatch:
        state=save(b,state,dict(state,dispatch={**state.get('dispatch',{}),phase:dict(stage='intent',marker=marker)}))
    elif dispatch['marker']!=marker:raise ValueError('scope dispatch identity changed')
    wake=fx.wake(state,phase,marker,note)
    if not isinstance(wake,dict) or not isinstance(wake.get('id'),str) or not wake['id']:
        raise ValueError('observed native wakeup identity required')
    dispatch=state['dispatch'][phase]
    if dispatch.get('wakeup_id') not in (None,wake['id']):raise ValueError('native scope wakeup changed')
    if not dispatch.get('wakeup_id'):
        state=save(b,state,dict(state,dispatch={**state['dispatch'],phase:dict(dispatch,stage='observing',wakeup_id=wake['id'])}))
    task_id=wake.get('last_task_id')
    if not task_id:return state
    task=fx.task(task_id,actor)
    if (task.get('id')!=task_id or task.get('agent_id')!=actor or task.get('issue_id')!=c['issue_id']
            or task.get('wakeup_id')!=wake['id']):raise ValueError('selected native scope task identity drift')
    if task.get('status') in ('queued','running'):return state
    try:
        if task.get('status')!='completed':raise ValueError('scope planning task did not complete')
        decision=terminal_output(task)
        reads=fx.read_hashes(task,c['eligible_code_sha256'])
        if not isinstance(reads,dict) or reads!=c['eligible_code_sha256']:
            raise ValueError('complete exact scope dependency read hashes required')
        with b.LOCK,b.db() as con:
            if ledger.load(con,key)!=state:raise ValueError('scope state changed during native observation')
            if phase=='proposal':return ledger.record_proposal(con,key,decision,task)
            return ledger.record_review(con,key,decision,task,reads)
    except (ValueError,TypeError,KeyError):
        # No terminal prose repair, tests waiver, dispatch reset or author retry.
        return save(b,state,dict(state,stage='blocked',incident=dict(category='invalid_scope_'+phase,
                    task_id=task_id,owner=actor,next_action='independent_diagnosis',automatic_retry=False)))
