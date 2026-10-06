"""Operator-only envelope qualification: no native task or workflow verdict.

Run on the isolated controller with explicit source and failed task identities.
One call per invocation; response bytes are discarded and only hashes/status are
persisted. Proxy receipts provide sanitized shape/schema metrics for rejections.
"""
import argparse
import hashlib
import json
import time
import urllib.request
import urllib.error
import uuid
import broker as b
import handoffs
import handoff_runtime
from model_policy import MODEL,PLACEHOLDER_KEY,execution_base_url

parser=argparse.ArgumentParser()
parser.add_argument('--source-task',required=True)
parser.add_argument('--failed-task',required=True)
parser.add_argument('--mode',choices=('stream','nonstream'),required=True)
parser.add_argument('--payload',choices=('synthetic','real-authorized'),default='synthetic')
parser.add_argument('--context',choices=('compact','synthetic-wrapper','synthetic-wrapper-v2'),default='compact')
args=parser.parse_args()
settings=json.loads((b.STATE/'native.json').read_text())
remaining=handoff_runtime.Effects(b,settings).remaining_calls()
if remaining<2:raise ValueError('at least two authorized calls required')
execution=str(uuid.uuid4())
with b.LOCK,b.db() as con:
    if con.execute("SELECT count(*) FROM leases WHERE status IN ('running','creating')").fetchone()[0]:
        raise ValueError('qualification requires idle workers')
    row=handoffs.load(con,args.source_task)
    data=json.loads(row['data'])
    if (row['stage']!='technical_decision_required'
            or data.get('recipient_task')!=args.failed_task
            or not data.get('unchanged_diagnosis_retry')
            or data.get('evidence',{}).get('correction_diagnosis',{}).get('category')!='unchanged_rejected_delivery'):
        raise ValueError('exact blocked unchanged-correction diagnosis required')
    con.execute('CREATE TABLE IF NOT EXISTS typed_envelope_qualifications('
        'execution_id TEXT PRIMARY KEY,source_task TEXT,failed_task TEXT,mode TEXT,receipt TEXT)')
    payload='wholly_synthetic' if args.payload=='synthetic' else 'authorized_real_diagnosis'
    attempts=con.execute('SELECT receipt FROM typed_envelope_qualifications WHERE failed_task=? AND mode=?',
                         (args.failed_task,args.mode)).fetchall()
    if any(json.loads(r[0]).get('payload')==payload and
           json.loads(r[0]).get('context','compact')==args.context for r in attempts):
        raise ValueError('qualification treatment already attempted; no identical retry')
    # Default external payload is wholly synthetic. Explicit real-authorized
    # mode is operator-only and requires approval to transmit findings/metadata.
    # Neither mode transmits credentials or accepts a real workflow decision.
    synthetic=dict(evidence=dict(tests=3,correction_diagnosis=dict(
        category='unchanged_rejected_delivery',previous_source='synthetic-before',
        source_task='synthetic-after',review_task='synthetic-review',
        manifest_sha256='a'*64,finding='Synthetic review asks for an example but gives no concrete defect.')))
    instruction=handoffs.unchanged_correction_instruction(synthetic if args.payload=='synthetic' else data)
    if args.context in ('synthetic-wrapper','synthetic-wrapper-v2'):
        # Control for generic wrapper wording only. No real title, description,
        # ambient history, SOUL, session messages or task result is transmitted.
        issue=dict(id=row['issue_id'],title='Synthetic diagnostic transport qualification',
                   description='Three synthetic tests pass. This is a protocol experiment, not a product work request.')
        note=('DELIVERY_HANDOFF '+'0'*64+'\n'+instruction) if args.context=='synthetic-wrapper-v2' else instruction
        task=dict(handoff_note=note)
        frame=dict(method='session/prompt',params=dict(prompt=[]))
        instruction=b.native_task_prompt(frame,'planning',issue,task)['params']['prompt'][0]['text']
    receipt=dict(operation='isolated_typed_envelope_qualification_v1',execution_id=execution,
        mode=args.mode,status='pending',model=MODEL,workflow_decision_accepted=False,
        worker_tool_executed=False,delivery_approval=False,started_at=time.time(),
        instruction_sha256=hashlib.sha256(instruction.encode()).hexdigest(),payload=payload,context=args.context)
    con.execute('INSERT INTO typed_envelope_qualifications VALUES(?,?,?,?,?)',
        (execution,args.source_task,args.failed_task,args.mode,json.dumps(receipt,sort_keys=True)))

body=dict(model=MODEL,stream=args.mode=='stream',max_tokens=1200,
          messages=[dict(role='user',content=instruction)])
request=urllib.request.Request(execution_base_url(execution)+'/chat/completions',
    data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+PLACEHOLDER_KEY,
                                          'Content-Type':'application/json'},method='POST')
try:
    try:
        with urllib.request.urlopen(request,timeout=130) as response:
            status=response.status;output=response.read(4*1024*1024+1)
    except urllib.error.HTTPError as error:
        status=error.code;output=error.read(4096)
    if len(output)>4*1024*1024:raise ValueError('bounded qualification response required')
    receipt.update(status='finished',http_status=status,response_sha256=hashlib.sha256(output).hexdigest())
except Exception as error:
    receipt.update(status='failed',error_type=type(error).__name__)
finally:
    receipt['finished_at']=time.time()
    with b.db() as con:
        con.execute('UPDATE typed_envelope_qualifications SET receipt=? WHERE execution_id=?',
                    (json.dumps(receipt,sort_keys=True),execution))
print(json.dumps({k:receipt[k] for k in ('execution_id','mode','status','http_status') if k in receipt}))
