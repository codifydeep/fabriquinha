"""Project native, authoritative Kanban events into the coordination ledger.

This records handoff receipt from real claims, never from Telegram promises.
Native Kanban remains the claim/lease authority. Each retry has its own lease
handoff rather than overwriting the receipt of an earlier worker.
"""
import json
from coordination_store import PROFILES
from review_policy import validate_review


def sync_handoffs(conn, config, store):
    attempt = config['attempt']
    saved = store.get(attempt, 'cursor', 'native_handoffs') or {'event_id':0}
    rows = conn.execute('''SELECT e.id,e.task_id,e.kind,e.payload,e.run_id,e.created_at AS at,
        t.title,t.assignee,r.profile FROM task_events e
        JOIN tasks t ON t.id=e.task_id LEFT JOIN task_runs r ON r.id=e.run_id
        WHERE e.id>? ORDER BY e.id''', (saved['event_id'],)).fetchall()
    processed = 0
    for row in rows:
        payload = json.loads(row['payload'] or '{}')
        sender, recipient, expected = 'system', None, None
        if row['kind'] == 'review_requested':
            sender, recipient = payload.get('implementer'), payload.get('reviewer')
            error = validate_review(sender, recipient)
            if error:
                raise ValueError('invalid native review handoff: ' + error)
            expected = 'Revisar independentemente; integrar ou devolver mudanças com evidência.'
        elif row['kind'] == 'changes_requested':
            sender, recipient = payload.get('reviewer'), payload.get('implementer')
            expected = 'Corrigir os achados e comprovar testes; solicitar nova revisão.'
        if recipient:
            store.handoff(attempt, f"event:{row['id']}", row['task_id'], sender, recipient,
                [f"kanban:{config['board']}:{row['task_id']}:event:{row['id']}"], expected, int(row['at']) + 1800)
        elif row['kind'] == 'claimed':
            recipient = row['profile']
            if recipient not in PROFILES:
                raise ValueError('native claim has no canonical owner')
            prior = conn.execute("SELECT id,kind,payload FROM task_events WHERE task_id=? AND id<? AND kind IN ('review_requested','changes_requested') ORDER BY id DESC LIMIT 1",
                                 (row['task_id'],row['id'])).fetchone()
            artifacts = [f"kanban:{config['board']}:{row['task_id']}"]
            expected = 'Executar o card e produzir evidência verificável.'
            if prior:
                handoff = json.loads(prior['payload'] or '{}')
                intended = handoff.get('reviewer') if prior['kind'] == 'review_requested' else handoff.get('implementer')
                if payload.get('source_status') == 'review' and intended != recipient:
                    raise ValueError('review claim differs from requested reviewer')
                sender = handoff.get('implementer') if prior['kind'] == 'review_requested' else handoff.get('reviewer')
                artifacts.append(f"kanban:event:{prior['id']}")
                expected = 'Revisão independente' if payload.get('source_status') == 'review' else 'Implementação/correção e testes'
            key = f"claim:{row['id']}:run:{row['run_id']}"
            store.handoff(attempt,key,row['task_id'],sender,recipient,artifacts,expected,int(row['at'])+1800)
            store.accept(attempt,key,recipient,str(row['run_id']))
            if prior:
                request_key = f"event:{prior['id']}"
                offered = store.get(attempt,'handoff',request_key)
                if offered and offered['status'] == 'offered' and offered['recipient'] == recipient:
                    store.accept(attempt,request_key,recipient,str(row['run_id']))
        with store.transaction(attempt):
            store._put(attempt,'cursor','native_handoffs',{'event_id':row['id']})
        processed += 1
    return processed
