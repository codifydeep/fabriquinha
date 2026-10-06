"""Operator maintenance: preserve C8 delivery and request scoped CTO recovery."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
from coordination_store import CoordinationStore
from prepare_validation_cycle5 import cli, BOARD, CONTROL

SOURCE='t_9d901dba'
QA='t_6fe1bb24'
REVISION='47e068e89f5be0d3c4371c5df41a83f80501a610da8d864d74f7647e209bf8c7'

def main():
    os.umask(0o077)
    assert (BOARD/'MAINTENANCE').exists()
    journal=CONTROL/'cycle-8-resume.json'
    if journal.exists(): print(journal.read_text()); return
    with sqlite3.connect(BOARD/'kanban.db') as db:
        db.row_factory=sqlite3.Row
        assert not db.execute("SELECT 1 FROM tasks WHERE status='running' OR current_run_id IS NOT NULL OR worker_pid IS NOT NULL").fetchone()
        source=db.execute('SELECT * FROM tasks WHERE id=?',(SOURCE,)).fetchone()
        assert source['status']=='blocked' and source['assignee']=='techlead'
        from review_block_event import review_block_event
        assert review_block_event(db,SOURCE)['id']==1605
    diagnostic=json.loads(cli('create','INCIDENT-'+SOURCE+' — C8 retomada persistente da revisão',
        '--assignee','cto','--initial-status','blocked','--workspace','scratch','--priority','100000',
        '--max-runtime','15m','--max-retries','2','--idempotency-key','rehearsal-c8-persistent-resume','--json',
        '--body','O guard de encerramento e a recuperação após timeout foram corrigidos e testados. '
        'Use review_diagnose; se can_resume=true, use review_resume com revision e block_event retornados. '
        'A entrega corrigida está preservada; não reimplemente, não aprove, não peça decisão técnica ao CEO. '
        'A retomada deve estacionar este incidente até a revisão e QA comprovarem a entrega. '
        'Se can_resume=false, registre a divergência concreta e bloqueie sem repetir a mesma tentativa.'))
    for task in ('t_386e3ab3','t_68033728'):
        with sqlite3.connect(BOARD/'kanban.db') as db:
            archived=db.execute('SELECT status FROM tasks WHERE id=?',(task,)).fetchone()[0]=='archived'
        if not archived:
            cli('comment',task,'Diagnóstico C8 preservado e substituído por '+diagnostic['id']+'. Correção do controlador não representa aprovação ou resolução do incidente.')
            cli('archive',task)
    store=CoordinationStore(CONTROL/'coordination.db')
    try:
        with store.transaction(BOARD.name):
            for row in store.db.execute("SELECT id,data FROM records WHERE attempt=? AND kind='incident'",(BOARD.name,)).fetchall():
                record=json.loads(row['data'])
                if record.get('task')!=SOURCE or record['status'] in ('resolved','superseded'): continue
                if record.get('native_task')!=diagnostic['id']:
                    record.setdefault('previous_diagnoses',[]).append(record.get('native_task'))
                record.update(native_task=diagnostic['id'],owner='cto',status='open',stage='diagnosis',progress_at=int(time.time()),cycle=8)
                for key in ('spike','spike_consumed','spike_failed_notice','attention_notice','runtime_notice','decision_overdue_notice'):
                    if key in record: record.setdefault('before_c8_resume',{})[key]=record.pop(key)
                store._put(BOARD.name,'incident',row['id'],record)
        state_path=CONTROL/'execution.json'; state=json.loads(state_path.read_text())
        state['phase']='ENSAIO_8_RETOMADA_PERSISTENTE'
        state_path.write_text(json.dumps(state,indent=2))
        store.enqueue(BOARD.name,'operator:c8-preserved-recovery',json.dumps(dict(profile='techlead',chat_id=state['telegram_chat_id'],text=
            '🧪 C8: retomada da entrega preservada. CTO '+diagnostic['id']+' → revisão '+SOURCE+' → QA '+QA+'. '
            'Correções: encerramento por estado persistente e recuperação de timeout. Não é aprovação; Truco continua bloqueado.')))
    finally: store.close()
    cli('comment',SOURCE,'C8: entrega '+REVISION+' preservada. Recuperação pelo CTO '+diagnostic['id']+'; nenhuma aprovação concedida pelo operador.')
    with sqlite3.connect(BOARD/'kanban.db') as db:
        status=db.execute('SELECT status FROM tasks WHERE id=?',(diagnostic['id'],)).fetchone()[0]
    if status not in ('todo','ready'):
        try:
            cli('unblock',diagnostic['id'])
        except subprocess.CalledProcessError:
            # The CLI can report failure after promotion. Durable state, not
            # process return code alone, determines whether retry is needed.
            with sqlite3.connect(BOARD/'kanban.db') as db:
                actual=db.execute('SELECT status FROM tasks WHERE id=?',(diagnostic['id'],)).fetchone()[0]
            if actual not in ('todo','ready'): raise
    journal.write_text(json.dumps(dict(cycle=8,recovery=diagnostic['id'],tdd=SOURCE,qa=QA,revision=REVISION,approved=False),indent=2))
    for path in (journal,state_path): os.chown(path,10000,10000)
    print(journal.read_text())

if __name__=='__main__': main()
