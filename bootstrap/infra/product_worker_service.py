"""Opt-in controller bridge. Notifications persist before external delivery.

Instantiate only with controller-owned Workspace/runner and its matching native
board connection. No production bootstrap is implied by importing this module.
"""
import json
from pathlib import Path
from product_controller import ProductController
from product_handoff import deliver
from product_verdict import deliver_verdict
from product_workspace import digest


class WorkerService(ProductController):
    def __init__(self,workspace,tdd,runner,native):
        super().__init__(workspace,tdd,runner)
        database=Path(native.execute('PRAGMA database_list').fetchone()[2]).resolve()
        if database!=workspace.claim.board/'kanban.db':raise PermissionError('native board mismatch')
        self.native=native
        self.db.execute('CREATE TABLE IF NOT EXISTS product_notifications(id TEXT PRIMARY KEY,attempt TEXT,payload TEXT,sent INTEGER DEFAULT 0)');self.db.commit()

    def notify(self,event,payload):
        content=dict(event=event,**payload);identity=digest(content)
        with self.db:self.db.execute('INSERT OR IGNORE INTO product_notifications(id,attempt,payload) VALUES(?,?,?)',
                                    (identity,payload['attempt'],json.dumps(content)))

    def handle(self,request):
        current,_=self.w.state(request)
        self.notify('activity_started',{k:current[k] for k in ('attempt','task','run','profile','mode')})
        result=super().handle(request)
        if request['operation']=='product_submit':
            result=dict(result,**deliver(self,self.native,result))
            result['handed_off']=True
        elif request['operation']=='product_verdict':
            result=dict(result,**deliver_verdict(self,self.native,result))
        if request['operation'] in ('product_submit','product_verdict'):
            self.notify('activity_finished',dict(attempt=current['attempt'],task=current['task'],run=current['run'],
                profile=current['profile'],mode=current['mode'],revision=result['revision'],state=result['state']))
        return result

    def recover(self):
        for row in self.db.execute("SELECT envelope FROM product_handoffs WHERE state='PREPARED'").fetchall():
            envelope=json.loads(row[0]);deliver(self,self.native,envelope)
        for row in self.db.execute("SELECT envelope FROM product_verdicts WHERE state='PREPARED'").fetchall():
            envelope=json.loads(row[0]);deliver_verdict(self,self.native,envelope)
        self.collect_finished()

    def collect_finished(self):
        # Reconstruct notifications even if process died immediately after the
        # native transition/ack. Stable content gives the same deduplication key.
        for table,run_field,profile_field,mode in (
            ('product_handoffs','run','author','implementation'),
            ('product_verdicts','review_run','reviewer','review')):
            for row in self.db.execute("SELECT envelope FROM "+table+" WHERE state='DELIVERED'").fetchall():
                envelope=json.loads(row[0])
                self.notify('activity_finished',dict(attempt=envelope['attempt'],task=envelope['task'],
                    run=envelope[run_field],profile=envelope[profile_field],mode=mode,
                    revision=envelope['revision'],state='DELIVERED'))

    def export_notifications(self,ledger,chat_id=None):
        # Existing coordination sender owns Telegram retries/acknowledgement.
        # A crash between enqueue and sent=1 repeats the same ledger key.
        self.collect_finished()
        for identity,attempt,payload in self.db.execute('SELECT id,attempt,payload FROM product_notifications WHERE sent=0').fetchall():
            if chat_id is not None:
                event=json.loads(payload)
                payload=json.dumps(dict(profile=event['profile'],chat_id=chat_id,text=json.dumps(event)))
            ledger.enqueue(attempt,'product:'+identity,payload)
            with self.db:self.db.execute('UPDATE product_notifications SET sent=1 WHERE id=?',(identity,))
