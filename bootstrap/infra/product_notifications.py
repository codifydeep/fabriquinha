"""Fixed-destination adapter relay. Never trusts a queued chat ID or token."""
import json
import urllib.request
from pathlib import Path
from dotenv import dotenv_values
from coordination_store import CoordinationStore

ATTEMPT='product-adapter-agent-trial-01'

def render(raw):
    event=json.loads(raw)
    if event.get('attempt')!=ATTEMPT or event.get('profile') not in ('backend_data','techlead'):
        raise ValueError('unexpected notification identity')
    if event.get('event') not in ('activity_started','activity_finished'):
        raise ValueError('unexpected event')
    label='STARTED' if event['event']=='activity_started' else 'HANDOFF COMPLETED'
    return event['profile'],f"[Adapter trial — recorded event]\n{label}: {event['task']} | run {event['run']} | {event['mode']}\nRevision: {event.get('revision','not submitted')}\nThis is an isolated rehearsal, not Truco homologation."

def flush(store,chat,token_for,send):
    count=0
    for item in store.pending(ATTEMPT):
        profile,text=render(item['text'])
        send(token_for(profile),chat,text)
        store.sent(ATTEMPT,item['id']);count+=1
    return count

def main():
    source=Path('/source')
    chat=json.loads((source/'governance/execution.json').read_text())['telegram_chat_id']
    def token_for(profile):
        token=dotenv_values(source/'profiles'/profile/'.env').get('TELEGRAM_BOT_TOKEN')
        if not token:raise ValueError('profile Telegram token unavailable')
        return token
    def send(token,chat,text):
        req=urllib.request.Request('https://api.telegram.org/bot'+token+'/sendMessage',
            data=json.dumps(dict(chat_id=chat,text=text)).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=20) as response:result=json.load(response)
        if result.get('ok') is not True:raise RuntimeError('Telegram did not acknowledge message')
    store=CoordinationStore('/trial-control/coordination.db')
    try:
        count=flush(store,chat,token_for,send)
        print(json.dumps(dict(sent=count,pending=len(store.pending(ATTEMPT)))))
    except Exception as exc:
        # urllib errors can contain bot tokens: never print their message.
        print(json.dumps(dict(error=type(exc).__name__,retry_safe=True)))
        raise SystemExit(1)
    finally:store.close()

if __name__=='__main__':main()
