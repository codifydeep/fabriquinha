"""First native tests-only v2 capability; no legacy route or worker endpoint.

The capability, native binding and persistent phase commit atomically. A lost
capability response is not recoverable by minting another attempt. Installation
must wire the returned selection into filesystem/tool handlers before launch;
calling this module alone never launches a worker or authorizes product edits.
"""
import hashlib
import json
import secrets
import time
import uuid

try:
    from . import quality_lifecycle_enrollment as enrollment,quality_lifecycle_v2 as quality
    from . import quality_red_capture as capture,controller_maintenance as maintenance,native
except ImportError:
    import quality_lifecycle_enrollment as enrollment,quality_lifecycle_v2 as quality
    import quality_red_capture as capture,controller_maintenance as maintenance,native


def require(value):
    if not value:raise ValueError('authenticated first tests-only v2 admission required')


def initialize(con):
    capture.initialize(con)
    con.execute('CREATE TABLE IF NOT EXISTS quality_author_admissions('
        'issue_id TEXT PRIMARY KEY,task_id TEXT UNIQUE,request_id TEXT UNIQUE,'
        'context TEXT NOT NULL,context_sha256 TEXT NOT NULL)')


def load(con,request_id):
    initialize(con)
    row=con.execute('SELECT context,context_sha256 FROM quality_author_admissions WHERE request_id=?',
        (request_id,)).fetchone()
    if not row:return None
    context=json.loads(row[0]);require(quality.digest(context)==row[1])
    e=enrollment.lookup(con,context['issue_id'])
    require(e is not None and quality.digest(e)==context['enrollment_sha256'])
    require(context['request_id']==request_id and context['phase']=='tests_only_v2'
        and context['attempt']==1 and context['mode']=='implementation')
    binding=con.execute('SELECT n.task_id,n.agent_id,n.scope,n.issue_id,g.mode,g.attempt,'
        'q.run_id,q.phase,q.plan_sha256 FROM native_bindings n JOIN grants g USING(request_id) '
        'JOIN quality_native_scopes q ON q.request_id=n.request_id AND q.task_id=n.task_id '
        'WHERE n.request_id=?',(request_id,)).fetchall()
    require(len(binding)==1 and tuple(binding[0])==tuple(context[k] for k in
        ('task_id','agent_id','scope','issue_id','mode','attempt','run_id','phase','plan_sha256')))
    require(con.execute('SELECT max(attempt) FROM grants WHERE task_id=?',
        (context['task_id'],)).fetchone()[0]==1)
    return context


def selection(b,request_id):
    """Exact worker contract; integration must not replace it with issue editables."""
    enrollment.canonical(request_id)
    with b.db() as con:
        c=load(con,request_id)
        require(c is not None)
        row=con.execute('SELECT config FROM quality_lifecycle_enrollments WHERE issue_id=?',
            (c['issue_id'],)).fetchone()
        plan,spec=enrollment.request(json.loads(row[0]))
    require(c['namespace']==b.PREFIX and c['plan_sha256']==quality.digest(plan))
    return dict(phase='tests_only_v2',scope=c['scope'],base=c['base'],
        editable_paths=['/workspace/'+p for p in sorted(plan['new_tests'])],
        read_paths=['/workspace/'+p for p in sorted(spec['files'])],
        test_commands=[],terminal_allowed=False,product_edits_allowed=False,
        legacy_calibration_allowed=False,delivery_approval=False)


def admit(b,task_id,agent_id,*,now=None):
    for value in (task_id,agent_id):enrollment.canonical(value)
    now=time.time() if now is None else now
    settings=json.loads((b.STATE/'native.json').read_text())
    task=native.task_record(settings,task_id,agent_id)
    require(task.get('id')==task_id and task.get('agent_id')==agent_id
        and task.get('status')=='running' and settings['agents'].get(agent_id)=='implementation'
        and task.get('workspace_id')==settings['workspace_id'] and task.get('runtime_id')==settings['runtime_id'])
    issue=task.get('issue_id');enrollment.canonical(issue)
    with b.db() as con:
        e=enrollment.lookup(con,issue);require(e is not None and e['namespace']==b.PREFIX)
        require(agent_id==e['author'] and settings['workspace_id']==e['workspace_id']
            and settings['runtime_id']==e['runtime_id'] and settings['agents'].get(e['reviewer'])=='review')
        plan,spec=enrollment.request(json.loads(con.execute(
            'SELECT config FROM quality_lifecycle_enrollments WHERE issue_id=?',(issue,)).fetchone()[0]))
    # Native and Docker observations do not hold a database writer/global lock.
    runs=native.issue_task_runs(settings,issue)
    require(len(runs)==1 and runs[0].get('id')==task_id and runs[0].get('agent_id')==agent_id)
    base=b.issue_base(issue)
    require(all(base.get(k)==e[v] for k,v in (('issue_id','issue_id'),('base_sha','base_sha'),
        ('volume','base_volume'),('manifest_sha256','base_manifest_sha256'))))
    scope=settings['workspace_id']+':'+agent_id+':implementation:'+task_id
    with b.LOCK,b.db() as con:
        maintenance.require_admission(con);initialize(con)
        require(enrollment.lookup(con,issue)==e and json.loads((b.STATE/'native.json').read_text())==settings)
        durable=con.execute('SELECT issue_id,base_sha,volume,manifest_sha256 FROM issue_bases WHERE issue_id=?',
            (issue,)).fetchone()
        require(durable is not None and tuple(durable)==tuple(base[k] for k in
            ('issue_id','base_sha','volume','manifest_sha256')))
        # No automatic retry, secret readback, or legacy grant reuse.
        require(not con.execute('SELECT 1 FROM quality_author_admissions WHERE issue_id=? OR task_id=?',
            (issue,task_id)).fetchone())
        require(not con.execute('SELECT 1 FROM native_bindings WHERE task_id=? OR issue_id=?',
            (task_id,issue)).fetchone())
        require(not con.execute('SELECT 1 FROM grants WHERE task_id=?',(task_id,)).fetchone())
        require(not con.execute('SELECT 1 FROM grants g LEFT JOIN leases l USING(request_id) '
            'WHERE g.used=1 AND l.request_id IS NULL LIMIT 1').fetchone())
        active=con.execute("SELECT count(*) FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()[0]
        reserved=con.execute('SELECT count(*) FROM grants WHERE used=0 AND deadline>?',(now,)).fetchone()[0]
        require(active+reserved<2)
        require(not con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) "
            "WHERE n.agent_id=? AND l.status IN ('creating','starting','running','closing')",(agent_id,)).fetchone())
        require(not con.execute('SELECT 1 FROM native_bindings n JOIN grants g USING(request_id) '
            'WHERE n.agent_id=? AND g.used=0 AND g.deadline>?',(agent_id,now)).fetchone())
        request_id=str(uuid.uuid4());token=secrets.token_hex(32)
        context=dict(namespace=b.PREFIX,issue_id=issue,task_id=task_id,agent_id=agent_id,scope=scope,
            request_id=request_id,mode='implementation',attempt=1,run_id=e['run_id'],phase='tests_only_v2',
            plan_sha256=quality.digest(plan),enrollment_sha256=quality.digest(e),base=dict(base))
        con.execute('INSERT INTO grants(digest,task_id,attempt,mode,request_id,deadline,used) VALUES(?,?,?,?,?,?,?)',
            (hashlib.sha256(token.encode()).hexdigest(),task_id,1,'implementation',request_id,now+480,0))
        con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',(request_id,task_id,agent_id,scope,issue))
        con.execute('INSERT INTO quality_native_scopes VALUES(?,?,?,?,?)',
            (request_id,task_id,e['run_id'],'tests_only_v2',quality.digest(plan)))
        con.execute('INSERT INTO quality_author_admissions VALUES(?,?,?,?,?)',
            (issue,task_id,request_id,json.dumps(context,sort_keys=True),quality.digest(context)))
    return dict(capability=token,request_id=request_id,task_id=task_id,attempt=1,mode='implementation')
