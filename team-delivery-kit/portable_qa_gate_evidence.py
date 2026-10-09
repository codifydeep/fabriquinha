"""Read-only verification of an existing approved snapshot, never new approval."""
import json
import subprocess


def verify(incident,delivery):
    from evalctl import PROJECT
    name=PROJECT+'-execution-broker-1'
    labels=json.loads(subprocess.check_output(['docker','inspect','--format',
        '{{json .Config.Labels}}',name],text=True,timeout=10))
    if (labels.get('com.docker.compose.project')!=PROJECT
            or labels.get('com.docker.compose.service')!='execution-broker'):
        raise ValueError('owned approval evidence controller required')
    program='''import broker as b,json,sys,native,read_stream_receipts
from artifact_read_evidence import observations
issue=sys.argv[1];expected=json.loads(sys.argv[2])
with b.db() as c:
 row=c.execute('SELECT r.review_task_id,r.source_task_id,r.reviewer_agent_id,r.manifest_sha256,r.status,s.volume,s.status,n.agent_id,n.issue_id FROM reviews r JOIN snapshots s ON s.task_id=r.source_task_id JOIN native_bindings n ON n.task_id=r.source_task_id WHERE r.review_task_id=?',(expected['review_task'],)).fetchone()
 wanted=(expected['review_task'],expected['source_task'],expected['reviewer'],expected['manifest_sha256'],'approved',expected['volume'],'complete',expected['author'],issue)
 if not row or tuple(row)!=wanted or expected['author']==expected['reviewer']:raise ValueError('existing exact independent approval required')
 reads=observations(read_stream_receipts.load(c,expected['review_task']))
 names=[r[0] for r in c.execute('SELECT path FROM issue_editables WHERE issue_id=?',(issue,))]
 if c.execute("SELECT 1 FROM sqlite_master WHERE name='task_contracts'").fetchone():
  revision=c.execute('SELECT r.body FROM task_contracts t JOIN contract_revisions r USING(decision_task) WHERE t.task_id=? AND r.issue_id=?',(expected['source_task'],issue)).fetchone()
  if revision:
   from portable_contract import required_files
   permitted=required_files(json.loads(revision[0]));names=[n for n in names if n.removeprefix('/workspace/') in permitted]
 if not names or any(not n.startswith('/workspace/') or '/..' in n for n in names):raise ValueError('registered historical inspection paths required')
 required={'/delivery/'+n.removeprefix('/workspace/') for n in names}
 if not required<=set(reads) or any(type(reads[p].get('lines')) is not int or reads[p]['lines']!=reads[p].get('total_lines') or reads[p]['lines']<=0 for p in required):raise ValueError('complete historical inspection required')
settings=json.loads((b.STATE/'native.json').read_text())
for task,actor in ((expected['source_task'],expected['author']),(expected['review_task'],expected['reviewer'])):
 record=native.task_record(settings,task,actor)
 if record.get('id')!=task or record.get('issue_id')!=issue or record.get('agent_id')!=actor or record.get('status')!='completed':raise ValueError('completed exact approval lineage required')
print(json.dumps(dict(operation='existing_approved_snapshot_verified_not_new_approval',issue_id=issue,delivery=expected,delivery_approval=False)))
'''
    proof=json.loads(subprocess.check_output(['docker','exec','-w','/',name,'python','-c',
        program,incident['parent_issue_id'],json.dumps(delivery,sort_keys=True)],text=True,timeout=30))
    if (proof.get('operation')!='existing_approved_snapshot_verified_not_new_approval'
            or proof.get('issue_id')!=incident['parent_issue_id']
            or proof.get('delivery')!=delivery or proof.get('delivery_approval') is not False):
        raise ValueError('historical QA approval evidence drift')
    return proof
