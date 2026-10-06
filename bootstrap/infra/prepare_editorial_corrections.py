"""Offline native successor cards; seed unchanged drafts, never approvals."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from hermes_cli import kanban_db as kb
from immutable_delivery import DeliveryStore
from planning_drafts import initialize, save as save_draft

BOARD=Path('/opt/data/kanban/boards/truco-online-r2-20260911')
PRIVATE=Path('/deliveries'); CONTROL=Path('/opt/data/governance')
SOURCE='t_b4bc42d2'
OLD={'stories':'t_10ca48e7','design':'t_fd99c33d'}


def save(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def main():
    os.umask(0o077)
    state=json.loads((CONTROL/'execution.json').read_text())
    data=json.loads((BOARD/'planning.json').read_text())
    assert state['attempt']==data['attempt']=='truco-restart-20260911'
    assert data==json.loads((PRIVATE/'planning-config.json').read_text())
    assert not state['product_dispatch_enabled'] and not state['implementation_dispatch_enabled']
    assert not state.get('editorial_correction_cards'), 'already prepared; inspect instead of duplicating'
    with sqlite3.connect(BOARD/'kanban.db') as db:
        assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
        for tid in [SOURCE,*OLD.values()]:
            assert db.execute('SELECT status FROM tasks WHERE id=?',(tid,)).fetchone()[0]=='done'
    (BOARD/'MAINTENANCE').write_text('Editorial successor preparation. Preserve all evidence.\n')
    os.chown(BOARD/'MAINTENANCE',10000,10000)
    backup=CONTROL/('editorial-backup-'+time.strftime('%Y%m%d-%H%M%S')); backup.mkdir()
    for source in (BOARD/'planning.json',PRIVATE/'planning-config.json',CONTROL/'execution.json'):
        shutil.copy2(source,backup/source.name)
    for source in (BOARD/'kanban.db',PRIVATE/'controller.db',CONTROL/'coordination.db'):
        with sqlite3.connect(source) as src,sqlite3.connect(backup/source.name) as dest:
            src.backup(dest); assert dest.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    proof=sqlite3.connect(PRIVATE/'controller.db'); proof.row_factory=sqlite3.Row
    initialize(proof)
    stage=backup/'editorial-stage'; stage.mkdir()
    os.environ['HERMES_ALLOWED_KANBAN_BOARD']=stage.name
    with sqlite3.connect(BOARD/'kanban.db') as src,sqlite3.connect(stage/'kanban.db') as dest: src.backup(dest)
    db=kb.connect(stage/'kanban.db'); ids={}; store=DeliveryStore(PRIVATE)
    try:
        for role,previous in OLD.items():
            original=data['cards'][previous]
            assert not original.get('superseded_by')
            row=proof.execute('SELECT revision FROM approvals WHERE task=? ORDER BY review_run DESC LIMIT 1',(previous,)).fetchone()
            assert row
            store.load(state['attempt'],previous,row['revision'])
            content=(store.path(state['attempt'],previous,row['revision'])/'files/PLAN.md').read_text()
            parents=[previous,SOURCE]
            tid=kb.create_task(db,title='DOC-'+role.upper()+' — Correção editorial mínima do PR19',
                body='Corrigir somente cabeçalho e título registrados; preservar requisitos e evidências.',
                assignee=original['author'],workspace_kind='scratch',initial_status='blocked',parents=parents,
                max_runtime_seconds=1200,max_retries=1,idempotency_key=state['attempt']+':editorial-pr19:'+role)
            edits=[]
            if role=='stories':
                edits.append(dict(old='# PLAN.md — Fatia de Lobby (LOB-01..07) — Product Planning',
                                  new='# Histórias de usuário — Fatia de Lobby (LOB-01..07)'))
            old_header='**Tarefa:** '+('t_97deb23b' if role=='design' else previous)
            edits.append(dict(old=old_header,new='**Tarefa:** '+tid))
            expected=content
            for edit in edits:
                assert expected.count(edit['old'])==1
                expected=expected.replace(edit['old'],edit['new'],1)
            objective=('Correção editorial estritamente limitada. O rascunho privado contém os bytes aprovados do predecessor, '
                'não uma nova aprovação. Leia os insumos e planning_read(view="draft"), então use planning_patch com '
                'expected_sha atual e exatamente estas substituições: '+json.dumps(edits,ensure_ascii=False)+
                '. Não reescreva o corpo, não acrescente notas nem normalize idioma. Preserve cada outro byte. '
                'Submeta ao revisor independente da matriz; revisor valida os novos cabeçalhos e conteúdo preservado. '
                'Referências históricas no corpo continuam legítimas. Sem merge ou implementação.')
            workspace=BOARD/'workspaces'/tid; workspace.mkdir(parents=True); os.chown(workspace,10000,10000)
            db.execute('UPDATE tasks SET workspace_path=?,body=? WHERE id=?',(str(workspace),objective,tid)); db.commit()
            data['cards'][tid]=dict(role=role,author=original['author'],reviewer=original['reviewer'],parents=parents,
                correction_gate=True,predecessor=previous,review_source=SOURCE,objective=objective,
                exact_content_sha256=hashlib.sha256(expected.encode()).hexdigest())
            save_draft(proof,tid,0,content,'seed_from_approved_predecessor')
            original['superseded_by']=tid; ids[role]=tid
            kb.unblock_task(db,tid)
        with sqlite3.connect(BOARD/'kanban.db') as dest: db.backup(dest)
    finally: db.close(); proof.close()
    save(PRIVATE/'planning-config.json',data); save(BOARD/'planning.json',data)
    state.update(phase='CORRECOES_EDITORIAIS_PREPARADAS',editorial_correction_cards=ids,
                 editorial_backup=str(backup),next_action='Produto/Designer corrigem somente cabeçalhos; revisão independente, nova exportação e parecer em novo SHA.')
    save(CONTROL/'execution.json',state)
    for path in (BOARD/'kanban.db',BOARD/'planning.json',CONTROL/'execution.json'): os.chown(path,10000,10000)
    print(json.dumps(dict(cards=ids,backup=str(backup),implementation_allowed=False)))


if __name__=='__main__': main()
