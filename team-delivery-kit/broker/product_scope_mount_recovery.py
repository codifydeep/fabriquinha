"""Controller-only recovery of a proven missing-evidence review mount.

Reauthenticate the completed proposal and the failed review's observed worker
policy. Probe the corrected mount resolver in isolated historical state; never
recreate a worker or pretend a failed reviewer approved anything.
"""
import contextlib
import hashlib
import json
import sqlite3
from types import SimpleNamespace
try:
    from . import product_scope_execution as execution,product_scope_ledger as ledger,test_revision_review as revision
except ImportError:
    import product_scope_execution as execution
    import product_scope_ledger as ledger
    import test_revision_review as revision

ERROR='hermes session/prompt failed: session/prompt: Internal error (code=-32603, data={"broker_diagnostic": []})'


class NativeEffects(execution.NativeEffects):
    def qualify(self,plan):
        b=self.b;c=plan['context'];self.verify_binding(plan)
        ledger.policy.validate_proposal(plan['original_contract'],c,plan['proposal'])
        proposal=self.task(plan['proposal_task']['id'],c['cto'])
        if (ledger.task_identity(proposal)!=plan['proposal_task'] or proposal.get('status')!='completed'
                or execution.terminal_output(proposal)!=plan['proposal']
                or self.read_hashes(proposal,c['eligible_code_sha256'])!=c['eligible_code_sha256']):
            raise ValueError('reauthenticated unchanged completed proposal required')
        failed=self.task(plan['incident']['task_id'],c['reviewer'])
        if failed.get('status')!='failed' or failed.get('error')!=ERROR or failed.get('issue_id')!=c['issue_id']:
            raise ValueError('exact failed independent review required')
        with b.db() as con:
            rows=con.execute('SELECT n.request_id,i.payload,l.status FROM native_bindings n '
                             'JOIN worker_creation_intents i USING(request_id) JOIN leases l USING(request_id) '
                             'WHERE n.task_id=?',(failed['id'],)).fetchall()
            if len(rows)!=1 or rows[0][2]!='closed':raise ValueError('one closed failed review worker required')
            request,raw,_=rows[0];payload=json.loads(raw)
            observations=[json.loads(r[0]) for r in con.execute('SELECT receipt FROM worker_policy_observations WHERE request_id=?',(request,))]
            snapshot=con.execute('SELECT volume,status FROM snapshots WHERE task_id=?',(c['source_task'],)).fetchone()
        if (any(m.get('Target')=='/evidence/candidate' for m in payload.get('HostConfig',{}).get('Mounts',[]))
                or payload.get('Labels',{}).get('delivery-kit.owner')!=b.OWNER
                or not snapshot or snapshot[1]!='complete'):
            raise ValueError('proven absent candidate mount and exact sponsor required')
        payload_sha=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        if not any(o.get('operation')=='worker_policy_observation_v1' and o.get('request_id')==request
                   and o.get('payload_sha256')==payload_sha and o.get('worker_image')==payload['Image']
                   and o.get('normalized_differences')==[] for o in observations):
            raise ValueError('observed exact failed worker policy required')
        expected=[dict(Type='volume',Source=snapshot[0],Target='/evidence/candidate',ReadOnly=True)]
        memory=sqlite3.connect(':memory:')
        memory.executescript('CREATE TABLE product_scope_plans(plan_key TEXT PRIMARY KEY,data TEXT);'
            'CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,issue_id TEXT,agent_id TEXT);'
            'CREATE TABLE snapshots(task_id TEXT,volume TEXT,status TEXT);')
        historical=dict(plan,stage='awaiting_review')
        memory.execute('INSERT INTO product_scope_plans VALUES (?,?)',(plan['key'],ledger.encoded(historical)))
        memory.execute('INSERT INTO native_bindings VALUES (?,?,?,?)',(request,failed['id'],c['issue_id'],c['reviewer']))
        memory.execute('INSERT INTO snapshots VALUES (?,?,?)',(c['source_task'],snapshot[0],'complete'))
        @contextlib.contextmanager
        def db():yield memory
        def read_volume(method,path,*args):
            if method!='GET' or path!='/volumes/'+snapshot[0] or args:raise ValueError('read-only mount probe required')
            return b.docker(method,path)
        # Replay only the historical metadata in a read-only structural probe.
        # There is no grant, container creation or live-state substitution.
        def historical_task(identifier,actor):
            if identifier!=failed['id'] or actor!=c['reviewer']:raise ValueError('exact historical reviewer required')
            return dict(failed,status='running')
        fx=SimpleNamespace(task=historical_task,verify_binding=self.verify_binding,wake=self.wake)
        probe=SimpleNamespace(db=db,docker=read_volume,OWNER=b.OWNER)
        try:
            # The public resolver must delegate to the real scoped mount logic.
            actual=revision.planning_mounts(probe,request,scope_effects=fx)
            if actual!=expected:raise ValueError('corrected resolver did not select exact read-only evidence')
        finally:memory.close()
        self.verify_binding(plan)
        return dict(operation='qualified_scope_mount_recovery_v1',failed_task=failed['id'],
                    original_plan_sha256=ledger.policy.digest(plan),proposal_sha256=plan['proposal_sha256'],
                    failed_payload_sha256=payload_sha,mount_sha256=ledger.policy.digest(expected),
                    write_grant_issued=False,delivery_approval=False)


def recover(b,issue,effects=None):
    fx=effects or NativeEffects(b)
    with b.db() as con:
        row=con.execute('SELECT config,state FROM product_scope_runs WHERE issue_id=?',(issue,)).fetchone()
        if not row:raise ValueError('registered scope pipeline required')
        config,run=map(json.loads,row)
        old=ledger.load(con,run['plan_key'])
        if run.get('mount_recovery'):
            if (old.get('mount_recovery')!=run['mount_recovery'] or old['context']['issue_id']!=issue
                    or old['context']['contract_sha256']!=config['contract_sha256']):
                raise ValueError('immutable mount recovery lineage required')
            return old
    if (config.get('enabled') is not True or run['stage']!='blocked'
            or run.get('incident',{}).get('category')!='scope_plan_not_approved'
            or old['stage']!='blocked' or old.get('incident',{}).get('category')!='invalid_scope_review'
            or any(k in old for k in ('review','qualification','materialization','registration','mount_recovery'))
            or old['context']['issue_id']!=issue or old['context']['source_task']!=run['source_task']
            or old['context']['contract_sha256']!=config['contract_sha256']
            or old.get('proposal_sha256')!=ledger.policy.digest(old.get('proposal'))):
        raise ValueError('exact unapproved review mount failure required')
    proof=fx.qualify(old)
    keys={'operation','failed_task','original_plan_sha256','proposal_sha256','failed_payload_sha256',
          'mount_sha256','write_grant_issued','delivery_approval'}
    if (set(proof)!=keys or proof['operation']!='qualified_scope_mount_recovery_v1'
            or proof['failed_task']!=old['incident']['task_id'] or proof['original_plan_sha256']!=ledger.policy.digest(old)
            or proof['proposal_sha256']!=old['proposal_sha256']
            or any(proof[k] is not False for k in ('write_grant_issued','delivery_approval'))
            or any(not isinstance(proof[k],str) or len(proof[k])!=64 or any(c not in '0123456789abcdef' for c in proof[k])
                   for k in ('failed_payload_sha256','mount_sha256'))):
        raise ValueError('exact non-authorizing mount recovery proof required')
    key=ledger.policy.digest(dict(previous_plan=old['key'],proof=proof))
    new={k:old[k] for k in ('context','original_contract','proposal','proposal_sha256','proposal_task')}
    new.update(key=key,stage='awaiting_review',author_blocked=True,delivery_approval=False,
               mount_recovery=dict(previous_plan=old['key'],proof=proof))
    with b.LOCK,b.db() as con:
        current=con.execute('SELECT config,state FROM product_scope_runs WHERE issue_id=?',(issue,)).fetchone()
        if tuple(current)!=tuple(row) or ledger.load(con,old['key'])!=old:raise ValueError('mount recovery sponsor changed')
        con.execute('INSERT INTO product_scope_plans VALUES (?,?)',(key,ledger.encoded(new)))
        after=dict(run,stage='scope_plan',plan_key=key,mount_recovery=new['mount_recovery'],previous_incident=run['incident'])
        after.pop('incident')
        changed=con.execute('UPDATE product_scope_runs SET state=? WHERE issue_id=? AND state=?',(ledger.encoded(after),issue,row[1]))
        if changed.rowcount!=1:raise ValueError('mount recovery CAS failed')
    return new
