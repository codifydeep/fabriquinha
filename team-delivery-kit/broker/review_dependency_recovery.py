"""Qualify a changed pre-model dependency, never manufacture a review verdict."""
import hashlib
import json
import time
import contextlib
import importlib.util
from pathlib import Path
import sqlite3
try:
    import native
except ImportError:
    from broker import native


def record(b, task_id):
    with b.LOCK, b.db() as con:
        binding=con.execute('SELECT * FROM native_bindings WHERE task_id=?',(task_id,)).fetchone()
        if not binding:raise ValueError('dependency failure binding required')
        trial=con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',
                          (binding['issue_id'],)).fetchone()
        if not trial:raise ValueError('independent review trial required')
        config,state=map(json.loads,trial)
        if (config['reviewer']!=binding['agent_id'] or state.get('status')!='blocked'
                or state.get('review_failure',{}).get('task_id')!=task_id
                or con.execute('SELECT 1 FROM tool_events WHERE request_id=? AND tool_count>0',
                               (binding['request_id'],)).fetchone()
                or con.execute("SELECT 1 FROM acp_events WHERE request_id=? AND method='session/prompt'",
                               (binding['request_id'],)).fetchone()):
            raise ValueError('exact failed pre-model independent reviewer required')
        settings=json.loads((b.STATE/'native.json').read_text())
        task=native.task_record(settings,task_id,binding['agent_id'])
        if (task.get('status')!='failed' or task.get('wakeup_id')!=state.get('wakeup_id')
                or 'restricted broker stream failed: broker_internal' not in (task.get('error') or '')):
            raise ValueError('exact native dependency failure required')
        issue=native.issue_record(settings,binding['issue_id'])
        identity={k:task.get(k) for k in ('id','agent_id','wakeup_id','handoff_note')}
        identity['task_id']=task_id
        try:
            b.native_task_prompt({'method':'session/prompt','params':{'prompt':[]}},
                                 settings['agents'][binding['agent_id']],issue,identity)
        except ModuleNotFoundError as error:
            if error.name not in ('execution_context','generated_context'):
                raise ValueError('unqualified missing dependency') from None
            missing=error.name
        else:
            raise ValueError('missing dependency not reproduced')
        receipt=dict(operation='native_review_dependency_failure_v1',task_id=task_id,
            issue_id=binding['issue_id'],agent_id=binding['agent_id'],wakeup_id=state['wakeup_id'],
            manifest_sha256=state['manifest_sha256'],missing_module=missing,
            old_image=b.IMAGE,model_calls=0,delivery_approval=False,at=time.time())
        con.execute('CREATE TABLE IF NOT EXISTS native_review_dependency_failures(task_id TEXT PRIMARY KEY,receipt TEXT)')
        prior=con.execute('SELECT receipt FROM native_review_dependency_failures WHERE task_id=?',(task_id,)).fetchone()
        if prior:return json.loads(prior[0])
        con.execute('INSERT INTO native_review_dependency_failures VALUES (?,?)',(task_id,json.dumps(receipt,sort_keys=True)))
        return receipt


def probe(b, con, issue, task, mode):
    """Exercise the installed prompt constructor with only selected in-memory state."""
    configuration=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
        (issue['id'],)).fetchone()[0])
    configuration['enabled']=True  # Hypothetical resumed route, not a live permission change.
    spec=importlib.util.spec_from_file_location('isolated_dependency_prompt_probe',b.__file__)
    isolated=importlib.util.module_from_spec(spec);spec.loader.exec_module(isolated)
    memory=sqlite3.connect(':memory:');memory.row_factory=sqlite3.Row
    try:
        memory.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
        memory.execute('INSERT INTO delivery_routes VALUES (?,?)',(issue['id'],json.dumps(configuration)))
        memory.execute('CREATE TABLE delivery_handoffs(source_task TEXT,issue_id TEXT,stage TEXT,owner TEXT,data TEXT)')
        for row in con.execute('SELECT source_task,issue_id,stage,owner,data FROM delivery_handoffs WHERE issue_id=?',
                               (issue['id'],)):
            memory.execute('INSERT INTO delivery_handoffs VALUES (?,?,?,?,?)',tuple(row))
        @contextlib.contextmanager
        def isolated_db():
            with memory:yield memory
        isolated.db=isolated_db
        identity={k:task.get(k) for k in ('id','agent_id','wakeup_id','handoff_note')};identity['task_id']=task['id']
        frame=isolated.native_task_prompt({'method':'session/prompt','params':{'prompt':[]}},mode,issue,identity)
        return hashlib.sha256(json.dumps(frame,sort_keys=True).encode()).hexdigest()
    finally:
        memory.close()


def repaired(b, con, payload, task, state):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='native_review_dependency_failures'").fetchone():
        return None
    row=con.execute('SELECT receipt FROM native_review_dependency_failures WHERE task_id=?',
                    (payload['failed_task'],)).fetchone()
    evidence=json.loads(row[0]) if row else {}
    if (not evidence or evidence.get('operation')!='native_review_dependency_failure_v1'
            or evidence.get('task_id')!=task['id'] or evidence.get('issue_id')!=payload['issue_id']
            or evidence.get('agent_id')!=task.get('agent_id') or evidence.get('wakeup_id')!=state.get('wakeup_id')
            or evidence.get('manifest_sha256')!=payload['manifest_sha256']
            or evidence.get('model_calls')!=0 or evidence.get('delivery_approval') is not False
            or evidence.get('old_image')==b.IMAGE
            or evidence.get('missing_module') not in ('execution_context','generated_context')):
        raise ValueError('changed exact review dependency evidence required')
    settings=json.loads((b.STATE/'native.json').read_text())
    issue=native.issue_record(settings,payload['issue_id'])
    prompt_sha256=probe(b,con,issue,task,settings['agents'][task['agent_id']])
    return dict(operation='qualified_review_dependency_repair_v1',failure=evidence,
        fixed_image=b.IMAGE,prompt_sha256=prompt_sha256,
        model_calls=0,delivery_approval=False)


if __name__=='__main__':
    import broker,sys
    receipt=record(broker,sys.argv[1])
    print(json.dumps(dict(recorded=True,task_id=receipt['task_id'],missing_module=receipt['missing_module'],
                         model_calls=0,delivery_approval=False)))
