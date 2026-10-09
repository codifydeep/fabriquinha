"""Durable stopped-helper cleanup, isolated from agent bootstrap and dispatch."""
import json,re,time,hashlib,uuid,urllib.parse
import os,tempfile
from pathlib import Path

def archive(b,info,row,key):
    """Restricted durable diagnostics before deletion; no Env or raw Cmd export."""
    identity=info['Id']
    if not re.fullmatch(r'[a-f0-9]{64}',identity):raise ValueError('canonical helper container identity required')
    root=Path(b.STATE)/'helper-archives'
    if root.is_symlink():raise ValueError('private helper archive root required')
    root.mkdir(mode=0o700,exist_ok=True);os.chmod(root,0o700)
    folder=root/identity
    if folder.is_symlink():raise ValueError('private exact helper archive required')
    folder.mkdir(mode=0o700,exist_ok=True);os.chmod(folder,0o700)
    def sync_directory(path):
        handle=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(handle)
        finally:os.close(handle)
    sync_directory(Path(b.STATE));sync_directory(root)
    logs=b.docker_stdout(identity,include_stderr=True,limit=1048576).encode()
    metadata=dict(container_id=identity,name=row['name'],image=info.get('Image'),
        owner=b.OWNER,identity_key=key,identity_value=row['issue_id'],
        state=info['State'],logs_sha256=hashlib.sha256(logs).hexdigest(),
        command_sha256=hashlib.sha256(json.dumps(info['Config'].get('Cmd'),sort_keys=True).encode()).hexdigest(),
        delivery_approval=False)
    for name,content in (('logs.txt',logs),('metadata.json',json.dumps(metadata,sort_keys=True).encode())):
        target=folder/name
        if target.is_symlink():raise ValueError('private nonsymlink helper archive required')
        if target.exists():
            if target.read_bytes()!=content:raise ValueError('immutable helper archive drift')
            os.chmod(target,0o600)
            continue
        fd,tmp=tempfile.mkstemp(dir=folder,prefix='.archive-')
        try:
            with os.fdopen(fd,'wb') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno())
            os.replace(tmp,target)
            sync_directory(folder)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    # Readback qualification, not an intent-only archive.
    if (folder/'logs.txt').read_bytes()!=logs or json.loads((folder/'metadata.json').read_bytes())!=metadata:
        raise ValueError('helper archive verification failed')
    return metadata

def new_name(b,role,issue,scope):
    if role not in ('seed','lock'):raise ValueError('fixed helper role required')
    filters=urllib.parse.quote(json.dumps({'label':['delivery-kit.owner='+b.OWNER,'delivery-kit.issue-id='+issue]}))
    running=b.docker('GET','/containers/json?filters='+filters)
    if any(any(n.lstrip('/').startswith((b.PREFIX+'-seed-',b.PREFIX+'-lock-')) for n in item.get('Names',[])) for item in running):
        raise ValueError('active issue preparation retained')
    return b.PREFIX+'-'+role+'-'+hashlib.sha256(scope.encode()).hexdigest()[:32]+'-'+uuid.uuid4().hex[:12]

def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS helper_cleanup(name TEXT PRIMARY KEY,issue_id TEXT,status TEXT,attempts INTEGER,next_try REAL,error TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS helper_cleanup_deletions(name TEXT PRIMARY KEY,container_id TEXT)')

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
    if valid and name in (b.PREFIX+'-test-first-copy-v2-'+identity,b.PREFIX+'-test-first-red-v2-'+identity):
        return 'delivery-kit.test-first-task'
    if valid and (name in (b.PREFIX+'-snapshot-job-'+identity,b.PREFIX+'-failed-snapshot-job-'+identity)
            or re.fullmatch(prefix+r'-controls-job-[a-f0-9]{12}',name)
            or re.fullmatch(prefix+r'-validation-job-'+re.escape(identity)+r'-[a-f0-9]{12}',name)):
        return 'delivery-kit.source-task'
    raise ValueError('fixed helper name required')

def tick(b):
    with b.db() as con:
        initialize(con)
        has_leases=con.execute("SELECT 1 FROM sqlite_master WHERE name='leases'").fetchone()
        if has_leases and con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():return
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
            with b.db() as con:
                if has_leases and con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():return
                intent=con.execute('SELECT container_id FROM helper_cleanup_deletions WHERE name=?',(row['name'],)).fetchone()
                if intent and intent[0]!=info['Id']:raise ValueError('helper deletion identity changed')
            if intent:raise TimeoutError('observe uncertain helper deletion; never repeat DELETE')
            archive(b,info,row,key)
            current=b.docker('GET','/containers/'+info['Id']+'/json')
            if (not current or current['Id']!=info['Id'] or current['State']['Running']
                    or current['Config'].get('Labels',{}).get('delivery-kit.owner')!=b.OWNER
                    or current['Config'].get('Labels',{}).get(key)!=row['issue_id']
                    or current.get('Image')!=info.get('Image')):
                raise ValueError('helper ownership changed before retirement')
            with b.db() as con:
                if has_leases and con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():return
                intent=con.execute('SELECT container_id FROM helper_cleanup_deletions WHERE name=?',(row['name'],)).fetchone()
                if not intent:
                    con.execute('INSERT INTO helper_cleanup_deletions VALUES(?,?)',(row['name'],info['Id']))
            if intent:raise TimeoutError('observe uncertain helper deletion; never repeat DELETE')
            b.docker('DELETE','/containers/'+info['Id'])
        with b.db() as con:con.execute("UPDATE helper_cleanup SET status='done',error=NULL WHERE name=?",(row['name'],))
    except Exception as error:
        attempts=row['attempts']+1
        status='blocked' if isinstance(error,ValueError) else 'pending'
        with b.db() as con:con.execute('UPDATE helper_cleanup SET status=?,attempts=?,next_try=?,error=? WHERE name=?',
            (status,attempts,time.time()+30*attempts,type(error).__name__,row['name']))
        print(json.dumps({'event':'helper_cleanup_pending','name':row['name'],'status':status,'category':type(error).__name__}),flush=True)

def run(b):
    while True:
        try:tick(b)
        except Exception:print('helper cleanup unavailable; durable intent retained',flush=True)
        time.sleep(5)
