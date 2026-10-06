"""Deterministic team status and scoped CEO decisions for the native /kanban lane."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import time
from coordination_store import CoordinationStore

EXECUTION=Path(os.environ.get('HERMES_TEAM_EXECUTION','/opt/data/governance/execution.json'))
LEDGER=Path(os.environ.get('HERMES_COORDINATION_DB','/opt/data/governance/coordination.db'))
BOARDS=Path('/opt/data/kanban/boards')


def execution():
    data=json.loads(EXECUTION.read_text())
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*',data.get('board','')) or not data.get('attempt'):
        raise ValueError('invalid execution registry')
    return data


def status():
    data=execution()
    with sqlite3.connect(f"file:{BOARDS/data['board']/'kanban.db'}?mode=ro",uri=True) as conn:
        conn.row_factory=sqlite3.Row
        planning=BOARDS/data['board']/'planning.json'
        if planning.exists():
            from planning_status import derive
            data=derive(data,conn,json.loads(planning.read_text()))
        counts=dict(conn.execute('SELECT status,count(*) FROM tasks GROUP BY status').fetchall())
        active=[dict(row) for row in conn.execute("SELECT id,title,assignee,status,last_heartbeat_at FROM tasks WHERE status IN ('running','blocked','triage','review','ready') ORDER BY priority DESC LIMIT 12")]
        for task in active:
            runs=conn.execute('SELECT status,error FROM task_runs WHERE task_id=? ORDER BY id DESC LIMIT 2',(task['id'],)).fetchall()
            task['runs']=[dict(r) for r in runs]
    conn.close()
    lines=[f"Execução: {data['attempt']}",f"Fase: {data['phase']}",
           f"Produto liberado: {'sim' if data.get('product_dispatch_enabled') else 'não'}; ensaio aprovado: {'sim' if data.get('rehearsal_passed') else 'não'}",
           f"Planejamento documental: {'liberado' if data.get('planning_dispatch_enabled') else 'não liberado'}",
           'Kanban: '+(', '.join(f'{key}={value}' for key,value in counts.items()) or 'vazio')]
    if data.get('planning_status'):
        progress=data['planning_status']
        lines.append(f"Documentos: {progress['approved']}/{progress['total']} aprovados na revisão exata — {progress['state']}")
    lines.append('Próxima ação: '+data.get('next_action','não registrada'))
    if data.get('pr_review_status'):
        progress=data['pr_review_status']
        lines.append(f"Parecer de PR: {progress['approved']}/{progress['total']} revisados — {progress['state']}; não equivale a merge.")
    for receipt in data.get('publication_integrations',[]):
        lines.append(f"Integração comprovada: PR #{receipt['pr']} — commit {receipt['merge_commit']} — revisão {receipt['review_run']}.")
    for task in active:
        lines.append(f"{task['id']} | {task['assignee']} | {task['status']} | {task['title'][:110]}")
        for index,run in enumerate(task['runs']):
            reason='orçamento de iterações esgotado' if 'Iteration budget exhausted' in str(run['error']) else run['status']
            lines.append(f"  {'Última execução' if index==0 else 'Anterior'}: {reason}")
    with sqlite3.connect(f'file:{LEDGER}?mode=ro',uri=True) as db:
        pending=db.execute('SELECT count(*) FROM outbox WHERE attempt=? AND sent_at IS NULL',(data['attempt'],)).fetchone()[0]
        questions=[json.loads(row[0]) for row in db.execute("SELECT data FROM records WHERE attempt=? AND kind='question'",(data['attempt'],))]
    db.close()
    lines.append(f'Notificações pendentes: {pending}; decisões aguardadas: {sum(q["status"]=="pending" for q in questions)}')
    lines.append('Heartbeat não comprova progresso; HOMOLOGADA exige entrega e QA verificados.')
    return '\n'.join(lines)


def answer(question_id, answer_text, user_id, chat_id, is_bot=False):
    data=execution()
    if is_bot or str(user_id)!=str(data.get('ceo_telegram_id')) or str(chat_id)!=str(data.get('telegram_chat_id')):
        raise PermissionError('only the configured CEO in the team group may answer')
    store=CoordinationStore(LEDGER)
    try:
        question=store.get(data['attempt'],'question',question_id)
        if not question:
            raise ValueError('question does not belong to this execution')
        from hermes_cli import kanban_db as kb
        conn=kb.connect(board=data['board'])
        try:
            blocked=conn.execute("SELECT id,payload FROM task_events WHERE task_id=? AND kind IN ('blocked','block_loop_detected') ORDER BY id DESC LIMIT 1",(question['task'],)).fetchone()
            if not blocked or f'[DECISION:{question_id}]' not in str(json.loads(blocked['payload'] or '{}').get('reason','')):
                raise ValueError('question no longer matches the current block')
            store.answer(data['attempt'],question_id,str(user_id),answer_text,int(time.time()))
            record_answer_comment(conn,question_id,store.get(data['attempt'],'question',question_id))
            # Compare-and-unblock inside the native transaction. This only
            # resumes analysis; no tool permission or merge approval is granted.
            kb.unblock_task(conn,question['task'],expected_block_event=int(blocked['id']))
            current=conn.execute('SELECT status FROM tasks WHERE id=?',(question['task'],)).fetchone()
            result='análise retomada' if current and current['status'] in ('ready','todo','review','running') else 'aguardando replanejamento técnico'
            return f"Resposta {question_id} registrada para {question['task']}; {result}, sem concessão de permissões técnicas."
        finally:
            conn.close()
    finally:
        store.close()


def handle_command(text, source):
    text=re.sub(r'^/?kanban(?:@[A-Za-z0-9_]+)?(?:\s+|$)','',text.strip(),count=1)
    try:
        tokens=shlex.split(text)
        if tokens==['team-status']:
            return status()
        if tokens and tokens[0]=='decision':
            if len(tokens)<3:
                return 'Uso: /kanban decision ID_DA_PERGUNTA sua resposta'
            return answer(tokens[1],' '.join(tokens[2:]),getattr(source,'user_id',None),
                          getattr(source,'chat_id',None),getattr(source,'is_bot',False))
        return None
    except (ValueError,PermissionError) as exc:
        return 'Comando recusado: '+str(exc)


def ask(task, key, category, prompt, options):
    data=execution()
    profile=os.environ.get('HERMES_PROFILE')
    run_id=os.environ.get('HERMES_KANBAN_RUN_ID')
    if os.environ.get('HERMES_KANBAN_TASK')!=task or os.environ.get('HERMES_EXECUTION_ATTEMPT')!=data['attempt']:
        raise PermissionError('question must originate from the assigned worker in this attempt')
    if not re.fullmatch(r'q_[a-zA-Z0-9_-]{1,80}',key):
        raise ValueError('question ID must start with q_ and be stable for this decision')
    from hermes_cli import kanban_db as kb
    conn=kb.connect(board=data['board'])
    store=CoordinationStore(LEDGER)
    try:
        row=conn.execute('SELECT assignee,status,current_run_id FROM tasks WHERE id=?',(task,)).fetchone()
        if not row or row['status']!='running' or row['assignee']!=profile or str(row['current_run_id'])!=run_id:
            raise PermissionError('stale or unassigned worker')
        prior=store.get(data['attempt'],'question',key)
        if prior and prior['status']!='pending':
            raise ValueError('answered questions cannot be reused for a new block')
        expiry=prior['expires'] if prior else int(time.time())+86400
        store.question(data['attempt'],key,task,profile,category,prompt,options,str(data['ceo_telegram_id']),expiry)
        if not kb.block_task(conn,task,reason=f'[DECISION:{key}] {category}: {prompt}',kind='needs_input',expected_run_id=int(run_id)):
            raise ValueError('worker changed before question block; do not notify CEO')
        store.enqueue(data['attempt'],'question:'+key,json.dumps(dict(profile=profile,chat_id=data['telegram_chat_id'],
            text=question_message(data,key,store.get(data['attempt'],'question',key)))))
        return key
    finally:
        store.close()
        conn.close()


def question_message(data,key,question):
    return (f"Decisão {key} | {question['task']} | {question['category']}\n{question['prompt']}\n"
            f"Opções: {'; '.join(question['options'])}\n"
            f"Responda com /kanban@{data.get('command_bot','techlead_truco_poc_bot')} decision {key} sua resposta")


def record_answer_comment(conn,key,question):
    from hermes_cli import kanban_db as kb
    author='ceo-decision:'+key
    body=(f"Resposta verificada do CEO para {key}; categoria {question['category']}. "
          f"Conteúdo: {json.dumps(question['answer'],ensure_ascii=False)}\n"
          'Retome somente este escopo. Não equivale a aprovação de ferramenta, merge ou exceção não solicitada.')
    with kb.write_txn(conn):
        found=conn.execute('SELECT 1 FROM task_comments WHERE task_id=? AND author=? AND body=?',(question['task'],author,body)).fetchone()
        if not found:
            kb.add_comment(conn,question['task'],author,body)


def reconcile_questions(conn,config,store):
    """Recover crash-after-block-before-notify without generating a new question."""
    data=execution()
    if data['attempt']!=config['attempt'] or data['board']!=config['board']:
        return
    for row in store.db.execute("SELECT id,data FROM records WHERE attempt=? AND kind='question'",(data['attempt'],)).fetchall():
        key,question=row['id'],json.loads(row['data'])
        event=conn.execute("SELECT id,payload FROM task_events WHERE task_id=? AND kind IN ('blocked','block_loop_detected') ORDER BY id DESC LIMIT 1",(question['task'],)).fetchone()
        if not event or f'[DECISION:{key}]' not in str(json.loads(event['payload'] or '{}').get('reason','')):
            continue
        if question['status']=='pending' and question['expires']>=int(time.time()):
            store.enqueue(data['attempt'],'question:'+key,json.dumps(dict(profile=question['owner'],chat_id=data['telegram_chat_id'],text=question_message(data,key,question))))
        elif question['status']=='answered':
            from hermes_cli import kanban_db as kb
            record_answer_comment(conn,key,question)
            # Repair a crash after recording the answer but before native
            # unblock; the compare happens inside the same native write txn.
            kb.unblock_task(conn,question['task'],expected_block_event=int(event['id']))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('status')
    q=sub.add_parser('question')
    for field in ('task','id','category','prompt','options'):
        q.add_argument('--'+field,required=True)
    args=parser.parse_args()
    if args.action=='status':
        print(status())
    else:
        print(ask(args.task,args.id,args.category,args.prompt,json.loads(args.options)))
