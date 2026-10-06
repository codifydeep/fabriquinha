"""Mode-specific capabilities and prompts for the registered E2E board."""
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing
from e2e_policy import BASELINE,NOTES


def config(database=None):
    path=Path(database or os.environ.get('HERMES_KANBAN_DB','/absent')).parent/'e2e.json'
    return json.loads(path.read_text()) if path.is_file() else None


def registered(conn,task):
    data=config(conn.execute('PRAGMA database_list').fetchone()[2])
    return bool(data and task in data['cards'].values())


def allowed(state):
    data=config()
    if not data or state['task'] not in data['cards'].values(): return None
    if state['mode']=='closed': return set()
    role=next(k for k,v in data['cards'].items() if v==state['task'])
    common={'kanban_show','kanban_heartbeat','kanban_comment','kanban_block','e2e_status'}
    if state['mode']=='review':
        return common|{'review_inspect','review_validate','kanban_request_changes','kanban_complete'}|({'e2e_merge'} if role=='build' else {'e2e_review_validate'})
    return common|{'kanban_request_review'}|{'build':{'e2e_write','e2e_test','e2e_submit','e2e_restore_published'},'deploy':{'e2e_deploy'},'qa':{'e2e_verify'}}[role]


def context(conn,task):
    data=config(conn.execute('PRAGMA database_list').fetchone()[2])
    if not data or task not in data['cards'].values(): return None
    row=conn.execute('SELECT * FROM tasks WHERE id=?',(task,)).fetchone()
    event=conn.execute("SELECT payload FROM task_events WHERE task_id=? AND run_id=? AND kind='claimed' ORDER BY id DESC LIMIT 1",(task,row['current_run_id'])).fetchone()
    review=row['status']=='review' or bool(event and json.loads(event['payload'] or '{}').get('source_status')=='review')
    role=next(k for k,v in data['cards'].items() if v==task)
    head=f'E2E rehearsal {data["attempt"]}. Task {task}. Profile {row["assignee"]}. Role {role}. Mode '+('REVIEW' if review else 'IMPLEMENTATION')+'.\n'
    if review:
        text='Use review_inspect, then review_validate(revision=delivery.revision). Review only the existing immutable evidence. Do not implement or repeat Red. '
        if role=='build':
            text+='If NOTES.md is missing, request changes to add the canonical notes. If notes exist and tests pass, call e2e_merge. If CI is pending, call e2e_status and retry e2e_merge; never complete before merged=true. Then kanban_complete. '
        else: text='Use review_inspect, then e2e_review_validate() with NO arguments: the controller selects the exact current deployed commit. After passed=true, call kanban_complete. Do not copy any historical hashes. '
        return head+text+'No generic terminal, file edits or infrastructure actions are allowed. Technical failures go to Tech Lead/CTO, not CEO.'
    if role=='build':
        if conn.execute("SELECT 1 FROM task_events WHERE task_id=? AND kind='changes_requested' LIMIT 1",(task,)).fetchone():
            return head+'REWORK: preserve app.py and test_user.py. Do not repeat Red/Green. Write ONLY NOTES.md with the content below; trailing newline is optional. Then e2e_submit. If wait_for_fault=true, call e2e_status until interrupted; replacement resumes. Request review only after submission returns revision and head.\n'+NOTES
        return head+'''First call e2e_status. If Green already exists, preserve ALL code and tests; do not repeat Red.
For a new task, e2e_write app.py with the EXACT baseline below, and write test_user.py with >=5 distinct unittest test methods, importing unittest and `from app import winner`. Use direct self.assertEqual(winner(...), ...) or self.assertIsNone(winner(...)). No helpers, skips or decorators.
Required cases: (12,0)->A, (0,12)->B, (12,13)->A, (0,0)->None, (11,11)->None.
Run e2e_test(stage="red") BEFORE implementation; real assertion failures must be accepted.
Then change ONLY app.py winner(a,b): A if a>=12, otherwise B if b>=12, otherwise None. No imports or function calls. Run e2e_test(stage="green").
The observer will kill the FIRST successful Green worker once, preserving its files. Before this injection, do not submit, block or overwrite anything; wait using e2e_status. The replacement worker reuses Green and calls e2e_submit.
Do NOT write NOTES.md on the first submission: the independent reviewer must request this documentation change. On that rework, write ONLY NOTES.md with the canonical content below; e2e_submit again. No code/test changes after Green.
After e2e_submit returns PR/head/revision, call kanban_request_review(reviewer="techlead"). Do not complete your own work.
After publication do not edit anything until formal changes are requested. If handoff reports workspace_changed_after_publication, use e2e_restore_published: it preserves divergent content privately and restores the published snapshot. Then request review; do not resubmit identical content.
BASELINE app.py:\n'''+BASELINE+'\nCANONICAL NOTES.md:\n'+NOTES
    if role=='deploy': return head+'Call e2e_deploy. It builds only the reviewed merge, verifies local HTTP, rolls back and restores the same candidate. After passed=true, kanban_request_review(reviewer="quality_security"). Never claim product homologation.'
    return head+'Call e2e_verify to independently test the deployed merge. After passed=true, kanban_request_review(reviewer="techlead"). Never fabricate logs or claim Truco release.'


def scoped_parts():
    data=config(); task=os.environ.get('HERMES_KANBAN_TASK')
    if not data or task not in data['cards'].values(): return None
    with closing(sqlite3.connect('file:'+os.environ['HERMES_KANBAN_DB']+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        instruction=context(db,task)
    return dict(stable='You are a scoped E2E rehearsal worker. Use actual tool results only. Do not access product files, credentials, profile memories or arbitrary commands. A closed run means stop. This test is not Truco homologation.',context=instruction,volatile='')


def register(registry,check_fn):
    from review_boundary import call,worker_state
    def restore(args,**kwargs):
        result=call('e2e_restore_published')
        state=worker_state(); root=Path(os.environ['HERMES_KANBAN_WORKSPACE']).resolve()
        if root!=Path(os.environ['HERMES_KANBAN_DB']).parent/'workspaces'/state['task']: raise PermissionError('assigned workspace only')
        for name in set(result['files'])|set(result['remove']):
            if name not in {'app.py','test_user.py','NOTES.md'} or (root/name).is_symlink(): raise PermissionError('unsafe restore path')
        for name,content in result['files'].items(): (root/name).write_text(content)
        for name in result['remove']: (root/name).unlink(missing_ok=True)
        return json.dumps(dict(call('e2e_restore_confirm'),backup_id=result['backup_id'],next_tool='kanban_request_review',reviewer='techlead'))
    registry.register(name='e2e_restore_published',toolset='kanban',schema=dict(name='e2e_restore_published',description='Original author only: preserve divergence privately and restore exact published snapshot; does not approve.',parameters=dict(type='object',properties={},additionalProperties=False)),handler=restore,check_fn=check_fn,emoji='↩')
    operations=['e2e_status','e2e_submit','e2e_merge','e2e_deploy','e2e_verify','e2e_test','e2e_review_validate']
    for name in operations:
        def handler(args,_name=name,**kwargs):
            result=call(_name,**args)
            if result.get('block_required'):
                from hermes_cli import kanban_db as kb
                state=worker_state(); db=kb.connect(os.environ['HERMES_KANBAN_DB'])
                try:
                    kb.block_task(db,state['task'],reason=json.dumps(result),kind='capability',expected_run_id=state['run'])
                finally: db.close()
                return json.dumps(dict(result,stop=True))
            green=result if _name=='e2e_test' and args.get('stage')=='green' else result.get('green') if _name=='e2e_status' else None
            if green and green.get('accepted') and result.get('mode','implementation')!='review':
                state=worker_state(); root=Path(os.environ['HERMES_KANBAN_WORKSPACE']).resolve()
                expected=Path(os.environ['HERMES_KANBAN_DB']).parent/'workspaces'/state['task']
                if root!=expected or (root/'e2e-fault-ready.json').is_symlink(): raise PermissionError('unsafe fault marker')
                (root/'e2e-fault-ready.json').write_text(json.dumps(dict(task=state['task'],run=state['run'],claim=state['claim'],green_run=green['run'])))
            return json.dumps(result)
        properties={'stage':{'type':'string','enum':['red','green']}} if name=='e2e_test' else {}
        registry.register(name=name,toolset='kanban',schema=dict(name=name,description='Fixed scoped E2E operation '+name,
            parameters=dict(type='object',properties=properties,required=list(properties),additionalProperties=False)),handler=handler,check_fn=check_fn,emoji='🧪')
    def write(args,**kwargs):
        call('e2e_edit_check',**args)
        state=worker_state(); root=Path(os.environ['HERMES_KANBAN_WORKSPACE']).resolve()
        if root!=Path(os.environ['HERMES_KANBAN_DB']).parent/'workspaces'/state['task']: raise PermissionError('assigned workspace only')
        path=root/args['path']
        if path.is_symlink(): raise PermissionError('symlink forbidden')
        path.write_text(NOTES if args['path']=='NOTES.md' else args['content'])
        return json.dumps(dict(written=args['path']))
    registry.register(name='e2e_write',toolset='kanban',schema=dict(name='e2e_write',description='Author-only edit of closed fixture files.',
        parameters=dict(type='object',properties={'path':{'type':'string','enum':['app.py','test_user.py','NOTES.md']},'content':{'type':'string'}},required=['path','content'],additionalProperties=False)),handler=write,check_fn=check_fn,emoji='📝')
