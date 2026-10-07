"""One controller-only replan after proven preserved-file capacity rejection.

No tools/API endpoint expose registration. A trusted operator supplies the
fixed readonly filesystem probe; native failures and current policy are also
checked live. This does not authorize an author, reset depth, change a limit,
or accept Red. The existing independent CTO protocol owns the next decision.
"""
import hashlib,json,time
from pathlib import Path


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS seeded_byte_budget_replans(issue_id TEXT PRIMARY KEY,source_task TEXT,receipt TEXT)')


def qualified(con,issue,source,data):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='seeded_byte_budget_replans'").fetchone():return False
    row=con.execute('SELECT source_task,receipt FROM seeded_byte_budget_replans WHERE issue_id=?',(issue,)).fetchone()
    return bool(row and row[0]==source and json.loads(row[1])==data.get('byte_budget_replan'))


def verify_proof(proof,seed,scope,namespace):
    expected=namespace+'-work-'+hashlib.sha256(scope.encode()).hexdigest()[:32]
    if (set(proof)!={'volume','bytes','sha256','regular','canonical','owner','nlink','writable_mode'}
            or proof['volume']!=expected or type(proof['bytes']) is not int or not 32000<=proof['bytes']<=32768
            or proof['sha256']!=seed or proof['regular'] is not True or proof['canonical'] is not True
            or type(proof['owner']) is not int or proof['owner']!=0
            or type(proof['nlink']) is not int or proof['nlink']!=1 or proof['writable_mode'] is not True):
        raise ValueError('exact unchanged valid fenced target with small byte headroom required')


def register(b,source,proof):
    try:import native,handoffs,remediation_runtime_guard as guard
    except ImportError:from broker import native,handoffs,remediation_runtime_guard as guard
    with b.LOCK:
        with b.db() as con:
            initialize(con)
            row=con.execute('SELECT issue_id,stage,data FROM delivery_handoffs WHERE source_task=?',(source,)).fetchone()
            if not row:raise ValueError('exact blocked source required')
            issue=row[0];old=json.loads(row[2])
            previous=con.execute('SELECT source_task,receipt FROM seeded_byte_budget_replans WHERE issue_id=?',(issue,)).fetchone()
            if previous:
                if previous[0]!=source:raise ValueError('one byte-budget replan per issue; no repeated recovery')
                return json.loads(previous[1])
            if (row[1]!='test_first_blocked' or old.get('error')!='test_first_correction_failed_after_cto_diagnosis'
                    or old.get('phase')!='test_first'
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()
                    or con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()):
                raise ValueError('idle exact blocked pre-Red correction required')
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
            bound=con.execute('SELECT n.scope,l.status FROM native_bindings n JOIN leases l USING(request_id) '
                'WHERE n.task_id=? AND n.issue_id=? AND n.agent_id=?',(source,issue,route['author'])).fetchall()
            if len(bound)!=1 or bound[0][1]!='closed':raise ValueError('one closed actual author binding required')
        value=guard.qualified(b,issue)
        if not value or not value.get('amendment') or not route.get('enabled'):raise ValueError('enabled qualified tests-only amendment required')
        hashes=value['previous_new_test_delivery']['test_sha256']
        if len(hashes)!=1:raise ValueError('one unchanged seeded NEW test required')
        target='/workspace/'+next(iter(hashes));verify_proof(proof,next(iter(hashes.values())),bound[0][0],b.PREFIX)
        volume=b.docker('GET','/volumes/'+proof['volume'])
        if any(volume.get('Labels',{}).get(k)!=v for k,v in {'delivery-kit.owner':b.OWNER,'delivery-kit.scope':bound[0][0]}.items()):
            raise ValueError('owned exact preserved workspace required')
        settings=json.loads((b.STATE/'native.json').read_text())
        task=native.task_record(settings,source,route['author']);runs=native.issue_task_runs(settings,issue)
        authors=[t for t in runs if t.get('agent_id')==route['author']]
        if (task['status']!='failed' or task['issue_id']!=issue
                or any(t['status'] in ('queued','dispatched','running') for t in runs)
                or max(authors,key=lambda t:(t.get('created_at') or '',t['id']))['id']!=source):
            raise ValueError('latest terminal failed author with no pending task required')
        outputs=[m.get('output','') for m in native.task_messages(settings,source)
                 if m.get('type')=='tool_result' and m.get('tool')=='patch']
        expected='patch failed for '+target+': Failed to write changes: Failed to write file:'
        if len(outputs)!=2 or any(not x.startswith(expected) or 'invalid fenced write target or size' not in x for x in outputs):
            raise ValueError('two actual correlated legacy fenced write rejections required')
        path=Path('/fenced_file_write.py') if Path('/fenced_file_write.py').exists() else Path(__file__).with_name('fenced_file_write.py')
        policy=path.read_bytes()
        if b'fenced write size exceeds ' not in policy or b'MAX_BYTES = 32768' not in policy:
            raise ValueError('changed fixed byte-feedback policy required; no identical retry')
        receipt=dict(operation='preserved_seed_byte_budget_replan_v1',source_task=source,issue_id=issue,
            previous=old,proof=proof,policy_sha256=hashlib.sha256(policy).hexdigest(),attempt_limit=1,
            author_retry_authorized=False,limits_increased=False,revision_depth_reset=False,delivery_approval=False)
        diagnostic=dict(kind='preserved_seed_capacity_rejection',issue_id=issue,task_id=source,
            reason='Canonical writable seeded NEW test is unchanged at '+str(proof['bytes'])+
                ' bytes, leaving '+str(32768-proof['bytes'])+' bytes before the unchanged32768 write limit. '
                'The two additions were rejected without changing bytes. Require a narrow COMMENT-only reduction '
                'before additions, preserving all methods/assertions, then repair harness and run all calibration/Red/review gates. '
                'The writer now distinguishes size from path failure and the proxy reports observed byte headroom.',
            tests_executed=False,red_verified=False,delivery_approval=False)
        new={**old,'diagnostic':diagnostic,'byte_budget_replan':receipt,
             'required_action':'CTO decide one changed-precondition tests-only recovery; no product permission'}
        with b.db() as con:
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():
                raise ValueError('worker started during byte-budget qualification')
            if json.loads(con.execute('SELECT data FROM delivery_handoffs WHERE source_task=?',(source,)).fetchone()[0])!=old:
                raise ValueError('blocked source changed during qualification')
            con.execute('INSERT INTO seeded_byte_budget_replans VALUES(?,?,?)',(issue,source,json.dumps(receipt,sort_keys=True)))
            handoffs.save(con,source,issue,'technical_decision_required',route['cto'],new,time.time())
        return receipt
