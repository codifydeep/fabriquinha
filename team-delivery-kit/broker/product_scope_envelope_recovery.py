"""Controller-only recovery for proven pre-model scope envelope failures.

The failed plan stays immutable. A new plan/wakeup lineage is created only
after an authenticated failure, exact fixed prompt probe and original sponsor
reverification. No HTTP worker endpoint, dispatch effect, edit grant or approval.
"""
import contextlib
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
try:
    from . import native_scope_note,product_scope_execution as execution,product_scope_ledger as ledger
except ImportError:
    import native_scope_note
    import product_scope_execution as execution
    import product_scope_ledger as ledger

ERROR='hermes session/prompt failed: session/prompt: restricted broker stream failed: broker_internal (code=-32000)'


class NativeEffects(execution.NativeEffects):
    def qualify(self,plan):
        self.verify_binding(plan)
        incident=plan.get('incident') or {}
        task=self.task(incident.get('task_id'),plan['context']['cto'])
        if (task.get('status')!='failed' or task.get('error')!=ERROR
                or task.get('issue_id')!=plan['context']['issue_id']
                or task.get('scope_note_envelope_verified') is not True):
            raise ValueError('authenticated pre-model envelope failure required')
        with self.b.db() as con:
            rows=con.execute('SELECT e.method,e.success FROM acp_events e JOIN native_bindings n USING(request_id) '
                             'WHERE n.task_id=?',(task['id'],)).fetchall()
        if sorted(map(tuple,rows))!=[('initialize',1),('session/new',1)]:
            raise ValueError('exact pre-prompt ACP lineage required')
        memory=sqlite3.connect(':memory:')
        memory.execute('CREATE TABLE product_scope_plans(data TEXT)')
        memory.execute('INSERT INTO product_scope_plans VALUES (?)',(json.dumps(dict(plan,stage='awaiting_proposal')),))
        @contextlib.contextmanager
        def db():yield memory
        try:note=execution.prompt(SimpleNamespace(db=db),task,self)
        finally:memory.close()
        self.verify_binding(plan)
        return dict(operation='qualified_scope_envelope_recovery_v1',failed_task=task['id'],
                    original_plan_sha256=ledger.policy.digest(plan),
                    envelope_sha256=task['scope_note_envelope_sha256'],
                    decoder_sha256=hashlib.sha256(Path(native_scope_note.__file__).read_bytes()).hexdigest(),
                    prompt_sha256=hashlib.sha256(note.encode()).hexdigest(),
                    write_grant_issued=False,delivery_approval=False)


def recover(b,issue,effects=None):
    fx=effects or NativeEffects(b)
    with b.db() as con:
        row=con.execute('SELECT config,state FROM product_scope_runs WHERE issue_id=?',(issue,)).fetchone()
        if not row:raise ValueError('existing scope pipeline required')
        config,run=map(json.loads,row)
        if run.get('recovery'):
            existing=ledger.load(con,run['plan_key'])
            if (existing.get('recovery')!=run['recovery'] or existing['context']['issue_id']!=issue
                    or existing['context']['contract_sha256']!=config['contract_sha256']):
                raise ValueError('registered recovery lineage changed')
            return existing
        if (config.get('enabled') is not True or run.get('stage')!='blocked'
                or run.get('incident',{}).get('category')!='scope_plan_not_approved'):
            raise ValueError('exact rejected scope pipeline required')
        old=ledger.load(con,run['plan_key'])
    if (old['stage']!='blocked' or old.get('incident',{}).get('category')!='invalid_scope_proposal'
            or any(k in old for k in ('proposal','review','materialization','registration','recovery'))
            or old['context']['issue_id']!=issue or old['context']['source_task']!=run['source_task']
            or old['context']['contract_sha256']!=config['contract_sha256']):
        raise ValueError('unapproved original scope proposal failure required')
    proof=fx.qualify(old)
    keys={'operation','failed_task','original_plan_sha256','envelope_sha256','decoder_sha256',
          'prompt_sha256','write_grant_issued','delivery_approval'}
    if (set(proof)!=keys or proof['operation']!='qualified_scope_envelope_recovery_v1'
            or proof['failed_task']!=old['incident']['task_id']
            or proof['original_plan_sha256']!=ledger.policy.digest(old)
            or any(proof[k] is not False for k in ('write_grant_issued','delivery_approval'))
            or any(not isinstance(proof[k],str) or len(proof[k])!=64 or any(c not in '0123456789abcdef' for c in proof[k])
                   for k in ('envelope_sha256','decoder_sha256','prompt_sha256'))):
        raise ValueError('exact controller recovery proof required')
    key=ledger.policy.digest(dict(previous_plan=old['key'],proof=proof))
    new=dict(key=key,context=old['context'],original_contract=old['original_contract'],
             stage='awaiting_proposal',author_blocked=True,delivery_approval=False,
             recovery=dict(previous_plan=old['key'],proof=proof))
    with b.LOCK,b.db() as con:
        current=con.execute('SELECT config,state FROM product_scope_runs WHERE issue_id=?',(issue,)).fetchone()
        if tuple(current)!=tuple(row) or ledger.load(con,old['key'])!=old:
            raise ValueError('scope recovery sponsor changed during qualification')
        if con.execute('SELECT 1 FROM product_scope_plans WHERE plan_key=?',(key,)).fetchone():
            raise ValueError('unregistered recovery plan exists')
        con.execute('INSERT INTO product_scope_plans VALUES (?,?)',(key,ledger.encoded(new)))
        after=dict(run,stage='scope_plan',plan_key=key,recovery=dict(previous_plan=old['key'],proof=proof),
                   previous_incident=run['incident'])
        after.pop('incident')
        changed=con.execute('UPDATE product_scope_runs SET state=? WHERE issue_id=? AND state=?',
                            (ledger.encoded(after),issue,row[1]))
        if changed.rowcount!=1:raise ValueError('scope recovery CAS failed')
    return new
