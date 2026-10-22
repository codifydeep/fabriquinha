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
try:
    from . import quality_review_launch as launch, quality_test_review as review
    from . import quality_review_reads as reads, read_stream_receipts, native, validation_job
    from . import controller_maintenance as maintenance, maintenance_job_clock as clock
except ImportError:
    import quality_review_launch as launch, quality_test_review as review
    import quality_review_reads as reads, read_stream_receipts, native, validation_job
    import controller_maintenance as maintenance, maintenance_job_clock as clock

quality=review.quality


def require(value):
    if not value:raise ValueError('exact native snapshot-bound test-review attestation required')


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_review_attestations('
        'source_task TEXT PRIMARY KEY,request_id TEXT UNIQUE,identity TEXT,receipt TEXT,'
        'identity_sha256 TEXT,receipt_sha256 TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS quality_review_observation_windows('
        'source_task TEXT PRIMARY KEY,identity_sha256 TEXT,state TEXT,state_sha256 TEXT)')


def status(b,source):
    terminal=load(b,source)
    if terminal:return terminal
    with b.db() as con:
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
        con.execute('INSERT INTO quality_review_observation_windows VALUES(?,?,?,?) '
            'ON CONFLICT(source_task) DO UPDATE SET state=excluded.state,state_sha256=excluded.state_sha256',
            (source,quality.digest(identity),json.dumps(state,sort_keys=True),quality.digest(state)))
    return state,now>=adjusted


def load(b,source):
    with b.db() as con:
        initialize(con)
        row=con.execute('SELECT identity,receipt,identity_sha256,receipt_sha256 FROM quality_review_attestations '
            'WHERE source_task=?',(source,)).fetchone()
    if not row:return None
    identity,receipt=json.loads(row[0]),json.loads(row[1])
    require(quality.digest(identity)==row[2] and quality.digest(receipt)==row[3]
        and identity['namespace']==b.PREFIX and identity['source_task']==source
        and receipt['operation']=='immutable_test_review_attestation_v2' and receipt['source_task']==source
        and receipt['execution_authorized'] is False and receipt['delivery_approval'] is False
        and receipt['stage'] in ('tests_frozen','changes_requested','technical_blocked')
        and receipt['tests_approved'] is (receipt['stage']=='tests_frozen'))
    return receipt


def verdict(output,packet,observed,prepared):
    require(isinstance(output,str) and 0<len(output.encode())<=16384)
    text=output.strip()
    fenced=re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```',text,re.I|re.S)
    if fenced:text=fenced.group(1)
    def unique(pairs):
        require(len({key for key,_ in pairs})==len(pairs));return dict(pairs)
    def invalid(value):raise ValueError('non-finite review verdict')
    value=json.loads(text,object_pairs_hook=unique,parse_constant=invalid)
    require(isinstance(value,dict) and set(value)=={'action','reason','manifest_sha256','plan_sha256',
        'red_sha256','criteria','findings'} and value['action'] in ('approve_tests','request_changes','escalate_cto')
        and isinstance(value['reason'],str) and 0<len(value['reason'])<=1200 and bool(value['reason'].strip())
        and all(value[key]==packet[key] for key in ('manifest_sha256','plan_sha256','red_sha256'))
        and isinstance(value['criteria'],list) and all(isinstance(item,str) for item in value['criteria'])
        and len(value['criteria'])==len(set(value['criteria']))
        and set(value['criteria'])==set(packet['plan']['criteria'])
        and isinstance(value['findings'],list) and len(value['findings'])<=8)
    if value['action']=='approve_tests':require(not value['findings'])
    if value['action']=='request_changes':require(bool(value['findings']))
    for finding in value['findings']:
        require(isinstance(finding,dict) and set(finding)=={'criterion','path','test','line','quote','expected','observed'}
            and finding['criterion'] in packet['plan']['criteria']
            and isinstance(finding['path'],str) and '/delivery/'+finding['path'] in observed
            and type(finding['line']) is int and finding['line']>=1
            and isinstance(finding['test'],str)
            and (finding['test']=='__module__' or finding['test'] in prepared['test_methods'].get(finding['path'],[]))
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
    note='DELIVERY_REVIEW_START '+context['marker']+'\nSource: '+c['source_task']+'\n'+context['instruction']
    require(task.get('id')==c['task_id'] and task.get('agent_id')==c['agent_id'] and task.get('status')=='completed'
        and task.get('issue_id')==c['issue_id'] and task.get('wakeup_id')==assignment['wakeup_id']
        and task.get('handoff_note')==note and task.get('workspace_id')==e['workspace_id']
        and task.get('runtime_id')==e['runtime_id'])
    runs=[r for r in native.issue_task_runs(settings,c['issue_id']) if r.get('agent_id')==c['agent_id']]
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
    expected=launch.payload(b,c['request_id'])
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
    phase['value']='complete_snapshot_reads'
    prepared=capture['copy']['prepared'];files=prepared.get('file_inventory')
    require(isinstance(files,dict))
    packet=context['packet'];plan=packet['plan']
    require(all(files.get(path,{}).get('sha256')==sha for path,sha in packet['red']['tests'].items()))
    observed=reads.observe(files,packet['manifest_sha256'],context['read_paths'],messages,include_content=True)
    phase['value']='native_terminal_verdict'
    output=(task.get('result') or {}).get('output')
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
        with b.LOCK,b.db() as con:
            maintenance.transaction(con)
            if maintenance.current(con):raise validation_job.Pending('maintenance preserves original review evidence')
            row=con.execute('SELECT context_sha256,state_sha256 FROM quality_test_reviews WHERE source_task=?',(source,)).fetchone()
            require(row is not None and tuple(row)==(identity['assignment_sha256'],identity['assignment_state_sha256']))
            if receipt['tests_approved']:
                require(review.admission(con,request) is not None
                    and quality.digest(read_stream_receipts.load(con,receipt['review_task']))==receipt['reads_stream_sha256'])
            con.execute('INSERT INTO quality_review_attestations VALUES(?,?,?,?,?,?)',
                (source,request,json.dumps(identity,sort_keys=True),json.dumps(receipt,sort_keys=True),
                    quality.digest(identity),quality.digest(receipt)))
        return receipt
