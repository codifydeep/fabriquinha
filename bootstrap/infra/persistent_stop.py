"""Turn-end enforcement from the exact durable run, never tool-call text."""
import os
import json
import sqlite3
from contextlib import closing


def closed_execution_message():
    """Stop before another model call after a verified transfer/revocation."""
    if not os.environ.get('HERMES_KANBAN_TASK'):
        return None
    try:
        task=os.environ['HERMES_KANBAN_TASK']; run=int(os.environ['HERMES_KANBAN_RUN_ID'])
        with closing(sqlite3.connect('file:'+os.environ['HERMES_KANBAN_DB']+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            execution=db.execute('SELECT * FROM task_runs WHERE id=? AND task_id=?',(run,task)).fetchone()
            current=db.execute('SELECT * FROM tasks WHERE id=?',(task,)).fetchone()
            claimed=db.execute("SELECT payload FROM task_events WHERE task_id=? AND run_id=? AND kind='claimed' ORDER BY id DESC LIMIT 1",(task,run)).fetchone()
            if not execution or not current or not claimed or json.loads(claimed['payload']).get('lock')!=os.environ['HERMES_KANBAN_CLAIM_LOCK']:
                return None
            if execution['ended_at'] is not None:
                return f"Execução {run} do card {task} encerrada no Kanban: {execution['outcome']}. Nenhuma ação adicional deste worker. Isso não declara homologação ou resolução do incidente."
            if current['current_run_id']!=run or current['claim_lock']!=os.environ['HERMES_KANBAN_CLAIM_LOCK']:
                return f"Posse da execução {run} do card {task} revogada. Worker encerrado sem alterar o novo responsável ou declarar sucesso."
    except (KeyError,ValueError,TypeError,sqlite3.Error):
        return None
    return None


def build_nudge(*, attempts=0, max_attempts=2, **ignored):
    task = os.environ.get('HERMES_KANBAN_TASK')
    if not task or attempts >= max_attempts:
        return None
    try:
        run = int(os.environ['HERMES_KANBAN_RUN_ID'])
        claim = os.environ['HERMES_KANBAN_CLAIM_LOCK']
        with closing(sqlite3.connect('file:'+os.environ['HERMES_KANBAN_DB']+'?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            execution = db.execute('SELECT * FROM task_runs WHERE id=? AND task_id=?', (run, task)).fetchone()
            current = db.execute('SELECT * FROM tasks WHERE id=?', (task,)).fetchone()
            claimed = db.execute("SELECT payload FROM task_events WHERE task_id=? AND run_id=? AND kind='claimed' ORDER BY id DESC LIMIT 1", (task, run)).fetchone()
            if not execution or not claimed or json.loads(claimed['payload']).get('lock') != claim or not current:
                raise ValueError('execution identity unavailable')
            # Ending this process is not task completion or release approval.
            if execution['ended_at'] is not None:
                return None
            if current['current_run_id'] != run or current['claim_lock'] != claim:
                return None  # Revoked ownership: never nudge an old worker to act.
        from review_boundary import worker_state
        state = worker_state()
        mode = state['mode'] if state else 'implementation'
        operations = {
            'review': 'review_inspect, review_validate, then kanban_complete or kanban_request_changes',
            'rework': 'rework_document, then kanban_request_review',
            'diagnosis': 'review_diagnose, then review_resume if safe; otherwise kanban_block',
            'implementation': 'finish the assigned evidence, then kanban_request_review',
        }
        if mode == 'closed':
            return None
        return ('[System: This exact execution has no durable terminal transition. '
                'Text and failed tool calls do not transfer responsibility. Mode: '+mode+'. '
                'Use only your authorized operations: '+operations[mode]+'. '
                'If blocked, record the concrete evidence with kanban_block. '
                'Never change another execution, bypass controls or claim release completion.]')
    except (KeyError, ValueError, sqlite3.Error):
        return ('[System: Durable execution identity could not be verified. Do not mutate '
                'files or claim success. Report the infrastructure/identity failure; '
                'do not attempt administrative recovery or another run.]')
