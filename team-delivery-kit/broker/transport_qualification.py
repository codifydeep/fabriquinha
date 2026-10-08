"""Bind controller-owned offline qualifications to one preserved failed task.

Unknown historical cause remains unknown. Qualification may reopen independent
diagnosis once; it never grants an author retry, Red or delivery approval.
"""
import hashlib
import json
import re
import uuid


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def private_json(path,limit):
    if path.is_symlink() or not path.is_file() or path.stat().st_mode&0o077 or path.stat().st_size>limit:
        raise ValueError('regular restricted controller evidence required')
    return json.loads(path.read_text())


def validate_probes(native,acp,worker,writer):
    for value,schema in ((native,'native-patch-probe-v1'),(acp,'fixed-acp-patch-probe-v1')):
        if (value.get('schema')!=schema or value.get('status')!='passed' or value.get('worker_image')!=worker
                or type(value.get('model_calls')) is not int or value['model_calls']!=0
                or value.get('delivery_approval') is not False or value.get('product_retry') is not False):
            raise ValueError('passed non-delivery offline evidence required')
        record=value.get('inspection',{})
        if (type(record.get('uid')) is not int or record['uid']!=10000 or record.get('writer_sha256')!=writer
                or any(record.get(k) is not True for k in ('baseline_unchanged','credentials_absent'))):
            raise ValueError('same installed isolated writer required')
    if any(native['inspection'].get(k) is not True for k in ('invalid_patch_rejected','fixed_syntax_error',
            'rejected_patch_preserved_bytes','valid_patch_success','exact_quotes_preserved')):
        raise ValueError('native negative and positive controls required')
    if (acp.get('model_authorship') is not False or acp.get('tool_protocol_valid') is not True
            or any(type(acp.get(k)) is not int or acp[k]!=v for k,v in
                {'actual_patch_calls':2,'actual_read_calls':2,'paired_patch_results':1,'syntax_rejected_patch_calls':1}.items())
            or type(acp['inspection'].get('requests')) is not int or acp['inspection']['requests']!=5
            or any(acp['inspection'].get(k) is not True for k in
                ('rejected_patch_preserved_bytes','exact_quotes_preserved'))):
        raise ValueError('actual ACP reject-correct path required')


def capture(b,issue,source):
    config_path=b.STATE/'transport-qualification.json'
    if not config_path.exists():return None
    config=private_json(config_path,8192)
    if (set(config)!={'native_probe','acp_probe','worker_image','writer_sha256'} or config['worker_image']!=b.IMAGE
            or not re.fullmatch(r'sha256:[a-f0-9]{64}',config['worker_image'])
            or not re.fullmatch(r'[a-f0-9]{64}',config['writer_sha256'])):
        raise ValueError('current installed qualification config required')
    folder=b.STATE/'synthetic-probe-evidence'
    if folder.is_symlink():raise ValueError('unsafe evidence folder')
    probes=[]
    for key in ('native_probe','acp_probe'):
        identifier=config[key]
        if not isinstance(identifier,str) or str(uuid.UUID(identifier))!=identifier:raise ValueError('probe identity required')
        archived=private_json(folder/(identifier+'.json'),8*1024*1024)
        result=archived.get('result',{})
        if result.get('execution_id')!=identifier:raise ValueError('probe binding mismatch')
        probes.append(result)
    validate_probes(*probes,b.IMAGE,config['writer_sha256'])
    with b.db() as c:
        row=c.execute('SELECT stage,data FROM delivery_handoffs WHERE source_task=? AND issue_id=?',(source,issue)).fetchone()
        if not row or row['stage']!='test_first_blocked':return None
        data=json.loads(row['data']);diagnostic=data.get('diagnostic',{})
        if (data.get('error')!='test_first_cto_requires_replanning' or data.get('decision',{}).get('action')!='escalate_cto'
                or not data.get('unchanged_seed_diagnosis_replay') or data.get('transport_qualification_replay')
                or diagnostic.get('kind')!='unchanged_seed_read_only_failure'
                or diagnostic.get('issue_id')!=issue or diagnostic.get('task_id')!=source
                or any(diagnostic.get(k) is not False for k in ('proxy_failure_cause_proven','write_executed',
                    'tests_executed','red_verified','delivery_approval'))
                or c.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
                or c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):return None
        preserved=c.execute('SELECT state FROM unchanged_seed_diagnoses WHERE source_task=?',(source,)).fetchone()
        if not preserved:return None
        state=json.loads(preserved[0])
        if state.get('stage')!='passed' or state.get('receipt')!=diagnostic:raise ValueError('same entire preserved snapshot required')
        receipt=dict(kind='qualified_transport_recovery_evidence_v1',issue_id=issue,source_task=source,
            diagnostic_sha256=digest(diagnostic),manifest_sha256=diagnostic['manifest_sha256'],
            worker_image=b.IMAGE,writer_sha256=config['writer_sha256'],config_sha256=digest(config),
            native_probe_sha256=digest(probes[0]),acp_probe_sha256=digest(probes[1]),
            historical_cause_proven=False,model_authorship=False,author_retry_authorized=False,delivery_approval=False)
        c.execute('CREATE TABLE IF NOT EXISTS transport_qualifications(source_task TEXT PRIMARY KEY,receipt TEXT)')
        old=c.execute('SELECT receipt FROM transport_qualifications WHERE source_task=?',(source,)).fetchone()
        if old and json.loads(old[0])!=receipt:raise ValueError('once-only qualification identity drift')
        if not old:c.execute('INSERT INTO transport_qualifications VALUES(?,?)',(source,json.dumps(receipt,sort_keys=True)))
        return receipt


def qualified(con,issue,source,data,worker_image=None):
    receipt=(data.get('transport_qualification_replay') or {}).get('certificate')
    if not isinstance(receipt,dict) or not worker_image or receipt.get('worker_image')!=worker_image:return False
    table=con.execute("SELECT 1 FROM sqlite_master WHERE name='transport_qualifications'").fetchone()
    if not table:return False
    row=con.execute('SELECT receipt FROM transport_qualifications WHERE source_task=?',(source,)).fetchone()
    return bool(row and json.loads(row[0])==receipt and receipt.get('issue_id')==issue
        and receipt.get('source_task')==source and receipt.get('diagnostic_sha256')==digest(data.get('diagnostic'))
        and all(receipt.get(k) is False for k in ('historical_cause_proven','model_authorship',
            'author_retry_authorized','delivery_approval')))
