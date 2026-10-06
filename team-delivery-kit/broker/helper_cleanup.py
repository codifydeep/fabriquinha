"""Durable stopped-helper cleanup, isolated from agent bootstrap and dispatch."""
import json,re,time,hashlib,uuid,urllib.parse

def new_name(b,role,issue,scope):
    if role not in ('seed','lock'):raise ValueError('fixed helper role required')
    filters=urllib.parse.quote(json.dumps({'label':['delivery-kit.owner='+b.OWNER,'delivery-kit.issue-id='+issue]}))
    running=b.docker('GET','/containers/json?filters='+filters)
    if any(any(n.lstrip('/').startswith((b.PREFIX+'-seed-',b.PREFIX+'-lock-')) for n in item.get('Names',[])) for item in running):
        raise ValueError('active issue preparation retained')
    return b.PREFIX+'-'+role+'-'+hashlib.sha256(scope.encode()).hexdigest()[:32]+'-'+uuid.uuid4().hex[:12]

def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS helper_cleanup(name TEXT PRIMARY KEY,issue_id TEXT,status TEXT,attempts INTEGER,next_try REAL,error TEXT)')

def schedule(b,name,issue):
    identity_label(b,name,issue)
    with b.db() as con:
        initialize(con)
        old=con.execute('SELECT issue_id FROM helper_cleanup WHERE name=?',(name,)).fetchone()
        if old and old['issue_id']!=issue:raise ValueError('helper ownership drift')
        con.execute('INSERT OR IGNORE INTO helper_cleanup VALUES(?,?,?,?,?,?)',(name,issue,'pending',0,time.time(),None))

def identity_label(b,name,identity):
    prefix=re.escape(b.PREFIX)
    if re.fullmatch(prefix+r'-(?:seed|lock)-[a-f0-9]{32}(?:-[a-f0-9]{12})?',name):return 'delivery-kit.issue-id'
    import uuid
    try:valid=str(uuid.UUID(identity))==identity
    except (ValueError,TypeError):valid=False
    if valid and (name in (b.PREFIX+'-snapshot-job-'+identity,b.PREFIX+'-failed-snapshot-job-'+identity)
            or re.fullmatch(prefix+r'-controls-job-[a-f0-9]{12}',name)):
        return 'delivery-kit.source-task'
    raise ValueError('fixed helper name required')

def tick(b):
    with b.db() as con:
        initialize(con)
        row=con.execute("SELECT * FROM helper_cleanup WHERE status='pending' AND next_try<=? ORDER BY next_try LIMIT 1",(time.time(),)).fetchone()
    if not row:return
    # Docker I/O deliberately happens without the controller LOCK or a DB transaction.
    try:
        info=b.docker('GET','/containers/'+row['name']+'/json')
        if info:
            labels=info['Config'].get('Labels',{})
            key=identity_label(b,row['name'],row['issue_id'])
            if labels.get('delivery-kit.owner')!=b.OWNER or labels.get(key)!=row['issue_id']:raise ValueError('foreign helper')
            if info['State']['Running']:raise ValueError('running helper retained')
            b.docker('DELETE','/containers/'+info['Id'])
        with b.db() as con:con.execute("UPDATE helper_cleanup SET status='done',error=NULL WHERE name=?",(row['name'],))
    except Exception as error:
        attempts=row['attempts']+1
        status='blocked' if isinstance(error,ValueError) or attempts>=3 else 'pending'
        with b.db() as con:con.execute('UPDATE helper_cleanup SET status=?,attempts=?,next_try=?,error=? WHERE name=?',
            (status,attempts,time.time()+30*attempts,type(error).__name__,row['name']))
        print(json.dumps({'event':'helper_cleanup_pending','name':row['name'],'status':status,'category':type(error).__name__}),flush=True)

def run(b):
    while True:
        try:tick(b)
        except Exception:print('helper cleanup unavailable; durable intent retained',flush=True)
        time.sleep(5)
