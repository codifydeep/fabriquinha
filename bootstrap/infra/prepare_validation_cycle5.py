"""Operator-only: preserve C4, exercise controlled recovery of its snapshot."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
from coordination_store import CoordinationStore

BOARD=Path('/opt/data/kanban/boards/rehearsal-20260912')
CONTROL=Path('/opt/data/governance/rehearsal')
SOURCE='t_da45e914'
QA='t_aede5ec8'
OLD=('t_aa48b097','t_b9b508e5')

def cli(*args):
    return subprocess.check_output(['/opt/hermes/.venv/bin/hermes','kanban','--board',BOARD.name,*args],text=True)

def main():
    os.umask(0o077)
    assert (BOARD/'MAINTENANCE').exists()
    journal=CONTROL/'cycle-5-cards.json'
    if journal.exists(): print(journal.read_text()); return
    with sqlite3.connect(BOARD/'kanban.db') as db:
        assert not db.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone()
        assert db.execute('SELECT status,assignee FROM tasks WHERE id=?',(SOURCE,)).fetchone()==('blocked','techlead')
    for task in OLD:
        cli('comment',task,'Ciclo 4 não aprovado; diagnóstico preservado e substituído pelo ensaio C5 de retomada controlada. Não representa resolução ou entrega.')
        cli('archive',task)
    diagnostic=json.loads(cli('create','INCIDENT-'+SOURCE+' — C5 recuperação da revisão congelada',
        '--assignee','cto','--initial-status','blocked','--workspace','scratch','--priority','100000',
        '--max-runtime','15m','--max-retries','2','--idempotency-key','rehearsal-c5-recovery','--json',
        '--body','Ciclo 5: o catálogo de ferramentas de revisão foi corrigido. Use review_diagnose; se can_resume=true, use review_resume com revision e block_event exatos. A operação retoma a revisão e estaciona este diagnóstico, sem aprovar a entrega. Não repita implementação, não peça decisão técnica ao CEO. Se houver divergência real, registre-a e bloqueie como capability.'))
    store=CoordinationStore(CONTROL/'coordination.db')
    try:
        with store.transaction(BOARD.name):
            for row in store.db.execute("SELECT id,data FROM records WHERE attempt=? AND kind='incident'",(BOARD.name,)).fetchall():
                record=json.loads(row['data'])
                if record.get('task')!=SOURCE or record['status'] in ('resolved','superseded'): continue
                record.setdefault('previous_diagnoses',[]).append(record.get('native_task'))
                record.update(native_task=diagnostic['id'],owner='cto',status='open',stage='diagnosis',progress_at=int(time.time()),cycle=5)
                for key in ('spike','spike_consumed','spike_failed_notice','attention_notice','runtime_notice','decision_overdue_notice'):
                    if key in record: record.setdefault('cycle4_history',{})[key]=record.pop(key)
                store._put(BOARD.name,'incident',row['id'],record)
    finally: store.close()
    cli('comment',SOURCE,'C5 retoma a revisão do snapshot preservado do ciclo 4 após correção do catálogo. CTO deve validar e retomar pela operação controlada; não é aprovação, nova implementação ou decisão do CEO.')
    journal.write_text(json.dumps(dict(cycle=5,recovery=diagnostic['id'],tdd=SOURCE,qa=QA,
        baseline_revision='2c9496c6ea955e850429eb52c47198c0b7e75fa507eafe27b11f7426d432ac0c',
        previous_cycle_approved=False),indent=2))
    state_path=CONTROL/'execution.json'; state=json.loads(state_path.read_text())
    state['phase']='ENSAIO_5_CATALOGO_RECUPERACAO'; state_path.write_text(json.dumps(state,indent=2))
    for path in (journal,state_path): os.chown(path,10000,10000)
    cli('unblock',diagnostic['id'])
    print(journal.read_text())

if __name__=='__main__': main()
