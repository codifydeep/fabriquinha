"""Durable technical impediments, distinct from missing terminal operations."""
import json
from product_workspace import digest
from product_lane import emit
from hermes_cli import kanban_db as kb

class Impediments:
    def __init__(self,db,binding,native):
        self.db=db;self.binding=binding;self.native=native
        db.execute('CREATE TABLE IF NOT EXISTS product_impediments(id TEXT PRIMARY KEY,report TEXT,state TEXT)');db.commit()
    def handle(self,req):
        who=self.binding(req)
        if set(req)!={'operation','attempt','task','run','claim','category','evidence','next_action'}:raise ValueError('exact impediment fields required')
        if req['category'] not in ('dependency','capability','infrastructure','functional','evidence'):raise ValueError('technical category required')
        if any(not isinstance(req[n],str) or not 40<=len(req[n])<=5000 for n in ('evidence','next_action')):raise ValueError('concrete evidence and next action required')
        report={k:who[k] for k in ('attempt','task','run','profile','mode')};report.update({k:req[k] for k in ('category','evidence','next_action')})
        key=digest(report)
        with self.db:self.db.execute('INSERT OR IGNORE INTO product_impediments VALUES(?,?,?)',(key,json.dumps(report),'PREPARED'))
        self.recover();return dict(impediment=key,state='BLOCKED_TECHNICAL',owner='cto' if who['profile'] in ('cto','techlead') else 'techlead')
    def recover(self):
        if (self.binding.board/'MAINTENANCE').exists():return
        for key,raw in self.db.execute("SELECT id,report FROM product_impediments WHERE state='PREPARED'").fetchall():
            report=json.loads(raw);task=kb.get_task(self.native,report['task']);reason='technical-impediment:'+key+' '+report['category']+' — '+report['evidence']+' Next: '+report['next_action']
            if task.status=='running' and task.current_run_id==report['run']:
                if not kb.block_task(self.native,task.id,reason=reason,kind='capability',expected_run_id=report['run']):raise PermissionError('impediment transition refused')
            elif task.status not in ('blocked','triage'):raise PermissionError('impediment transition conflict')
            emit(self.binding.board,'technical_impediment',task=report['task'],profile=report['profile'],next_action=report['next_action'])
            with self.db:self.db.execute("UPDATE product_impediments SET state='DELIVERED' WHERE id=?",(key,))
