"""Private draft prototype. Must be hosted by controller, never by a worker.

live_claim must read native Kanban claim provenance, not trust request fields.
Not yet registered with Hermes tool handlers; does not authorize product dispatch.
"""
import hashlib,json,re,sqlite3
from pathlib import PurePosixPath

def digest(files):
    return hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def validate_files(files):
    if not isinstance(files,dict) or not 1<=len(files)<=1000:raise ValueError('file count')
    total=0
    for name,content in files.items():
        if not isinstance(name,str) or not isinstance(content,str):raise ValueError('text files only')
        parts=PurePosixPath(name).parts
        if not parts or name!=PurePosixPath(name).as_posix() or name.startswith('/') or '\\' in name or any(p in ('.','..') or p.startswith('.') for p in parts):raise ValueError('unsafe path')
        if parts[0] not in ('src','server','web','shared','tests','docs','design','package.json','package-lock.json','tsconfig.json','tsconfig.build.json','eslint.config.mjs','README.md'):raise ValueError('unregistered path')
        if any(p in ('node_modules','credentials.json','id_rsa') for p in parts):raise ValueError('private or generated path')
        total+=len(content.encode())
    if total>1024*1024:raise ValueError('draft byte limit')

class Workspace:
    def __init__(self,db,live_claim):
        self.db=db;self.claim=live_claim
        db.execute('CREATE TABLE IF NOT EXISTS product_drafts(attempt TEXT,task TEXT,author TEXT,base TEXT,version INTEGER,files TEXT,protected TEXT,reviewer TEXT,PRIMARY KEY(attempt,task))')
        db.execute('CREATE TABLE IF NOT EXISTS product_submissions(attempt TEXT,task TEXT,run INTEGER,version INTEGER,revision TEXT,files TEXT,PRIMARY KEY(attempt,task,run,version))')
        db.commit()

    def seed(self,attempt,task,author,base,files,protected,reviewer='techlead'):
        """Operator/controller registration only; never expose this operation to agents."""
        validate_files(files)
        from product_review_policy import validate
        cards=getattr(self.claim,'cards',{})
        if validate(author,reviewer,cards.get(task) if isinstance(cards,dict) else None):raise ValueError('invalid review matrix')
        if not re.fullmatch(r'[0-9a-f]{40}',base):raise ValueError('exact base commit required')
        if not set(protected)<=files.keys():raise ValueError('unknown protected file')
        # Caller must enumerate all base tests/configuration when registering.
        if any(n.startswith('tests/') and n not in protected for n in files):raise ValueError('baseline tests must be protected')
        with self.db:
            self.db.execute('INSERT INTO product_drafts VALUES(?,?,?,?,?,?,?,?)',(attempt,task,author,base,0,json.dumps(files),json.dumps({n:files[n] for n in protected}),reviewer))

    def state(self,request,write=False):
        current=self.claim(request)
        if not current or current.get('mode') not in ('implementation','review'):raise PermissionError('active native claim required')
        for key in ('attempt','task','run','claim'):
            if current.get(key)!=request.get(key):raise PermissionError('stale or foreign claim')
        row=self.db.execute('SELECT author,base,version,files,protected,reviewer FROM product_drafts WHERE attempt=? AND task=?',(current['attempt'],current['task'])).fetchone()
        if not row:raise PermissionError('unregistered workspace')
        if write and (current['mode']!='implementation' or current.get('profile')!=row[0]):raise PermissionError('original author only')
        return current,row

    def read_draft(self,request):
        current,row=self.state(request,write=True)
        files=json.loads(row[3]);return dict(version=row[2],sha256=digest(files),files=files,base=row[1])

    def edit(self,request,expected_version,expected_sha,replacements):
        if not isinstance(replacements,dict) or not 1<=len(replacements)<=8:raise ValueError('1..8 complete text replacements')
        with self.db:
            current,row=self.state(request,write=True);files=json.loads(row[3]);protected=json.loads(row[4])
            if row[2]!=expected_version or digest(files)!=expected_sha:raise ValueError('stale draft')
            cards=getattr(self.claim,'cards',{})
            card=cards.get(current['task'],{}) if isinstance(cards,dict) else {}
            if any(n.startswith('docs/governance/') or n=='docs/product/ceo-goal-v0.1.md' for n in replacements):raise PermissionError('governance and CEO goal require the separate reviewed governance/product-scope workflow')
            if card.get('adapter')=='document':
                from product_documents import validate_replacements
                validate_replacements(replacements)
            files.update(replacements);validate_files(files)
            if any(files.get(n)!=value for n,value in protected.items()):raise PermissionError('baseline tests/config cannot be changed')
            result=self.db.execute('UPDATE product_drafts SET version=version+1,files=? WHERE attempt=? AND task=? AND version=?',
                (json.dumps(files),current['attempt'],current['task'],expected_version))
            if result.rowcount!=1:raise ValueError('concurrent draft change')
        return dict(version=expected_version+1,sha256=digest(files))

    def freeze(self,request,version):
        with self.db:
            current,row=self.state(request,write=True)
            if row[2]!=version:raise ValueError('stale submission')
            files=json.loads(row[3]);revision=digest(dict(attempt=current['attempt'],task=current['task'],run=current['run'],base=row[1],files=files))
            self.db.execute('INSERT OR IGNORE INTO product_submissions VALUES(?,?,?,?,?,?)',
                (current['attempt'],current['task'],current['run'],version,revision,row[3]))
        return dict(revision=revision,version=version,base=row[1],scope='frozen_source_only',tests_proven=False,approved=False)

    def remove_empty_artifact(self,request,version,sha,path,reason):
        if not isinstance(reason,str) or len(reason)<30:raise ValueError('artifact rationale required')
        with self.db:
            who,row=self.state(request,write=True);files=json.loads(row[3]);protected=json.loads(row[4])
            card=self.claim.cards[who['task']]
            if path not in card.get('removable_empty_artifacts',[]) or path in protected:raise PermissionError('baseline removal forbidden')
            if path not in files or files[path].strip():raise PermissionError('only proved empty new artifacts may be removed')
            if row[2]!=version or digest(files)!=sha:raise ValueError('stale draft')
            del files[path];validate_files(files)
            self.db.execute('UPDATE product_drafts SET version=version+1,files=? WHERE attempt=? AND task=?',(json.dumps(files),who['attempt'],who['task']))
        return dict(version=version+1,sha256=digest(files),removed_empty_artifact=path)

    def inspect(self,request,revision):
        current,row=self.state(request)
        if current['mode']!='review' or current.get('profile')!=row[5] or current.get('profile')==row[0]:raise PermissionError('registered independent reviewer required')
        snapshot=self.db.execute('SELECT files FROM product_submissions WHERE attempt=? AND task=? AND revision=?',
            (current['attempt'],current['task'],revision)).fetchone()
        if not snapshot:raise ValueError('unknown submission')
        return json.loads(snapshot[0])
