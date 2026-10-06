"""Fixed immutable PR review, with durable verdict recovery on the product board."""
import hashlib,json
from pathlib import Path
from product_workspace import digest

class PRReview:
    def __init__(self,root,binding,native,private):
        self.root=Path(root);self.binding=binding;self.native=native;self.db=private
        private.execute('CREATE TABLE IF NOT EXISTS product_pr_verdicts(task TEXT,run INTEGER,envelope TEXT,state TEXT,PRIMARY KEY(task,run))');private.commit()
    def packet(self,task):
        card=self.binding.cards[task]
        raw=(self.root/'pr-packets'/(task+'.json')).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=card['packet_sha256']:raise PermissionError('packet drift')
        return json.loads(raw),card['packet_sha256']
    def handle(self,req):
        identity=self.binding(req)
        if identity['mode']!='review':raise PermissionError('PR review only')
        op=req['operation'];allowed={'product_status':set(),'product_inspect':{'revision'},'product_read_file':{'revision','path','offset'},'product_verdict':{'revision','decision','reason'}}
        if op not in allowed or set(req)!={'operation','attempt','task','run','claim'}|allowed[op]:raise PermissionError('fixed PR operation only')
        packet,revision=self.packet(identity['task'])
        if op=='product_status':return dict(revision=revision,mode='review',head=packet['head'],base=packet['base'])
        if req['revision']!=revision:raise PermissionError('obsolete packet')
        from product_reading import compact,page
        if op=='product_inspect':return dict(packet,**compact(packet.get('files',{})))
        if op=='product_read_file':return dict(page(packet['files'],req['path'],req['offset']),revision=revision)
        decision=req['decision'];reason=req['reason']
        if decision not in ('approve','request_changes') or not isinstance(reason,str) or not 30<=len(reason)<=10000:raise ValueError('substantive verdict required')
        ci=packet['ci']
        if decision=='approve' and (ci['event']!='pull_request' or ci['head_sha']!=packet['head'] or ci['conclusion']!='success'):raise PermissionError('exact-head real CI required')
        envelope=dict(task=identity['task'],run=identity['run'],attempt=identity['attempt'],revision=revision,
            head=packet['head'],base=packet['base'],pr=packet['pr'],reviewer=identity['profile'],
            author=self.binding.cards[identity['task']]['author'],decision=decision,reason=reason,merge_authorized=False)
        with self.db:
            old=self.db.execute('SELECT envelope FROM product_pr_verdicts WHERE task=? AND run=?',(identity['task'],identity['run'])).fetchone()
            if old and json.loads(old[0])!=envelope:raise PermissionError('conflicting verdict')
            self.db.execute('INSERT OR IGNORE INTO product_pr_verdicts VALUES(?,?,?,?)',(identity['task'],identity['run'],json.dumps(envelope),'PREPARED'))
        return self.deliver(envelope)
    def deliver(self,envelope):
        from hermes_cli import kanban_db as kb
        task=envelope['task'];run=envelope['run'];summary='product-pr-verdict:'+digest(envelope)+'\n'+envelope['reason']
        if (self.binding.board/'MAINTENANCE').exists():raise PermissionError('board paused')
        row=self.native.execute('SELECT outcome,summary FROM task_runs WHERE id=? AND task_id=?',(run,task)).fetchone()
        outcome='completed' if envelope['decision']=='approve' else 'changes_requested'
        if not row or tuple(row)!=(outcome,summary):
            current=self.native.execute('SELECT claim_lock FROM tasks WHERE id=?',(task,)).fetchone()
            self.binding(dict(attempt=envelope['attempt'],task=task,run=run,claim=current['claim_lock'] if current else None))
            if envelope['decision']=='approve':
                ok=kb.complete_task(self.native,task,expected_run_id=run,summary=summary,result=summary,
                    metadata={'product_pr_verdict':envelope},fire_lifecycle_hook=False)
            else:ok=kb.request_changes(self.native,task,expected_run_id=run,reason=summary)[0]
            if not ok:raise PermissionError('native verdict refused')
        with self.db:self.db.execute("UPDATE product_pr_verdicts SET state='DELIVERED' WHERE task=? AND run=?",(task,run))
        return dict(envelope,state='DELIVERED')
    def recover(self):
        for row in self.db.execute("SELECT envelope FROM product_pr_verdicts WHERE state='PREPARED'").fetchall():self.deliver(json.loads(row[0]))
