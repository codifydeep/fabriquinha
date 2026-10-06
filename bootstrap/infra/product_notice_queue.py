"""Bounded, persistent per-message notification delivery; never blocks work."""
import json,time

PROFILES={'produto','designer','cto','techlead','backend_data','frontend','mobile','devops','quality_security'}

def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,payload TEXT,sent INTEGER DEFAULT 0)')
    columns={r[1] for r in db.execute('PRAGMA table_info(events)')}
    for name,definition in (
        ('delivery_attempts','INTEGER NOT NULL DEFAULT 0'),
        ('next_attempt','REAL NOT NULL DEFAULT 0'),
        ('delivery_state',"TEXT NOT NULL DEFAULT 'PENDING'"),
        ('last_error','TEXT'),('alerted','INTEGER NOT NULL DEFAULT 0')):
        if name not in columns:db.execute('ALTER TABLE events ADD COLUMN '+name+' '+definition)
    db.commit()

def flush(db,send,now=None,limit=20):
    schema(db)
    now=time.time() if now is None else now
    delivered=0
    rows=db.execute("SELECT id,payload,delivery_attempts,alerted FROM events WHERE sent=0 AND delivery_state='PENDING' AND next_attempt<=? ORDER BY id LIMIT ?",(now,limit)).fetchall()
    for identity,raw,attempts,alerted in rows:
        event={};permanent=False
        try:
            event=json.loads(raw)
            if not isinstance(event,dict):raise ValueError('invalid event')
            profile=event.get('profile','techlead')
            if profile not in PROFILES or not isinstance(event.get('task'),str) or not isinstance(event.get('event'),str):raise ValueError('invalid event')
            text=('[Truco v0.1 | lobby real | '+str(identity)+']\n'+event['event'].upper()+': '+event['task']+' | '+profile+'\n'+
                'Status/mode: '+str(event.get('status',event.get('mode','')))+'\n'+
                'Next: '+str(event.get('next_action','Execute assigned work and record evidence'))+'\n'+
                'Board: Truco v0.1 — Lobby real. Snapshot review is not PR integration or homologation.')
            # Telegram allows 4096 characters; preserve event identity and link to board.
            text=text[:3900]
        except (TypeError,ValueError,KeyError):
            permanent=True
        try:
            if permanent:raise ValueError('invalid event')
            send(profile,text)
        except Exception as exc:
            attempts+=1
            with db:
                db.execute('UPDATE events SET delivery_attempts=?,next_attempt=?,delivery_state=?,last_error=? WHERE id=?',
                    (attempts,now+min(900,15*2**min(attempts,6)),'QUARANTINED' if permanent else 'PENDING',type(exc).__name__,identity))
                # Do not recursively create alerts about an undeliverable alert.
                if not alerted and (permanent or attempts>=5) and (not isinstance(event,dict) or event.get('event')!='notification_degraded'):
                    alert=dict(event='notification_degraded',task='notification-'+str(identity),profile='techlead',source_event=identity,
                        next_action='Notification '+str(identity)+' requires delivery diagnosis; execution continues. Inspect the durable queue; never resend work as a chat command.')
                    db.execute('INSERT INTO events(payload) VALUES(?)',(json.dumps(alert),))
                    db.execute('UPDATE events SET alerted=1 WHERE id=?',(identity,))
            print(json.dumps(dict(event='telegram_quarantined' if permanent else 'telegram_pending',id=identity,error=type(exc).__name__)),flush=True)
            continue
        with db:db.execute("UPDATE events SET sent=1,delivery_state='DELIVERED',last_error=NULL WHERE id=?",(identity,))
        delivered+=1
        print(json.dumps(dict(event='telegram_sent',id=identity)),flush=True)
    return delivered
