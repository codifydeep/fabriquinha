"""Idle-only registration on the SAME visible product board, preserving evidence."""
import hashlib,json,os,shutil,sqlite3,time
from pathlib import Path
from hermes_cli import kanban_db as kb
board=Path('/board');control=Path('/control')
number=int(os.environ.get('PR_NUMBER','22'))
packet=Path('/input/'+os.environ.get('PR_PACKET','release-base-packet.json')).read_bytes();data=json.loads(packet)
assert data['pr']==number and data['ci']['conclusion']=='success'
db=kb.connect(board/'kanban.db')
assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
cfg=json.loads((control/'config.json').read_text())
assert cfg==json.loads((board/'product-adapter.json').read_text())
assert not any(c.get('pr')==number for c in cfg['cards'].values()), 'Already registered; do not duplicate'
backup=control/(f'pr{number}-backup-'+time.strftime('%Y%m%d-%H%M%S'));backup.mkdir()
for path in (control/'config.json',board/'product-adapter.json'):shutil.copy2(path,backup/path.name)
with sqlite3.connect(backup/'kanban.db') as dest:db.backup(dest)
with sqlite3.connect(control/'controller.db') as source,sqlite3.connect(backup/'controller.db') as dest:source.backup(dest)
tid=kb.create_task(db,title=f'PR{number} — CTO independent integration review',assignee='techlead',initial_status='blocked',
    body=data.get('purpose','Review exact Git packet, preservation, scope, CI and provenance. No implementation or Red. Not homologation.'),
    max_runtime_seconds=1200,max_retries=0,idempotency_key=cfg['attempt']+f':pr{number}-review')
assert kb.unblock_task(db,tid)
claim=kb.claim_task(db,tid,claimer='operator-pr-packet-registration')
assert claim
assert kb.request_review(db,tid,reviewer='cto',expected_run_id=claim.current_run_id,
    summary='Operator-prepared frozen PR packet; no model authorship claimed. Exact-head independent CTO review required.')
cfg['cards'][tid]=dict(scope='pr_review',author='techlead',reviewer='cto',pr=number,
    packet_sha256=hashlib.sha256(packet).hexdigest(),
    brief='Review the frozen real product PR packet, not a generic rehearsal. Read product_status then product_inspect. Inspect actual code/configuration, provenance, test preservation and actual pull_request CI. Assess only the explicit sub-delivery scope; do not require complete v0.1 for a prerequisite PR. Approve or request concrete changes through product_verdict. No shell, edits, reexecution of Red, merge or deploy.')
(control/'pr-packets').mkdir(exist_ok=True)
(control/'pr-packets'/(tid+'.json')).write_bytes(packet)
for path in (control/'config.json',board/'product-adapter.json'):path.write_text(json.dumps(cfg,indent=2)+'\n')
os.chown(board/'product-adapter.json',10000,10000)
(control/f'pr{number}-registration.json').write_text(json.dumps(dict(task=tid,packet_sha256=cfg['cards'][tid]['packet_sha256'],backup=str(backup)))+'\n')
print(json.dumps(dict(task=tid,reviewer='cto',status='review',backup=str(backup))))
