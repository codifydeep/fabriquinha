"""Controller attestation of one completed immutable v2 test review.

No worker report/endpoint, UI read fallback, mutable workspace or boolean claim
can approve tests. A terminal receipt is durable and never replays native work.
Frozen tests permit a subsequent implementation admission, not execution/merge.
"""
import hashlib
import ast
import json
import re
import time
from quality_review_verdict import parse as parse_decision, required_reads
try:
    from . import quality_review_launch as launch, quality_test_review as review
    from . import quality_review_reads as reads, read_stream_receipts, native, validation_job
    from . import controller_maintenance as maintenance, maintenance_job_clock as clock
    from . import quality_review_history as history
except ImportError:
    import quality_review_launch as launch, quality_test_review as review
    import quality_review_reads as reads, read_stream_receipts, native, validation_job
    import controller_maintenance as maintenance, maintenance_job_clock as clock
    import quality_review_history as history

quality=review.quality


def require(value):
    if not value:raise ValueError('exact native snapshot-bound test-review attestation required')


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_review_attestations('
        'source_task TEXT PRIMARY KEY,request_id TEXT UNIQUE,identity TEXT,receipt TEXT,'
        'identity_sha256 TEXT,receipt_sha256 TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS quality_review_observation_windows('
        'source_task TEXT PRIMARY KEY,identity_sha256 TEXT,state TEXT,state_sha256 TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS quality_review_attempt_attestations('
        'source_task TEXT PRIMARY KEY,request_id TEXT UNIQUE,identity TEXT,receipt TEXT,identity_sha256 TEXT,receipt_sha256 TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS quality_review_attempt_windows('
        'source_task TEXT PRIMARY KEY,request_id TEXT UNIQUE,identity_sha256 TEXT,state TEXT,state_sha256 TEXT)')


def status(b,source):
    terminal=load(b,source)
    if terminal:return terminal
    with b.db() as con:
        current=con.execute('SELECT state FROM quality_test_reviews WHERE source_task=?',(source,)).fetchone()
        assignment=json.loads(current[0]) if current else {}
        if any(k in assignment for k in ('bootstrap_marker','completion_marker')) and assignment['stage']!='admitted':return None
        request=assignment.get('request_id')
        table=history.window_table(con,source,request)
        if table!='quality_review_observation_windows':
            if not history.exists(con,table):return None
            row=con.execute('SELECT state,state_sha256 FROM '+table+' WHERE source_task=? AND request_id=?',(source,request)).fetchone()
            if not row:return None
            state=json.loads(row[0]);require(quality.digest(state)==row[1]);return state
        if not review.capture.enrollment.exists(con,'quality_review_observation_windows'):return None
        row=con.execute('SELECT state,state_sha256 FROM quality_review_observation_windows '
            'WHERE source_task=?',(source,)).fetchone()
    if not row:return None
    state=json.loads(row[0]);require(quality.digest(state)==row[1])
    return state


def observation_window(b,source,identity,context):
    now=time.time()
    with b.LOCK,b.db() as con:
        maintenance.transaction(con)
        if maintenance.current(con):raise validation_job.Pending('maintenance preserves original review observation')
        initialize(con)
        table=history.window_table(con,source,identity['request_id'])
        renewed=table!='quality_review_observation_windows'
        if renewed:
            row=con.execute('SELECT identity_sha256,state,state_sha256 FROM '+table+' WHERE source_task=? AND request_id=?',
                (source,identity['request_id'])).fetchone()
        else:
            row=con.execute('SELECT identity_sha256,state,state_sha256 FROM quality_review_observation_windows '
                'WHERE source_task=?',(source,)).fetchone()
        if row:
            state=json.loads(row[1]);require(row[0]==quality.digest(identity) and quality.digest(state)==row[2])
        else:
            state=dict(stage='awaiting_native_review_evidence',owner=context['reviewer'],started_at=now,
                deadline=now+1800,observations=0,alert_due=False,tests_approved=False,delivery_approval=False)
        adjusted=clock.deadline(con,b.PREFIX,state['deadline'],now,budget=1800)
        state.update(observations=state['observations']+1,alert_due=now>=adjusted-1200,
            next_action='observe the original native task and closed lease; do not rerun review')
        if renewed:
            conflict='source_task,request_id' if table=='quality_review_successor_windows' else 'source_task'
            con.execute('INSERT INTO '+table+' VALUES(?,?,?,?,?) '
                'ON CONFLICT('+conflict+') DO UPDATE SET state=excluded.state,state_sha256=excluded.state_sha256',
                (source,identity['request_id'],quality.digest(identity),json.dumps(state,sort_keys=True),quality.digest(state)))
        else:
            con.execute('INSERT INTO quality_review_observation_windows VALUES(?,?,?,?) '
                'ON CONFLICT(source_task) DO UPDATE SET state=excluded.state,state_sha256=excluded.state_sha256',
                (source,quality.digest(identity),json.dumps(state,sort_keys=True),quality.digest(state)))
    return state,now>=adjusted


def stored_row(con,source,request_id=None):
    """Current or exact historical receipt for transactional downstream gates."""
    if request_id is None:
        current=con.execute('SELECT state,state_sha256 FROM quality_test_reviews WHERE source_task=?',(source,)).fetchone()
        require(current is not None and quality.digest(json.loads(current[0]))==current[1])
        request_id=json.loads(current[0]).get('request_id')
    if request_id is None:return None
    rows=history.rows(con,'attestation',source=source)
    selected=[]
    for row in rows:
        identity,receipt=json.loads(row[0]),json.loads(row[1])
        require(quality.digest(identity)==row[2] and quality.digest(receipt)==row[3]
            and identity['source_task']==source and receipt['source_task']==source)
        if identity.get('request_id')==request_id and receipt.get('request_id')==request_id:selected.append(row)
    rows=selected;require(len(rows)<=1)
    if not rows:return None
    row=rows[0];identity,receipt=json.loads(row[0]),json.loads(row[1])
    require(quality.digest(identity)==row[2] and quality.digest(receipt)==row[3]
        and identity['source_task']==source and receipt['source_task']==source and receipt['request_id']==request_id)
    return row[1],row[3]


def load(b,source,*,request_id=None):
    with b.db() as con:
        rows=history.rows(con,'attestation',source=source)
        if not rows:return None
        for old in rows:
            old_identity,old_receipt=json.loads(old[0]),json.loads(old[1])
            require(quality.digest(old_identity)==old[2] and quality.digest(old_receipt)==old[3]
                and old_identity['namespace']==b.PREFIX and old_identity['source_task']==source
                and old_receipt['source_task']==source)
        if request_id is None:
            current=con.execute('SELECT state,state_sha256 FROM quality_test_reviews WHERE source_task=?',(source,)).fetchone()
            require(current is not None and quality.digest(json.loads(current[0]))==current[1])
            request_id=json.loads(current[0]).get('request_id')
        selected=[row for row in rows if json.loads(row[1]).get('request_id')==request_id]
        require(len(selected)<=1)
        if not selected:return None
        row=selected[0]
    identity,receipt=json.loads(row[0]),json.loads(row[1])
    require(quality.digest(identity)==row[2] and quality.digest(receipt)==row[3]
        and identity['namespace']==b.PREFIX and identity['source_task']==source
        and receipt['operation']=='immutable_test_review_attestation_v2' and receipt['source_task']==source
        and receipt['execution_authorized'] is False and receipt['delivery_approval'] is False
        and receipt['stage'] in ('tests_frozen','changes_requested','technical_blocked')
        and receipt['tests_approved'] is (receipt['stage']=='tests_frozen'))
    return receipt


def completion_diagnostic(output,packet,files,paths,messages):
    """Pure repair evidence; cannot parse around prose or approve a past run."""
    verdict_state='valid';required=paths
    try:
        choice=parse_decision(output,packet)
        required=required_reads(choice,packet,paths)
    except (ValueError,KeyError,TypeError,UnicodeError):
        verdict_state='invalid'
    return dict(operation='immutable_review_completion_diagnostic_v1',
        verdict_format=verdict_state,expected_format='one_exact_json_object',
        manifest_sha256=packet['manifest_sha256'],
        output_sha256=hashlib.sha256(output.encode()).hexdigest() if isinstance(output,str) else None,
        reads=reads.assessment(files,packet['manifest_sha256'],paths,messages,required_paths=required),
        tests_approved=False,execution_authorized=False,delivery_approval=False)


def verdict(output,packet,observed,prepared):
    value=parse_decision(output,packet)
    for finding in value['findings']:
        require(isinstance(finding,dict) and set(finding)=={'criterion','path','test','line','quote','expected','observed'}
            and finding['criterion'] in packet['plan']['criteria']
            and isinstance(finding['path'],str) and '/delivery/'+finding['path'] in observed
            and type(finding['line']) is int and finding['line']>=1
            and isinstance(finding['test'],str)
            and (finding['test']=='__module__' or finding['test'] in prepared['test_methods'].get(finding['path'],[])
                or finding['path'] in packet['plan']['new_tests'])
            and all(isinstance(finding[key],str) and 0<len(finding[key])<=500 for key in ('quote','expected','observed')))
        line=observed['/delivery/'+finding['path']]['line_content'].get(finding['line'])
        require(isinstance(line,str) and bool(finding['quote'].strip()) and finding['quote'] in line)
        if finding['test']!='__module__':
            lines=observed['/delivery/'+finding['path']]['line_content']
            tree=ast.parse('\n'.join(lines[n] for n in sorted(lines)).encode())
            require(any(isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name==finding['test']
                and node.lineno<=finding['line']<=node.end_lineno for node in ast.walk(tree)))
    return value


def collect(b,c,context,assignment,phase):
    phase['value']='native_identity'
    e,_,_,_,_=review.capture.authorize_source(b,c['source_task'])
    settings=json.loads((b.STATE/'native.json').read_text())
    require(settings['workspace_id']==e['workspace_id'] and settings['runtime_id']==e['runtime_id']
        and settings['agents'].get(c['agent_id'])=='review')
    task=native.task_record(settings,c['task_id'],c['agent_id'])
    if task.get('status') in ('queued','pending','running'):
        raise validation_job.Pending('observe the same native test-review task')
    note=review.note(b,context,assignment)
    require(task.get('id')==c['task_id'] and task.get('agent_id')==c['agent_id'] and task.get('status')=='completed'
        and task.get('issue_id')==c['issue_id'] and task.get('wakeup_id')==assignment['wakeup_id']
        and task.get('handoff_note')==note and task.get('workspace_id')==e['workspace_id']
        and task.get('runtime_id')==e['runtime_id'])
    runs=[r for r in native.issue_task_runs(settings,c['issue_id']) if r.get('agent_id')==c['agent_id']]
    runs=review.eligible_runs(b,context,assignment,runs)
    require(len(runs)==1 and runs[0].get('id')==c['task_id'])
    issue=native.issue_record(settings,c['issue_id'])
    require({key:issue.get(key) for key in ('id','workspace_id','title','description')}==context['requirements'])
    phase['value']='closed_review_execution'
    with b.db() as con:
        lease=con.execute('SELECT status,name FROM leases WHERE request_id=?',(c['request_id'],)).fetchone()
        require(lease is not None)
        if lease[0] in ('creating','starting','running','closing'):
            raise validation_job.Pending('observe the original review close; no rerun')
        require(lease[0]=='closed' and lease[1]==b.PREFIX+'-job-'+c['request_id'])
        grant=con.execute('SELECT used FROM grants WHERE request_id=?',(c['request_id'],)).fetchone()
        require(grant is not None and type(grant[0]) is int and grant[0]==1)
    expected=launch.evidence_payload(b,c['request_id'])
    with b.db() as con:
        creation=con.execute('SELECT payload FROM worker_creation_intents WHERE request_id=?',(c['request_id'],)).fetchone()
        require(creation is not None and json.loads(creation[0])==expected)
        transport=con.execute('SELECT state FROM quality_transport_intents WHERE request_id=?',(c['request_id'],)).fetchone()
        require(transport is not None and transport[0]=='opened')
        inspections=con.execute('SELECT receipt_sha256,receipt FROM worker_policy_observations WHERE request_id=?',
            (c['request_id'],)).fetchall()
        proofs=[json.loads(raw) for sha,raw in inspections if hashlib.sha256(raw.encode()).hexdigest()==sha]
        proof=[p for p in proofs if p.get('payload_sha256')==hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest()
            and p.get('worker_image')==expected['Image'] and p.get('docker_status')=='running'
            and p.get('normalized_differences')==[] and re.fullmatch('[a-f0-9]{64}',str(p.get('container_id')))]
        require(bool(proof))
        events=con.execute('SELECT method,session_id,success FROM acp_events WHERE request_id=? ORDER BY rowid',
            (c['request_id'],)).fetchall()
        require(any(r[0]=='initialize' and r[2]==1 for r in events)
            and any(r[0]=='session/new' and r[2]==1 for r in events))
        prompts=[r for r in events if r[0]=='session/prompt' and r[2]==1]
        require(bool(prompts) and all(con.execute('SELECT 1 FROM acp_sessions WHERE scope=? AND session_id=?',
            (c['scope'],r[1])).fetchone() for r in prompts))
        messages=read_stream_receipts.load(con,c['task_id'])
        capture=json.loads(con.execute('SELECT context FROM quality_red_captures WHERE task_id=?',
            (c['source_task'],)).fetchone()[0])
    phase['value']='native_terminal_verdict'
    output=(task.get('result') or {}).get('output')
    packet=context['packet']
    files=capture['copy']['prepared'].get('file_inventory')
    try:choice=parse_decision(output,packet)
    except (ValueError,KeyError,TypeError) as error:
        error.review_diagnostic=completion_diagnostic(output,packet,files,context['read_paths'],messages)
        raise
    required=required_reads(choice,packet,context['read_paths'])
    phase['value']='complete_snapshot_reads'
    prepared=capture['copy']['prepared'];files=prepared.get('file_inventory')
    require(isinstance(files,dict))
    plan=packet['plan']
    require(all(files.get(path,{}).get('sha256')==sha for path,sha in packet['red']['tests'].items()))
    try:
        observed=reads.observe(files,packet['manifest_sha256'],context['read_paths'],messages,
            include_content=True,required_paths=required)
    except (ValueError,KeyError,TypeError) as error:
        error.review_diagnostic=completion_diagnostic(output,packet,files,context['read_paths'],messages)
        raise
    phase['value']='native_terminal_verdict'
    decision=verdict(output,packet,observed,prepared)
    action=decision['action']
    stage={'approve_tests':'tests_frozen','request_changes':'changes_requested','escalate_cto':'technical_blocked'}[action]
    result=dict(operation='immutable_test_review_attestation_v2',source_task=c['source_task'],stage=stage,
        owner=context['cto'] if action=='escalate_cto' else plan['author'],review_task=c['task_id'],
        request_id=c['request_id'],plan=plan,red=packet['red'],manifest_sha256=packet['manifest_sha256'],
        plan_sha256=packet['plan_sha256'],red_sha256=packet['red_sha256'],verdict=decision,
        native_output_sha256=hashlib.sha256(output.encode()).hexdigest(),
        reads={path:{key:value for key,value in receipt.items() if key!='line_content'} for path,receipt in observed.items()},
        reads_stream_sha256=quality.digest(messages),worker_inspection_sha256=quality.digest(proof[-1]),
        read_scope='complete_snapshot' if set(required)==set(context['read_paths']) else 'rejection_new_tests_and_citations',
        tests_approved=action=='approve_tests',execution_authorized=False,delivery_approval=False)
    if action=='approve_tests':
        frozen=dict(operation='independent_test_review_v2',run_id=plan['run_id'],issue_id=plan['issue_id'],
            contract_sha256=plan['contract_sha256'],plan_sha256=quality.digest(plan),task_id=c['task_id'],
            author=plan['author'],reviewer=plan['reviewer'],manifest_sha256=packet['manifest_sha256'],
            red_sha256=packet['red_sha256'],decision='approve_tests',criteria=decision['criteria'],complete_reads=True,read_only=True)
        quality.review(plan,packet['red'],frozen)
        result.update(test_review=frozen,frozen_tests=dict(packet['red']['tests']),criterion_tests=plan['criterion_tests'])
    return result


def observe(b,source):
    review.capture.enrollment.canonical(source)
    with review.capture.observation_lock(b,source):
        previous=load(b,source)
        if previous:return previous
        launch.enabled(b)
        context,assignment=review.load(b,source)
        require(assignment['stage']=='admitted')
        with b.db() as con:
            if maintenance.current(con):raise validation_job.Pending('maintenance pauses new test-review attestation')
        request=assignment['request_id']
        identity=dict(namespace=b.PREFIX,source_task=source,request_id=request,
            assignment_sha256=quality.digest(context),assignment_state_sha256=quality.digest(assignment),
            packet_sha256=context['packet_sha256'])
        phase=dict(value='review_admission_provenance')
        window,expired=observation_window(b,source,identity,context)
        try:
            if expired:
                phase['value']='review_observation_deadline'
                raise ValueError('original review evidence observation deadline')
            c,registered,state=launch.context_for(b,request)
            require(registered==context and state==assignment)
            receipt=collect(b,c,context,assignment,phase)
        except validation_job.Pending as pending:
            pending.progress=window
            raise
        except (TimeoutError,OSError):
            pending=validation_job.Pending('observe original native/immutable evidence; no execution replay')
            pending.progress=window
            raise pending from None
        except (ValueError,KeyError,TypeError) as error:
            receipt=dict(operation='immutable_test_review_attestation_v2',source_task=source,
                stage='technical_blocked',owner=context['cto'],review_task=assignment['review_task'],request_id=request,
                incident=dict(category=phase['value'],error_type=type(error).__name__,automatic_retry=False,
                    expected_manifest_sha256=context['packet']['manifest_sha256'],
                    next_action='CTO inspect bound snapshot, native identity, reads and verdict; no identical retry'),
                tests_approved=False,execution_authorized=False,delivery_approval=False)
            if isinstance(error,reads.ReadRejected):receipt['incident']['file_diagnostic']=error.diagnostic
            if hasattr(error,'review_diagnostic'):receipt['incident']['completion_diagnostic']=error.review_diagnostic
        with b.LOCK,b.db() as con:
            maintenance.transaction(con)
            if maintenance.current(con):raise validation_job.Pending('maintenance preserves original review evidence')
            row=con.execute('SELECT context_sha256,state_sha256 FROM quality_test_reviews WHERE source_task=?',(source,)).fetchone()
            require(row is not None and tuple(row)==(identity['assignment_sha256'],identity['assignment_state_sha256']))
            if receipt['tests_approved']:
                require(review.admission(con,request) is not None
                    and quality.digest(read_stream_receipts.load(con,receipt['review_task']))==receipt['reads_stream_sha256'])
            existing=con.execute('SELECT request_id FROM quality_review_attestations WHERE source_task=?',(source,)).fetchone()
            table='quality_review_attestations'
            if history.successor(con,source,request):
                table='quality_review_successor_attestations'
            elif existing and existing[0]!=request:
                require(review.capture.enrollment.exists(con,'quality_review_attempts') and
                    con.execute('SELECT 1 FROM quality_review_attempts WHERE source_task=? AND request_id=?',(source,request)).fetchone())
                table='quality_review_attempt_attestations'
            con.execute('INSERT INTO '+table+' VALUES(?,?,?,?,?,?)',
                (source,request,json.dumps(identity,sort_keys=True),json.dumps(receipt,sort_keys=True),
                    quality.digest(identity),quality.digest(receipt)))
        return receipt
