"""Append-only successor storage; old review tables stay intact/readable.

This module selects records only. It cannot register a recovery, mint a grant,
dispatch an agent, reinterpret a verdict or approve a snapshot.
"""
TABLES={
    'admission':('quality_review_admissions','quality_review_attempts','quality_review_successor_admissions'),
    'attestation':('quality_review_attestations','quality_review_attempt_attestations','quality_review_successor_attestations'),
}
FIELDS={'admission':'context,context_sha256','attestation':'identity,receipt,identity_sha256,receipt_sha256'}


def require(value):
    if not value:raise ValueError('exact versioned review history required')


def exists(con,table):
    return bool(con.execute('SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone())


def initialize(con):
    # Only called by a controller-owned changed-condition transaction. Never
    # migrate old read-only evidence while inspecting it.
    con.execute('CREATE TABLE IF NOT EXISTS quality_review_successor_admissions('
        'source_task TEXT,task_id TEXT UNIQUE,request_id TEXT PRIMARY KEY,context TEXT,context_sha256 TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS quality_review_successor_attestations('
        'source_task TEXT,request_id TEXT UNIQUE,identity TEXT,receipt TEXT,identity_sha256 TEXT,receipt_sha256 TEXT,'
        'PRIMARY KEY(source_task,request_id))')
    con.execute('CREATE TABLE IF NOT EXISTS quality_review_successor_windows('
        'source_task TEXT,request_id TEXT,identity_sha256 TEXT,state TEXT,state_sha256 TEXT,PRIMARY KEY(source_task,request_id))')


def rows(con,kind,*,source=None,request=None):
    require(kind in TABLES and (source is not None or request is not None))
    where=[];values=[]
    for column,value in (('source_task',source),('request_id',request)):
        if value is not None:where.append(column+'=?');values.append(value)
    result=[]
    for table in TABLES[kind]:
        if exists(con,table):result.extend(con.execute('SELECT '+FIELDS[kind]+' FROM '+table+' WHERE '+' AND '.join(where),values).fetchall())
    return result


def successor(con,source,request):
    return bool(exists(con,'quality_review_successor_admissions') and con.execute(
        'SELECT 1 FROM quality_review_successor_admissions WHERE source_task=? AND request_id=?',(source,request)).fetchone())


def window_table(con,source,request):
    if successor(con,source,request):return 'quality_review_successor_windows'
    if exists(con,'quality_review_attempts') and con.execute(
            'SELECT 1 FROM quality_review_attempts WHERE source_task=? AND request_id=?',(source,request)).fetchone():
        return 'quality_review_attempt_windows'
    return 'quality_review_observation_windows'
