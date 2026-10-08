"""Controller evidence for rejected writes; never an author retry or verdict."""
import hashlib
import json
import re
import time
try:
    import handoffs, native
except ImportError:
    from broker import handoffs, native


def describe(messages, path):
    failures=[]
    for message in messages:
        if message.get('type')!='tool_result' or message.get('tool')!='patch':continue
        text=message.get('output')
        if not isinstance(text,str) or not text.startswith('patch failed for '+path+':'):continue
        match=re.search(r'ValueError: fenced write size exceeds (\d+) bytes; received at least (\d+) bytes\.',text)
        if not match or 'No bytes were changed.' not in text:continue
        limit,observed=map(int,match.groups())
        if limit!=32768 or observed!=limit+1:continue
        failures.append(hashlib.sha256(text.encode()).hexdigest())
    if len(failures)!=2:return None
    return dict(kind='fenced_patch_write_rejection',category='artifact_size',tool='patch',
        structure=dict(field='resulting_file',constraint='utf8_length',maximum_bytes=32768,
            received_at_least_bytes=32769,rejected_writes=2),
        reason='Both patches exceeded the fixed 32768-byte resulting-file limit. The write fence rejected them before writing; this is not a test failure. Preserve all methods/assertions and product/baseline bytes. A concrete tests-only remedy must fit the existing limit; no identical retry or limit increase.',
        tool_result_sha256=failures,write_executed=False,tests_executed=False,
        red_verified=False,delivery_approval=False)


def enrich(b,route,runs,source,prior,effects):
    """One new CTO diagnosis after a terminal escalation with missing evidence."""
    if not prior or prior['stage']!='test_first_blocked' or source.get('status')!='failed':return False
    data=json.loads(prior['data'])
    if (data.get('diagnostic') or data.get('error')!='test_first_cto_requires_replanning'
            or data.get('decision',{}).get('action')!='escalate_cto'
            or data.get('decision',{}).get('optional_files')!=[]
            or not route.get('enabled') or not route.get('test_first')
            or route['author']==route['cto'] or len(route['test_first_files'])!=1):return False
    issue=route['issue_id'];task=source['id']
    authors=[r for r in runs if r.get('agent_id')==route['author']]
    if (source.get('issue_id')!=issue or source.get('agent_id')!=route['author'] or not authors
            or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=task):return False
    cto=next((r for r in runs if r['id']==data.get('cto_task')),None)
    if (not cto or cto.get('status')!='completed' or cto.get('agent_id')!=route['cto']
            or cto.get('wakeup_id')!=data.get('test_first_cto_wakeup')
            or effects.decision(cto)!=data['decision']
            or any(r['status'] in ('queued','dispatched','running') for r in runs)):return False
    with b.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS fenced_patch_diagnoses(issue_id TEXT PRIMARY KEY,source_task TEXT,receipt TEXT)')
        if con.execute('SELECT 1 FROM fenced_patch_diagnoses WHERE issue_id=?',(issue,)).fetchone():return False
        binding=con.execute('SELECT n.request_id,l.status,g.mode FROM native_bindings n JOIN leases l USING(request_id) JOIN grants g USING(request_id) WHERE n.task_id=? AND n.issue_id=?',(task,issue)).fetchall()
        snapshot=con.execute('SELECT volume,status FROM failed_execution_snapshots WHERE task_id=?',(task,)).fetchone()
        if (len(binding)!=1 or binding[0]['status']!='closed' or binding[0]['mode']!='implementation'
                or not snapshot or snapshot['status']!='complete'
                or con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
                or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):return False
    volume=b.docker('GET','/volumes/'+snapshot['volume'])
    labels=(volume or {}).get('Labels',{})
    if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=task:return False
    settings=json.loads((b.STATE/'native.json').read_text())
    diagnostic=describe(native.task_messages(settings,task),'/workspace/'+route['test_first_files'][0])
    if not diagnostic:return False
    diagnostic.update(task_id=task,issue_id=issue,execution_id=binding[0]['request_id'])
    receipt=dict(operation='fenced_patch_diagnosis_v1',previous=data,diagnostic=diagnostic,
        snapshot_volume=snapshot['volume'],author_retry_authorized=False,delivery_approval=False)
    updated={**data,'diagnostic':diagnostic,'fenced_patch_diagnosis':receipt,
        'required_action':'CTO diagnose measured write limit; preserve tests and existing bounds'}
    for key in ('cto_task','decision','test_first_cto_wakeup','dispatched_at'):updated.pop(key,None)
    with b.LOCK,b.db() as con:
        current=handoffs.load(con,task)
        if not current or current['stage']!=prior['stage'] or current['data']!=prior['data']:return False
        con.execute('INSERT INTO fenced_patch_diagnoses VALUES(?,?,?)',(issue,task,json.dumps(receipt,sort_keys=True)))
        handoffs.save(con,task,issue,'technical_decision_required',route['cto'],updated,time.time())
    return True


def qualified(con,issue,source,data):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='fenced_patch_diagnoses'").fetchone():return False
    row=con.execute('SELECT source_task,receipt FROM fenced_patch_diagnoses WHERE issue_id=?',(issue,)).fetchone()
    receipt=data.get('fenced_patch_diagnosis')
    return bool(row and row[0]==source and isinstance(receipt,dict)
        and json.loads(row[1])==receipt and receipt.get('diagnostic')==data.get('diagnostic')
        and receipt.get('author_retry_authorized') is False and receipt.get('delivery_approval') is False)
