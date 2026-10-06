"""Persistent, idempotent escalation of blocked deliveries.

State is saved by the watchdog. Kanban incident cards are the durable work queue;
idempotency keys make a retry after a watchdog crash safe.
"""
import json
import subprocess


def parent_owner(profile):
    return 'cto' if profile in ('techlead', 'cto') else 'techlead'


def cli(config, *args):
    result = subprocess.run(
        [config['hermes_executable'], '-p', 'techlead', 'kanban', '--board', config['board'], *args],
        text=True, capture_output=True, timeout=45,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()[:500])
    return result.stdout


def incident_body(source, reason):
    return f'''Incidente operacional do card {source}. Evidência inicial: {reason}

Sua responsabilidade é remover o impedimento ou apresentar a decisão humana mínima necessária.
1. Leia o card original, seus pais, logs e PRs; mantenha o implementador original. Diagnostique o workspace_path do ORIGINAL, não seu scratch. Scratch vazio não prova worktree limpo. Leia comentários posteriores ao bloqueio: uma resposta humana pode já existir. Comentário não executa unblock nem equivale a aprovação de ferramenta.
2. Registre categoria, causa, evidência, próxima ação e condição verificável de retomada em comentário deste incidente.
   Se a causa for Iteration budget exhausted ou falha do validation_runner, leia o último traceback e runner-failures.json do original. Não aumente limites nem desbloqueie sem um diagnóstico específico. Verifique se os testes importam a implementação, se Red falha por assertions esperadas e se stdout/stderr foram capturados. Retorne a correção ao autor, sem enfraquecer testes ou editar evidências. Questões técnicas vão ao CTO, não ao CEO. Use o executor padronizado quando o contrato do card o exigir; não crie runners alternativos.
3. Para dependência sem merge, revise o PR e a CI; integre somente se correto e com autorização de revisão, nunca aprove conteúdo incorreto. Prove SHA ancestral da release remota.
4. Para permissão, prepare a alteração e indique operação/caminho exatos. Não contorne negação nem use terminal para substituir uma edição protegida. Solicite ao CEO apenas a autorização indispensável; autorização de uma política não desliga todas as proteções.
5. Para falha técnica, diagnostique ou proponha experimento pequeno. CTO decide arquitetura e estratégia; Tech Lead coordena revisão e integração. Merge normal não é tarefa do CEO. Nunca proponha --allow-unrelated-histories, force-push ou bypass de CI como recuperação genérica. Não crie nova geração de PLAN/RELEASE/RECOVERY para o mesmo incidente.
6. Se a pré-condição for comprovadamente satisfeita, comente a prova no card original e use a CLI Kanban unblock no original. Se o original já estiver done incorretamente, corrija sua dependência real antes de declarar resolução.
7. Não conclua este incidente enquanto a condição de retomada não estiver comprovada. Registre comandos e resultados. Se faltar ação humana, use block --kind needs_input com pergunta objetiva, risco e alteração preparada.

Este é um card de operação em scratch: não implementa features nem edita worktrees de outros cards. Uma correção de código deve voltar ao implementador e à revisão normal. O supervisor conserva este incidente e escala seu responsável se não houver progresso; não crie incidentes filhos.'''


def tick(conn, config, state, now, verify_delivery):
    records = state.setdefault('handoff_incidents', {})
    notices = []
    sources = []
    for row in conn.execute("SELECT id,title,assignee,status FROM tasks WHERE status='blocked' AND title NOT LIKE 'RELEASE-%' AND title NOT LIKE 'INCIDENT-%'"):
        event = conn.execute("SELECT id,payload FROM task_events WHERE task_id=? AND kind='blocked' ORDER BY id DESC LIMIT 1", (row['id'],)).fetchone()
        reason = json.loads(event['payload'] or '{}').get('reason', 'blocked') if event else 'blocked'
        sources.append((dict(row), str(reason), 'blocked'))
    # A done flag is not proof of delivery. Audit recently completed worktree
    # tasks and tasks already under incident; avoid rechecking historical cards.
    for row in conn.execute("""SELECT t.id,t.title,t.assignee,t.status FROM tasks t
        WHERE t.status='done' AND t.workspace_kind='worktree'
          AND t.title NOT LIKE 'GRAPH-%' AND EXISTS (
            SELECT 1 FROM task_links l JOIN tasks child ON child.id=l.child_id
             WHERE l.parent_id=t.id AND child.status NOT IN ('done','archived'))"""):
        if row['id'] in records:
            if records[row['id']]['phase'] != 'resolved':
                continue
        error = verify_delivery(conn, row['id'])
        if error:
            sources.append((dict(row), error, 'integration'))
    for source, reason, category in sources:
        sid = source['id']
        if sid in records:
            record = records[sid]
            if record['phase'] == 'resolved':
                # A resumed worker can fail again: reopen the same incident,
                # preserving history and avoiding a second incident generation.
                task = conn.execute('SELECT status FROM tasks WHERE id=?', (record['card'],)).fetchone()
                if task and task['status'] == 'blocked':
                    cli(config, 'unblock', record['card'])
                cli(config, 'reassign', record['card'], parent_owner(source['assignee']), '--reclaim', '--reason', 'Recorrência do impedimento; diagnóstico anterior insuficiente')
                record.update(phase='open', owner=parent_owner(source['assignee']),
                              last_progress_at=now, created_at=now, reason=reason)
                notices.append(f"🔁 Impedimento {sid} reapareceu; retomando {record['card']} sem duplicar o incidente.")
            continue
        owner = parent_owner(source['assignee'])
        created = json.loads(cli(config, 'create', f'INCIDENT-{sid} — Resolver impedimento de entrega',
            '--body', incident_body(sid, reason), '--assignee', owner, '--workspace', 'scratch',
            '--priority', '100000', '--max-runtime', '30m', '--max-retries', '2',
            '--created-by', 'handoff-supervisor', '--idempotency-key', f'handoff-incident:{sid}', '--json'))
        records[sid] = {'card': created['id'], 'owner': owner, 'created_at': now,
            'last_progress_at': now, 'event_cursor': 0, 'category': category, 'phase': 'open', 'reason': reason}
        notices.append(f"🚧 Impedimento {sid}: {created['id']} atribuído a {owner}. Próxima ação: diagnosticar e comprovar a condição de retomada.")
    for sid, record in records.items():
        if record['phase'] == 'resolved':
            continue
        source = conn.execute('SELECT status,last_heartbeat_at FROM tasks WHERE id=?', (sid,)).fetchone()
        task = conn.execute('SELECT status,assignee FROM tasks WHERE id=?', (record['card'],)).fetchone()
        if not source or not task:
            continue
        # Once useful work/review is queued again, the incident must not
        # compete with it for the same profile's sole execution slot.
        if source['status'] in ('ready', 'review', 'running'):
            record['phase'] = 'monitoring_recovery'
            if task['status'] in ('ready', 'blocked'):
                cli(config, 'schedule', record['card'], 'Aguardar entrega do original; supervisor acompanha e reabre se voltar a bloquear')
            continue
        if source['status'] == 'blocked' and record['phase'] == 'monitoring_recovery':
            if task['status'] == 'scheduled':
                cli(config, 'unblock', record['card'])
            record.update(phase='open', last_progress_at=now)
            notices.append(f"🔁 {sid} voltou a bloquear; diagnóstico retomado em {record['card']}.")
        # A new dashboard response resumes analysis, never grants a tool
        # permission or unblocks the source automatically. Cursor survives
        # restarts; repeated words on old comments cannot cause a retry loop.
        response = conn.execute("SELECT id FROM task_comments WHERE task_id=? AND author='dashboard' AND created_at>=? ORDER BY id DESC LIMIT 1",
                                (record['card'], record['created_at'])).fetchone()
        if response and int(response['id']) > record.get('human_response_cursor', 0):
            if task['status'] == 'blocked':
                cli(config, 'comment', record['card'], 'Resposta humana nova no dashboard: leia e valide o escopo. Retomar diagnóstico não aprova conteúdo, merge, nem ferramenta protegida; não desbloquear o original sem verificar pré-condições.')
                cli(config, 'unblock', record['card'])
                record.update(phase='open', last_progress_at=now)
                notices.append(f"📩 Resposta recebida em {record['card']}; diagnóstico retomado para validar escopo e pré-condições.")
            record['human_response_cursor'] = int(response['id'])
        # Heartbeats/comments alone cannot resolve an incident.
        resolved = False
        if source['status'] == 'done':
            resolved = verify_delivery(conn, sid) is None
        if resolved:
            # Only the operational INCIDENT is closed automatically, never
            # the source delivery; its gate independently rechecks the source.
            if task['status'] == 'scheduled':
                cli(config, 'unblock', record['card'])
            if task['status'] in ('scheduled', 'ready', 'blocked'):
                cli(config, 'complete', record['card'], '--result', 'Supervisor comprovou entrega integrada do original; incidente operacional encerrado.')
            record['phase'] = 'resolved'
            cli(config, 'comment', record['card'], 'Supervisor verificou retomada do original ou entrega integrada. Incidente resolvido; histórico preservado.')
            notices.append(f"✅ Incidente {record['card']} resolvido: retomada de {sid} comprovada.")
            continue
        # Concrete Kanban decisions count; heartbeat and repeated generic chat do
        # not indefinitely postpone escalation.
        event = conn.execute("SELECT MAX(id) AS id FROM task_events WHERE task_id=? AND kind IN ('review_requested','changes_requested','completed')", (record['card'],)).fetchone()
        eid = int(event['id'] or 0)
        if eid > record['event_cursor']:
            record['event_cursor'] = eid
            record['last_progress_at'] = now
        if task['status'] == 'running' and record['phase'] == 'open':
            record['phase'] = 'attended'
            notices.append(f"🔎 {record['owner']} assumiu {record['card']} para resolver {sid}.")
        age = now - record['last_progress_at']
        if age >= 600 and record['phase'] == 'open':
            record['phase'] = 'late'
            notices.append(f"⚠️ Incidente {record['card']} sem atendimento há 10 min; prioridade operacional máxima, responsável {record['owner']}.")
        failed = task['status'] in ('blocked', 'done', 'archived')
        # A timeout is an operational signal, never proof that a human
        # business decision is needed. CTO remains accountable for technical
        # problems. Explicit human requests must be made with their scope.
        if record['phase'] == 'awaiting_ceo':
            record.update(phase='technical_attention', last_progress_at=now)
            cli(config, 'comment', record['card'], 'Correção de governança: timeout não transfere decisões técnicas ao CEO. CTO mantém responsabilidade. Solicitação humana só com categoria produto/escopo, credencial, autorização ou exceção de risco, pergunta objetiva e opções.')
        if (age >= 1800 or failed) and now - record.get('last_escalation_notice', 0) >= 1800:
            record['last_escalation_notice'] = now
            if record['owner'] == 'techlead':
                cli(config, 'reassign', record['card'], 'cto', '--reclaim', '--reason', 'Escalonamento: impedimento persiste sem resolução comprovada')
                if task['status'] == 'blocked':
                    cli(config, 'unblock', record['card'])
                record.update(owner='cto', last_progress_at=now, phase='escalated')
                notices.append(f"⬆️ {record['card']} escalado ao CTO; {sid} continua pendente.")
            else:
                record['phase'] = 'technical_attention'
                cli(config, 'comment', record['card'], 'ACAO_TECNICA_CTO: impedimento persiste. Registre hipótese, experimento local limitado, responsável, evidência esperada e condição de retomada. Solicite apoio do especialista adequado; não transfira escolha técnica/arquitetural ao CEO nem repita retries sem nova evidência. Se houver dependência realmente humana, registre categoria, pergunta exata e escopo da autorização.')
                notices.append(f"🛠️ CTO: ação técnica necessária em {record['card']} ({sid}); investigar com experimento e especialista. Não é uma solicitação de decisão ao CEO.")
    # No runnable work while a release is active must never look healthy.
    active = conn.execute("SELECT 1 FROM tasks WHERE title LIKE 'RELEASE-%' AND status NOT IN ('done','archived') LIMIT 1").fetchone()
    executable = conn.execute("SELECT 1 FROM tasks WHERE status IN ('running','ready','review') LIMIT 1").fetchone()
    if active and not executable:
        state.setdefault('release_idle_since', now)
        if now - state['release_idle_since'] >= 600 and now - state.get('release_idle_notice', 0) >= 1800:
            notices.append('🚨 Versão ativa sem trabalho executável há 10 min. Impedimentos encaminhados aos responsáveis; consulte os cards INCIDENT e decisões pendentes do CEO.')
            state['release_idle_notice'] = now
    else:
        state.pop('release_idle_since', None)
    return notices
