"""Controller-only independently curated recommendations, never tool authority.

Proofs must come from the native read-only adapter, not agent-supplied claims.
No worker endpoint, filesystem capability or delivery approval is provided here.
"""
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from contextlib import closing
from delivery_memory import identity,digest


def text(value,limit):
    if (not isinstance(value,str) or not value.strip() or len(value)>limit
            or re.search(r'(?i)(authorization\s*:|bearer\s+|api[_-]?key\s*[:=]|-----BEGIN .*PRIVATE KEY)',value)):
        raise ValueError('bounded non-secret memory text required')


def proof(value):
    if (not isinstance(value,dict) or set(value)!=
            {'task_id','agent_id','status','mode','lease_status','content_sha256'}
            or value['status']!='completed' or value['mode']!='planning'
            or value['lease_status']!='closed'
            or not re.fullmatch(r'[a-f0-9]{64}',value['content_sha256'])):
        raise ValueError('completed closed native planning proof required')
    for field in ('task_id','agent_id'):
        if str(uuid.UUID(value[field]))!=value[field]:raise ValueError('native UUID required')


def validate(entry,now):
    if (not isinstance(entry,dict) or set(entry)!=
            {'subject','decisions','commit','source_release','expires','supersedes'}):
        raise ValueError('exact recommendation fields required')
    text(entry['subject'],120)
    if not isinstance(entry['decisions'],list) or not 1<=len(entry['decisions'])<=8:
        raise ValueError('bounded decision list required')
    for item in entry['decisions']:text(item,300)
    if (not isinstance(entry['commit'],str) or not re.fullmatch(r'[a-f0-9]{40}',entry['commit'])
            or not isinstance(entry['source_release'],str)
            or not re.fullmatch(r'[A-Z][A-Z0-9-]{2,60}',entry['source_release'])
            or type(entry['expires']) is not int or not now<entry['expires']<=now+30*86400
            or entry['supersedes'] is not None and not re.fullmatch(r'[a-f0-9]{64}',entry['supersedes'])):
        raise ValueError('explicit bounded validity and source lineage required')


def path(private):
    target=Path(private)/'decision-memory.sqlite'
    if target.is_symlink():raise ValueError('controller-owned decision store required')
    return target


def nominate(private,repository,namespace,entry,source,*,now=None):
    identity(repository,namespace);proof(source)
    now=int(time.time()) if now is None else now;validate(entry,now)
    envelope={'repository':repository,'namespace':namespace,'entry':entry,'source':source}
    encoded=json.dumps(envelope,sort_keys=True,separators=(',',':'));key=digest(encoded.encode())
    target=path(private)
    with closing(sqlite3.connect(target)) as con,con:
        con.execute('CREATE TABLE IF NOT EXISTS recommendations('
            'id TEXT PRIMARY KEY,repository TEXT,namespace TEXT,envelope TEXT,'
            'state TEXT,review TEXT,created INTEGER,superseded_by TEXT)')
        con.execute('INSERT OR IGNORE INTO recommendations VALUES(?,?,?,?,?,NULL,?,NULL)',
            (key,repository,namespace,encoded,'proposed',now))
    target.chmod(0o600);return key


def curate(private,repository,namespace,key,answer,review,*,now=None):
    identity(repository,namespace);proof(review)
    now=int(time.time()) if now is None else now
    if (not isinstance(answer,dict) or set(answer)!={'role','decision','entry_sha256','reason'}
            or answer['role']!='techlead' or answer['decision'] not in ('approve','reject')
            or answer['entry_sha256']!=key):raise ValueError('exact independent memory decision required')
    text(answer['reason'],300)
    target=path(private)
    with closing(sqlite3.connect(target)) as con,con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT envelope,state,review FROM recommendations WHERE id=? AND repository=? AND namespace=?',
            (key,repository,namespace)).fetchone()
        if not row:raise ValueError('unknown scoped nomination')
        envelope=json.loads(row[0]);source=envelope['source'];entry=envelope['entry']
        if digest(row[0].encode())!=key:raise ValueError('nomination hash drift')
        validate(entry,now)
        if source['agent_id']==review['agent_id'] or source['task_id']==review['task_id']:
            raise ValueError('independent native curator required')
        result=json.dumps({'answer':answer,'proof':review},sort_keys=True,separators=(',',':'))
        if row[1]!='proposed':
            if row[2]!=result:raise ValueError('terminal curation cannot change')
            return row[1]
        state='approved' if answer['decision']=='approve' else 'rejected'
        if state=='approved' and entry['supersedes']:
            old=con.execute('SELECT envelope,state,superseded_by FROM recommendations WHERE id=? AND repository=? AND namespace=?',
                (entry['supersedes'],repository,namespace)).fetchone()
            if not old or old[1]!='approved' or old[2] or json.loads(old[0])['entry']['subject']!=entry['subject']:
                raise ValueError('current same-subject supersession required')
            con.execute('UPDATE recommendations SET superseded_by=? WHERE id=?',(key,entry['supersedes']))
        con.execute('UPDATE recommendations SET state=?,review=? WHERE id=?',(state,result,key))
    return state


def read(private,repository,namespace,*,base_sha,is_ancestor,now=None):
    identity(repository,namespace)
    if not isinstance(base_sha,str) or not re.fullmatch(r'[a-f0-9]{40}',base_sha):raise ValueError('current Git base required')
    now=int(time.time()) if now is None else now;target=path(private)
    if not target.exists():return []
    with closing(sqlite3.connect(target.resolve().as_uri()+'?mode=ro',uri=True)) as con:
        rows=con.execute('SELECT id,envelope,review FROM recommendations WHERE repository=? AND namespace=? '
            'AND state=? AND superseded_by IS NULL ORDER BY created DESC,id LIMIT 20',(repository,namespace,'approved')).fetchall()
    result=[]
    for key,encoded,review in rows:
        envelope=json.loads(encoded);entry=envelope['entry'];curation=json.loads(review)
        if entry['expires']<=now:continue
        if digest(encoded.encode())!=key:raise ValueError('recommendation hash drift')
        validate(entry,now);proof(envelope['source']);proof(curation['proof'])
        if (curation['answer']['entry_sha256']!=key or curation['answer']['decision']!='approve'
                or envelope['source']['agent_id']==curation['proof']['agent_id']):
            raise ValueError('independent approved recommendation required')
        if is_ancestor(entry['commit'],base_sha):
            result.append({'id':key,'entry':entry,'validity':'historical_recommendation_revalidate','authority':False})
        if len(result)==3:break
    return result
