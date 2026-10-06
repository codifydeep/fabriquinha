"""Attempt-scoped Telegram outbox; no tokens persisted, delivery is at-least-once."""
import hashlib
import json
import time
from coordination_store import CoordinationStore


def enqueue(config, profile, text, key=None):
    if key is None:
        # Periodic digests/alerts may repeat, but not on every failed send.
        bucket = int(time.time()) // config.get('repeat_seconds', 1800)
        key = 'notice:' + hashlib.sha256(f'{profile}:{bucket}:{text}'.encode()).hexdigest()
    store = CoordinationStore(config['coordination_path'])
    try:
        store.enqueue(config['attempt'], key, json.dumps(dict(profile=profile, chat_id=config['chat_id'], text=text)))
    finally:
        store.close()


def flush(config, send, token_for, limit=2):
    store = CoordinationStore(config['coordination_path'])
    sent = 0
    try:
        for item in store.pending(config['attempt'])[:limit]:
            message = json.loads(item['text'])
            try:
                if config['attempt']=='rehearsal-e2e-20260916-ds1' and item['id']=='e2e-outbox-probe':
                    if not store.get(config['attempt'],'e2e_probe','notification_failure'):
                        with store.transaction(config['attempt']):
                            store._put(config['attempt'],'e2e_probe','notification_failure',dict(injected=True,at=time.time()))
                        raise ConnectionError('controlled one-time outbox failure')
                send(token_for(message['profile']), message['chat_id'],
                     f"[{config['attempt']} | {item['id'][:30]}]\n" + message['text'])
            except Exception:
                # Do not emit exception text: HTTP errors may contain tokens.
                break
            store.sent(config['attempt'], item['id'])
            sent += 1
        return sent
    finally:
        store.close()
