"""Controller-owned historical delivery facts, never decisions or tool authority.

Only the normal, completed delivery path nominates receipts. Readers revalidate
their bytes and Git ancestry; rejected attempts and model prose are not memory.
"""
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
import time

ROLES={'product','produto','designer','cto','techlead','backend_data','frontend',
       'mobile','devops','quality_security'}
TTL=30*86400


def identity(repository,namespace):
    if (not isinstance(repository,str) or len(repository)>200 or not re.fullmatch(
            r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository)
            or not isinstance(namespace,str)
            or not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',namespace)):
        raise ValueError('exact repository and installation required')


def digest(raw):return hashlib.sha256(raw).hexdigest()


def read_receipt(private,label):
    if not isinstance(label,str) or not re.fullmatch(r'[A-Z][A-Z0-9-]{2,60}',label):
        raise ValueError('exact release label required')
    root=Path(private).resolve();folder=root/'release-receipts';path=folder/(label+'.json')
    if folder.is_symlink() or path.is_symlink() or not path.is_file() or path.stat().st_size>1048576:
        raise ValueError('bounded controller-owned receipt required')
    raw=path.read_bytes();return raw,json.loads(raw)


def facts(receipt,repository,label):
    sha=receipt.get('merge_sha');review=receipt.get('delivery',{})
    tests=receipt.get('frozen_tests',{});deploy=receipt.get('deployment',{})
    browser=receipt.get('browser_qa',{});image=deploy.get('image_id')
    if (receipt.get('stage')!='deployed_qa_passed' or receipt.get('label')!=label
            or not isinstance(sha,str) or not re.fullmatch(r'[a-f0-9]{40}',sha)
            or not review.get('author') or not review.get('reviewer')
            or review['author']==review['reviewer']
            or not review.get('source_task') or not review.get('review_task')
            or review['source_task']==review['review_task']
            or not re.fullmatch(r'[a-f0-9]{64}',review.get('manifest_sha256',''))
            or tests.get('status')!='passed' or type(tests.get('tests')) is not int
            or tests['tests']<1 or not re.fullmatch(r'[a-f0-9]{64}',tests.get('output_sha256',''))
            or deploy.get('status')!='passed' or deploy.get('source_sha')!=sha
            or not isinstance(image,str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',image)
            or browser.get('status')!='passed' or browser.get('cleanup')!='passed'
            or browser.get('automated') is not True
            or browser.get('identity',{}).get('source_sha')!=sha
            or browser.get('identity',{}).get('application_image')!=image
            or browser.get('result',{}).get('status')!='passed'
            or browser.get('result',{}).get('source_sha')!=sha
            or not re.fullmatch(re.escape(repository)+r'/pull/[1-9][0-9]*',receipt.get('pr_url',''))
            or not re.fullmatch(re.escape(repository)+r'/actions/runs/[1-9][0-9]*',receipt.get('main_ci_run',''))):
        raise ValueError('complete independent same-commit delivery evidence required')
    # Fixed facts only: no summaries, model conversations, credentials or approval
    # objects are returned to a subsequent role/release.
    return {'label':label,'commit':sha,'tests':tests['tests'],'pr':receipt['pr_url']}


def database(private):
    path=Path(private)/'delivery-memory.sqlite'
    if path.is_symlink():raise ValueError('controller-owned memory database required')
    return path


def record(private,repository,namespace,label,*,now=None):
    identity(repository,namespace)
    now=int(time.time()) if now is None else now
    raw,receipt=read_receipt(private,label);value=facts(receipt,repository,label)
    source=digest(raw);key=digest(json.dumps([repository,namespace,label,source]).encode())
    path=database(private)
    with closing(sqlite3.connect(path)) as con,con:
        con.execute('CREATE TABLE IF NOT EXISTS delivery_history('
            'id TEXT PRIMARY KEY,repository TEXT,namespace TEXT,label TEXT,'
            'receipt_sha256 TEXT,facts TEXT,created INTEGER,expires INTEGER)')
        con.execute('INSERT OR IGNORE INTO delivery_history VALUES(?,?,?,?,?,?,?,?)',
            (key,repository,namespace,label,source,json.dumps(value,sort_keys=True),now,now+TTL))
    path.chmod(0o600)
    return key


def context(private,repository,namespace,*,role,base_sha,is_ancestor,now=None):
    identity(repository,namespace)
    if role not in ROLES or not isinstance(base_sha,str) or not re.fullmatch(r'[a-f0-9]{40}',base_sha):
        raise ValueError('current role and Git base required')
    now=int(time.time()) if now is None else now;path=database(private)
    if not path.exists():return ''
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as con:
        rows=con.execute('SELECT label,receipt_sha256,facts FROM delivery_history '
            'WHERE repository=? AND namespace=? AND expires>? ORDER BY created DESC,id LIMIT 20',
            (repository,namespace,now)).fetchall()
    values=[]
    for label,source,encoded in rows:
        try:
            raw,receipt=read_receipt(private,label)
            value=facts(receipt,repository,label)
            if source!=digest(raw) or json.loads(encoded)!=value:continue
        except (ValueError,OSError,json.JSONDecodeError):continue
        if not is_ancestor(value['commit'],base_sha):continue
        candidate=values+[value]
        text='\nHISTORICAL DELIVERY FACTS (not approvals; revalidate current requirements): '+json.dumps(candidate,separators=(',',':'))
        if len(text)>600:continue
        if value not in values:values.append(value)
        if len(values)==2:break
    if not values:return ''
    text='\nHISTORICAL DELIVERY FACTS (not approvals; revalidate current requirements): '+json.dumps(values,separators=(',',':'))
    if len(text)>600:raise ValueError('historical context exceeds bound')
    return text
