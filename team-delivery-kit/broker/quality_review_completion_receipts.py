"""Preserve worker pre-stop diagnostics as advisory, NEVER review authority."""
import hashlib
import json

PREFIX='QUALITY_REVIEW_COMPLETION_ATTEMPT_V1:'


def store(con,binding,notifications):
    if not binding:return
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='quality_native_scopes'").fetchone():return
    if not con.execute("SELECT 1 FROM quality_native_scopes WHERE request_id=? AND task_id=? AND phase='test_review_v2'",
            (binding['request_id'],binding['task_id'])).fetchone():return
    con.execute('CREATE TABLE IF NOT EXISTS quality_review_completion_receipts('
        'request_id TEXT,task_id TEXT,sha256 TEXT,receipt TEXT,PRIMARY KEY(request_id,sha256))')
    for frame in notifications:
        update=(frame.get('params') or {}).get('update') or {}
        content=update.get('content') or {}
        if frame.get('method')!='session/update' or update.get('sessionUpdate')!='agent_thought_chunk':continue
        text=content.get('text') if isinstance(content,dict) else None
        if not isinstance(text,str) or not text.startswith(PREFIX) or len(text.encode())>65536:continue
        raw=text[len(PREFIX):]
        try:value=json.loads(raw)
        except ValueError:continue
        if not isinstance(value,dict) or set(value)!={'candidate','candidate_sha256','diagnostic'}:continue
        if not isinstance(value['candidate'],str) or not isinstance(value['diagnostic'],dict):continue
        receipt=dict(operation='observed_worker_review_completion_v1',request_id=binding['request_id'],
            task_id=binding['task_id'],worker_advisory=value,authoritative=False,
            tests_approved=False,delivery_approval=False)
        encoded=json.dumps(receipt,sort_keys=True);sha=hashlib.sha256(encoded.encode()).hexdigest()
        con.execute('INSERT OR IGNORE INTO quality_review_completion_receipts VALUES(?,?,?,?)',
            (binding['request_id'],binding['task_id'],sha,encoded))
