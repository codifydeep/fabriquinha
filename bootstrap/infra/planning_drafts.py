"""Controller-owned, CAS-updated draft checkpoints. No paths or executable edits."""
import hashlib

def digest(content): return hashlib.sha256(content.encode()).hexdigest()

def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS planning_draft_history(id INTEGER PRIMARY KEY,task TEXT,run INTEGER,sha TEXT,content TEXT,action TEXT)')
    db.commit()

def save(db,task,run,content,action):
    if not isinstance(content,str) or not 1<=len(content.encode())<=48000: raise ValueError('draft_size: expected 1..48000 UTF-8 bytes')
    count=db.execute("SELECT count(*) FROM planning_draft_history WHERE task=? AND run=? AND action!='before'",(task,run)).fetchone()[0]
    if count>=3: raise ValueError('draft_budget: three saves used in this run; submit validated draft for independent review or block with concrete findings. Do not rewrite again.')
    old=db.execute('SELECT * FROM planning_drafts WHERE task=?',(task,)).fetchone()
    if old:
        db.execute('INSERT INTO planning_draft_history(task,run,sha,content,action) VALUES(?,?,?,?,?)',
                   (task,old['run'],digest(old['content']),old['content'],'before'))
    db.execute('INSERT OR REPLACE INTO planning_drafts VALUES(?,?,?)',(task,run,content))
    db.execute('INSERT INTO planning_draft_history(task,run,sha,content,action) VALUES(?,?,?,?,?)',
               (task,run,digest(content),content,action))
    db.commit()
    return dict(saved=True,sha256=digest(content),remaining_saves=2-count)

def edit(db,task,run,expected_sha,edits):
    row=db.execute('SELECT * FROM planning_drafts WHERE task=?',(task,)).fetchone()
    if not row or digest(row['content'])!=expected_sha: raise ValueError('stale_draft: reread current draft SHA before editing')
    if not isinstance(edits,list) or len(edits)>8: raise ValueError('patch_limit: 0..8 exact replacements required')
    content=row['content']
    for change in edits:
        if set(change)!= {'old','new'} or not all(isinstance(v,str) for v in change.values()): raise ValueError('patch_schema: old/new strings only')
        old,new=change['old'],change['new']
        if not old or content.count(old)!=1: raise ValueError('patch_match: old text must occur exactly once; nothing written')
        content=content.replace(old,new,1)
    return save(db,task,run,content,'patch' if edits else 'adopt')
