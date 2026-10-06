"""Offline native bootstrap: immutable successor cards, no rewritten historical receipts."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from hermes_cli import kanban_db as kb
from review_policy import REVIEWERS
from immutable_delivery import DeliveryStore

ROOT=Path('/opt/data'); PRIVATE=Path('/deliveries')
BOARD=ROOT/'kanban/boards/truco-online-r2-20260911'; CONTROL=ROOT/'governance'
SOURCE='t_b9aa58d8'
OLD={'stories':'t_10ca48e7','architecture':'t_75520b49','design':'t_97deb23b','plan':'t_83fc342c'}
OBJECTIVES={
 'design':'Corrigir o documento integral original: identificador BRIEF-TRUCO-v0.1-R1-20260916, trocar briefly por brief, português brasileiro consistente. Preservar todos os fluxos, estados, critérios LOB e acessibilidade. Não implementar código. Registrar as correções sem inventar validação de interface.',
 'architecture':'Corrigir ADR integral: em D1, referência de reconexão deve apontar D7, não D6; substituir seixo de renderização por camada/estratégia de renderização. Preservar stack, decisões, contratos API, riscos e critérios. Português brasileiro. Não alegar que CI/deploy foram executados. Revisão semântica e de referências cruzadas completa.',
 'plan':'Corrigir plano integral em português brasileiro, preservando 21 tarefas TDD-01..TDD-21 e cobertura LOB-01..07/V01-01..10. '
        'Usar somente IDs canônicos backend_data, quality_security etc., nunca aliases backend/qa. Toda tarefa deve respeitar a matriz canônica abaixo. '
        'Formato obrigatório para cada tarefa: - **TDD-XX** — título | autor → revisor | depende de: TDD-YY, TDD-ZZ ou — | verificação: critérios. '
        'Manter IDs e dependências sem ciclos e todos os critérios Red/Green/regressão, nenhum teste enfraquecido. Comparar novo design/ADR aprovados. '
        'CI por pull_request real permanece pendência técnica; workflow_dispatch verde não comprova esse evento. '
        'Não declarar produto, worktrees ou governança integrados; não criar cards de implementação. '
        'Matriz obrigatória: '+json.dumps(REVIEWERS,ensure_ascii=False)
}


def save(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def main():
    os.umask(0o077)
    state=json.loads((CONTROL/'execution.json').read_text())
    assert state['attempt']=='truco-restart-20260911'
    assert not state['product_dispatch_enabled'] and not state['implementation_dispatch_enabled']
    data=json.loads((BOARD/'planning.json').read_text())
    assert data==json.loads((PRIVATE/'planning-config.json').read_text())
    assert not state.get('planning_correction_cards'), 'already prepared; inspect instead of duplicating'
    with sqlite3.connect(BOARD/'kanban.db') as db:
        assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
        for tid in [SOURCE,*OLD.values()]:
            assert db.execute('SELECT status FROM tasks WHERE id=?',(tid,)).fetchone()[0]=='done'
    with sqlite3.connect(PRIVATE/'controller.db') as db:
        row=db.execute('SELECT revision,review_run FROM approvals WHERE task=? ORDER BY review_run DESC LIMIT 1',(SOURCE,)).fetchone()
        assert row
        validation=json.loads(db.execute('SELECT result FROM validations WHERE task=? AND revision=? AND review_run=?',(SOURCE,*row)).fetchone()[0])
        assert validation['pr_assessment']['decision']=='request_changes'
        DeliveryStore(PRIVATE).load(state['attempt'],SOURCE,row[0])
    (BOARD/'MAINTENANCE').write_text('Correction preparation; no active workers; preserve all evidence.\n')
    os.chown(BOARD/'MAINTENANCE',10000,10000)
    backup=CONTROL/('planning-corrections-backup-'+time.strftime('%Y%m%d-%H%M%S')); backup.mkdir()
    for source in (BOARD/'planning.json',PRIVATE/'planning-config.json',CONTROL/'execution.json'):
        shutil.copy2(source,backup/source.name)
    for source in (BOARD/'kanban.db',PRIVATE/'controller.db',CONTROL/'coordination.db'):
        with sqlite3.connect(source) as src,sqlite3.connect(backup/source.name) as dest:
            src.backup(dest); assert dest.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    stage=backup/'corrections-stage'; stage.mkdir()
    os.environ['HERMES_ALLOWED_KANBAN_BOARD']=stage.name
    with sqlite3.connect(BOARD/'kanban.db') as src,sqlite3.connect(stage/'kanban.db') as dest: src.backup(dest)
    db=kb.connect(stage/'kanban.db'); ids={}
    try:
        for role in ('design','architecture','plan'):
            original=data['cards'][OLD[role]]
            parents=[OLD[role],SOURCE,OLD['stories']]
            if role=='plan': parents += [ids['design'],ids['architecture']]
            tid=kb.create_task(db,title='DOC-'+role.upper()+'-R2 — Correções do PR #19',body=OBJECTIVES[role],
                assignee=original['author'],workspace_kind='scratch',initial_status='blocked',parents=parents,
                max_runtime_seconds=1200,max_retries=2,idempotency_key=state['attempt']+':pr19-corrections:'+role)
            workspace=BOARD/'workspaces'/tid; workspace.mkdir(parents=True); os.chown(workspace,10000,10000)
            db.execute('UPDATE tasks SET workspace_path=? WHERE id=?',(str(workspace),tid)); db.commit()
            data['cards'][tid]=dict(role=role,author=original['author'],reviewer=original['reviewer'],parents=parents,
                correction_gate=True,predecessor=OLD[role],review_source=SOURCE,objective=OBJECTIVES[role])
            original['superseded_by']=tid; ids[role]=tid
            kb.unblock_task(db,tid)
        with sqlite3.connect(BOARD/'kanban.db') as dest: db.backup(dest)
    finally: db.close()
    save(PRIVATE/'planning-config.json',data); save(BOARD/'planning.json',data)
    state.update(phase='CORRECOES_DOCUMENTAIS_PREPARADAS',planning_correction_cards=ids,
                 planning_corrections_backup=str(backup),next_action='Liberar correções por autores; plano depende de design/ADR corrigidos e aprovados.')
    save(CONTROL/'execution.json',state)
    for path in (BOARD/'kanban.db',BOARD/'planning.json',CONTROL/'execution.json'): os.chown(path,10000,10000)
    print(json.dumps(dict(cards=ids,backup=str(backup),implementation_allowed=False)))


if __name__=='__main__': main()
