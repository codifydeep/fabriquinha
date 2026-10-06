"""Native replay/decision/command tests: no network, real users or live volume."""
import asyncio
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch
from hermes_cli import kanban_db as kb
from gateway.slash_commands import GatewaySlashCommandsMixin
from coordination_store import CoordinationStore
import team_control


with tempfile.TemporaryDirectory(prefix='native-restart-') as tmp:
    root=Path(tmp)
    board=root/'boards'/'b2'
    board.mkdir(parents=True)
    path=board/'kanban.db'
    kb.init_db(path)
    conn=kb.connect(path)
    try:
        task=kb.create_task(conn,title='Isolated human decision',assignee='backend_data',initial_status='blocked')
        kb.unblock_task(conn,task)
        kb.block_task(conn,task,reason='[DECISION:q_first] initial fixture',kind='needs_input')
        first=conn.execute("SELECT MAX(id) FROM task_events WHERE task_id=? AND kind='blocked'",(task,)).fetchone()[0]
        try:
            kb.unblock_task(conn,task,expected_block_event=first+1)
        except ValueError:
            pass
        else:
            raise AssertionError('obsolete block accepted')
        assert kb.unblock_task(conn,task,expected_block_event=first)
        print('PASS: scoped native unblock rejects obsolete occurrence')
        ledger=root/'coordination.db'
        store=CoordinationStore(ledger)
        store.create_attempt('r2','b2','v0.1')
        store.question('r2','q_scope',task,'backend_data','scope','Web only?',['web','mobile'],'ceo-fixture',int(time.time())+600)
        kb.block_task(conn,task,reason='[DECISION:q_scope] scope fixture',kind='needs_input')
        registry=root/'execution.json'
        registry.write_text(json.dumps(dict(attempt='r2',board='b2',phase='ATIVA',
            product_dispatch_enabled=True,rehearsal_passed=True,ceo_telegram_id='ceo-fixture',telegram_chat_id='group-fixture')))
        original_connect=kb.connect
        with patch.object(team_control,'EXECUTION',registry),patch.object(team_control,'LEDGER',ledger),patch.object(team_control,'BOARDS',root/'boards'),patch.object(kb,'connect',lambda **kwargs:original_connect(path)):
            response=team_control.answer('q_scope','web','ceo-fixture','group-fixture')
            assert 'análise retomada' in response,response
            team_control.answer('q_scope','web','ceo-fixture','group-fixture')
            assert conn.execute("SELECT count(*) FROM task_comments WHERE author='ceo-decision:q_scope'").fetchone()[0]==1
            assert 'web' in conn.execute("SELECT body FROM task_comments WHERE author='ceo-decision:q_scope'").fetchone()[0]
            event=SimpleNamespace(text='/kanban@techlead_truco_poc_bot team-status',source=SimpleNamespace())
            output=asyncio.run(GatewaySlashCommandsMixin._handle_kanban_command(SimpleNamespace(),event))
            assert 'Execução: r2' in output,output
            print('PASS: real slash handler accepts bot mention and returns deterministic status')
            print('PASS: verified CEO answer resumes only its card and persists context once')
            kb.block_task(conn,task,reason='[DECISION:q_other] unrelated new block',kind='needs_input')
            try:
                team_control.answer('q_scope','web','ceo-fixture','group-fixture')
            except ValueError:
                pass
            else:
                raise AssertionError('old answer released a different block')
            print('PASS: old answer cannot release a later, different block')
        store.close()
    finally:
        conn.close()
