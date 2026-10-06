"""Derive planning completion from exact native handoff/approval receipts."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import re


def evaluate(conn, configuration):
    cards={tid: card for tid, card in configuration.get('cards',{}).items() if card.get('scope') != 'pr_review' and not card.get('superseded_by')}
    if not cards: return dict(state='NAO_CONFIGURADO',approved=0,total=0,receipts=[])
    receipts=[]; pending=[]
    for tid,card in cards.items():
        task=conn.execute('SELECT status FROM tasks WHERE id=?',(tid,)).fetchone()
        runs=conn.execute('SELECT id,metadata FROM task_runs WHERE task_id=? ORDER BY id DESC',(tid,)).fetchall()
        delivery=None; approval=None; approval_run=None
        for run in runs:
            meta=json.loads(run['metadata'] or '{}')
            if delivery is None: delivery=meta.get('immutable_delivery')
            if approval is None and meta.get('immutable_review'):
                approval=meta['immutable_review']; approval_run=run['id']
        valid=bool(task and task['status']=='done' and delivery and approval and not card.get('review_invalidated_reason')
            and approval.get('approved') is True and approval.get('revision')==delivery.get('revision')
            and approval.get('review_run')==approval_run
            and approval.get('author')==delivery.get('author')==card['author']
            and approval.get('reviewer')==delivery.get('reviewer')==card['reviewer']
            and card['author']!=card['reviewer'])
        if valid:
            receipts.append(dict(task=tid,revision=approval['revision'],review_run=approval_run,
                author=card['author'],reviewer=card['reviewer']))
        else: pending.append(tid)
    return dict(state='CONCLUIDO' if not pending else 'EM_ANDAMENTO',approved=len(receipts),total=len(cards),
                receipts=receipts,pending=pending)


def derive(execution, conn, configuration):
    result=evaluate(conn,configuration)
    update=dict(execution,planning_status=result)
    if result['state']=='CONCLUIDO' and execution.get('phase')=='PLANEJAMENTO_DOCUMENTAL_ATIVO':
        update.update(phase='PLANEJAMENTO_CONCLUIDO_AGUARDANDO_INTEGRACAO',
            next_action='Publish reviewed documents by PR; validate worktree/PR execution before coding.')
    elif result['state']!='CONCLUIDO' and execution.get('phase')=='PLANEJAMENTO_CONCLUIDO_AGUARDANDO_INTEGRACAO':
        update.update(phase='PLANEJAMENTO_DOCUMENTAL_ATIVO',next_action='Resolve pending planning reviews.')
    review_cards={tid:dict(card,scope='assessment_status') for tid,card in configuration.get('cards',{}).items()
                  if card.get('scope')=='pr_review'}
    if review_cards:
        review=evaluate(conn,dict(cards=review_cards))
        update['pr_review_status']=review
        if review['state']=='CONCLUIDO' and execution.get('phase')=='REVISAO_PR_EM_ANDAMENTO':
            update.update(phase='PARECER_PR_CONCLUIDO_AGUARDANDO_CONFERENCIA',
                next_action='Ler decisão e achados do parecer aprovado; reconferir SHA/base/CI remotos antes de publicar ou integrar. Sem merge automático.')
        elif review['state']!='CONCLUIDO' and execution.get('phase')=='PARECER_PR_CONCLUIDO_AGUARDANDO_CONFERENCIA':
            update.update(phase='REVISAO_PR_EM_ANDAMENTO',next_action='Resolver revisão pendente do parecer do PR.')
    integrations=[]
    for approved in update.get('pr_review_status',{}).get('receipts',[]):
        card=configuration['cards'][approved['task']]
        if not card.get('integration_action'): continue
        row=conn.execute('SELECT metadata FROM task_runs WHERE id=?',(approved['review_run'],)).fetchone()
        review=json.loads(row['metadata'] or '{}').get('immutable_review',{})
        receipt=review.get('integration',{})
        if (receipt.get('merged') is True and receipt.get('task')==approved['task']
            and receipt.get('revision')==approved['revision'] and receipt.get('review_run')==approved['review_run']
            and receipt.get('pr')==card.get('pr_number') and receipt.get('head')==card.get('head_sha')
            and receipt.get('base')==card.get('base_sha') and re.fullmatch(r'[0-9a-f]{40}',receipt.get('merge_commit',''))):
            integrations.append(receipt)
    update['publication_integrations']=integrations
    if integrations and update.get('phase')=='REVISAO_PR_EM_ANDAMENTO':
        update['next_action']='Fundação integrada com recibo. Concluir revisão do PR de planejamento no novo SHA/base/CI; implementação continua bloqueada.'
    elif update.get('phase')=='PARECER_PR_CONCLUIDO_AGUARDANDO_CONFERENCIA':
        update['next_action']='Pareceres concluídos. Conferir achados e preparar integração controlada do PR pendente; não repetir revisão concluída.'
    if ({14,19} <= {r['pr'] for r in integrations}
        and update.get('pr_review_status',{}).get('state')=='CONCLUIDO'
        and len(integrations)==update['pr_review_status']['total']
        and update.get('phase') in ('REVISAO_PR_EM_ANDAMENTO','PARECER_PR_CONCLUIDO_AGUARDANDO_CONFERENCIA')):
        update.update(phase='PLANEJAMENTO_INTEGRADO_AGUARDANDO_GATE_PRODUTO',next_action='Fundação e planejamento integrados com recibos. Tratar achados registrados, verificar aprovação real do brief e validar grafo antes de liberar implementação.')
    return update


def reconcile(execution_path):
    path=Path(execution_path)
    if not path.exists(): return False
    raw=path.read_bytes(); state=json.loads(raw)
    board=Path('/opt/data/kanban/boards')/state['board']; config=board/'planning.json'
    if not config.exists() or (board/'MAINTENANCE').exists(): return False
    configuration=json.loads(config.read_text())
    if configuration['attempt']!=state['attempt']: raise ValueError('planning attempt mismatch')
    with sqlite3.connect((board/'kanban.db').as_uri()+'?mode=ro',uri=True) as conn:
        conn.row_factory=sqlite3.Row
        updated=derive(state,conn,configuration)
    if updated==state: return False
    owner=path.stat()
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False) as output:
        temporary=Path(output.name)
        json.dump(updated,output,ensure_ascii=False,indent=2); output.write('\n'); output.flush(); os.fsync(output.fileno())
    try:
        temporary.chmod(owner.st_mode & 0o777)
        if os.geteuid()==0: os.chown(temporary,owner.st_uid,owner.st_gid)
        if path.read_bytes()!=raw: return False
        temporary.replace(path)
    finally: temporary.unlink(missing_ok=True)
    return True
