"""Register explicit CEO scope approval, without granting execution permissions."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from coordination_store import CoordinationStore

EXPECTED='273d7760dc25b2641631a98a8d3aef352883d4a92469c145154285e9dd17d403'
root=Path('/opt/data/governance')
execution=json.loads((root/'execution.json').read_text())
assert not execution['product_dispatch_enabled']
attempt=execution['attempt']; board=execution['board']
assert attempt=='truco-restart-20260911' and board=='truco-online-r2-20260911'
brief=Path('/input/product-brief-v0.1.md').read_bytes()
assert hashlib.sha256(brief).hexdigest()==EXPECTED
proofdb=sqlite3.connect('file:/deliveries/controller.db?mode=ro',uri=True)
try:
    raw=proofdb.execute('SELECT value FROM e2e_state WHERE key=?',('rehearsal-e2e-20260916-ds1:result',)).fetchone()[0]
    proof=json.loads(raw)
    assert proof['passed'] and not proof['product_released']
    assert proof['approval']['approved'] and proof['qa']['passed'] and proof['deploy']['passed']
    assert proof['approval']['revision']==proof['qa']['commit']==proof['deploy']['commit']
finally: proofdb.close()
dest=root/'approved-briefs'/EXPECTED
dest.mkdir(parents=True,exist_ok=True)
target=dest/'brief.md'
if target.exists(): assert target.read_bytes()==brief
else: target.write_bytes(brief)
evidence=dict(brief_id='BRIEF-TRUCO-v0.1-R1-20260916',brief_sha256=EXPECTED,
    criteria=['V01-'+str(i).zfill(2) for i in range(1,11)],
    milestone_criteria=['LOB-'+str(i).zfill(2) for i in range(1,8)],
    platforms=['web'],actor='ceo',source='Codex conversation',
    message='de acordo. Prossiga',scope='approve referenced brief, then prepare product execution; no PR or tool exception approval')
store=CoordinationStore(root/'coordination.db')
try:
    current=store.db.execute('SELECT state FROM attempts WHERE id=?',(attempt,)).fetchone()[0]
    if current=='EM_DESCOBERTA':
        store.transition(attempt,current,'AGUARDANDO_APROVACAO_DO_BRIEF','produto',dict(brief_sha256=EXPECTED,brief_id=evidence['brief_id']))
        current='AGUARDANDO_APROVACAO_DO_BRIEF'
    if current=='AGUARDANDO_APROVACAO_DO_BRIEF': store.transition(attempt,current,'ATIVA','ceo',evidence)
    else: assert current=='ATIVA' and store.get(attempt,'brief','approved')==evidence
    with store.transaction(attempt):
        store._put(attempt,'technical_validation','deepseek-ds1',dict(attempt='rehearsal-e2e-20260916-ds1',receipt=proof,
            scope='isolated HTTP rehearsal; does not validate arbitrary product worktrees or planning tools'))
finally: store.close()
execution.update(rehearsal_passed=True,product_dispatch_enabled=False,phase='BRIEF_APROVADO_PREPARANDO_EXECUCAO',
    brief_sha256=EXPECTED,brief_id=evidence['brief_id'],technical_rehearsal='rehearsal-e2e-20260916-ds1',
    next_action='validate product-mode tools and independent review before dispatch')
tmp=root/'execution.pending.json'; tmp.write_text(json.dumps(execution,indent=2)); tmp.replace(root/'execution.json')
print(json.dumps(dict(approval_recorded=True,brief_sha256=EXPECTED,product_dispatch_enabled=False)))
