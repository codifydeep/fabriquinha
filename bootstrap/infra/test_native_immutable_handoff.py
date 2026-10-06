"""Real native transitions with temporary boards; no live cards or model calls."""
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from hermes_cli import kanban_db as kb
from review_controller import Controller
from validation_runner import run,digest
import review_boundary as boundary

with tempfile.TemporaryDirectory() as tmp:
    board=Path(tmp)/'board'; board.mkdir()
    kb.init_db(board/'kanban.db'); conn=kb.connect(board/'kanban.db')
    controller=Controller(board,Path(tmp)/'private','attempt','unused','unused')
    try:
        task=kb.create_task(conn,title='TDD',assignee='backend_data',initial_status='blocked')
        qa=kb.create_task(conn,title='QA',assignee='quality_security',parents=[task],initial_status='blocked')
        work=board/'workspaces'/task; work.mkdir(parents=True)
        conn.execute('UPDATE tasks SET workspace_path=? WHERE id=?',(str(work),task)); conn.commit()
        (work/'score.py').write_text('def winner(a,b):\n    return None\n')
        (work/'test_score.py').write_text('import unittest\nfrom score import winner\nclass Old(unittest.TestCase):\n    def test_old(self): self.assertIsNone(winner(0,0))\n')
        tests='import unittest\nfrom score import winner\nclass New(unittest.TestCase):\n'
        for i,(a,b,v) in enumerate([(13,0,'A'),(0,13,'B'),(0,0,None),(12,12,'A'),(12,11,'A')]):
            tests+=f'    def test_{i}(self): self.assertEqual(winner({a},{b}),{v!r})\n'
        (work/'test_new_score.py').write_text(tests)
        contract=dict(immutable_review=True,runner_required=True,review_probe=True,semantic_docs=True,
            regression_sha256=digest(work/'test_score.py'),fixture_sha256=digest(work/'score.py'),minimum_tests=6,implementer='backend_data')
        contracts={task:contract}
        (board/'validation-contracts.json').write_text(json.dumps(contracts))
        run(work,'red',contract)
        (work/'score.py').write_text('def winner(a,b):\n    return "A" if a>=12 else "B" if b>=12 else None\n')
        run(work,'green',contract)

        def broker(operation,**args):
            state=boundary.worker_state()
            return controller.handle(dict(args,operation=operation,task=state['task'],run=state['run'],claim=state['claim']))
        def env(claimed):
            return patch.dict(os.environ,dict(HERMES_KANBAN_TASK=claimed.id,HERMES_KANBAN_DB=str(board/'kanban.db'),
                HERMES_KANBAN_WORKSPACE=claimed.workspace_path,
                HERMES_KANBAN_RUN_ID=str(claimed.current_run_id),HERMES_KANBAN_CLAIM_LOCK=claimed.claim_lock))
        kb.unblock_task(conn,task)
        with patch.object(boundary,'call',broker):
            author=kb.claim_task(conn,task,claimer='author')
            with env(author):
                from agent.system_prompt import build_system_prompt_parts
                import run_agent
                with patch.object(run_agent,'load_soul_md',side_effect=AssertionError('product SOUL must not load')):
                    scoped=build_system_prompt_parts(object())
                    assert 'isolated validation worker' in scoped['stable']
                    assert scoped['volatile']==''
                assert 'IMPLEMENTATION ONLY' in kb.build_worker_context(conn,task)
                assert 'backend_data' in kb.build_worker_context(conn,task)
                assert boundary.intercept('kanban_request_changes',{})['error']=='implementation_requires_review'
                assert boundary.intercept('kanban_complete',{})['error']=='implementation_requires_review'
                # Freeze before native handoff, then retry: same immutable revision.
                first=broker('freeze',reviewer='techlead')['revision']
                assert broker('freeze',reviewer='techlead')['revision']==first
                assert kb.request_review(conn,task,reviewer='techlead',expected_run_id=author.current_run_id)
            reviewer=kb.claim_review_task(conn,task,claimer='reviewer')
            # Reproduce the cycle-4 blocked review, then let only the CTO's
            # scoped operation restore review (never implementation).
            with env(reviewer):
                assert kb.block_task(conn,task,reason='Review catalogue unavailable',kind='capability',expected_run_id=reviewer.current_run_id)
            # Reproduce C8's native timeout + gave_up representation. The
            # controller and native commit must agree on this latest event.
            conn.execute("UPDATE task_runs SET outcome='timed_out' WHERE id=?",(reviewer.current_run_id,))
            conn.execute("INSERT INTO task_events(task_id,run_id,kind,payload,created_at) VALUES(?,?,'timed_out',?,1)",
                (task,reviewer.current_run_id,json.dumps(dict(pid=123,retry_status='review'))))
            conn.execute("INSERT INTO task_events(task_id,kind,payload,created_at) VALUES(?,'gave_up',?,1)",
                (task,json.dumps(dict(pid=123,retry_status='review',trigger_outcome='timed_out'))))
            conn.commit()
            diagnosis=kb.create_task(conn,title='INCIDENT-'+task,assignee='cto',initial_status='blocked')
            kb.unblock_task(conn,diagnosis)
            conn.execute('UPDATE tasks SET workspace_path=? WHERE id=?',(str(work),diagnosis)); conn.commit()
            diagnostic=kb.claim_task(conn,diagnosis,claimer='cto')
            from review_recovery import apply_resume
            with env(diagnostic):
                evidence=broker('diagnose'); assert evidence['can_resume'],evidence
                receipt=broker('resume',revision=evidence['revision'],block_event=evidence['block_event'])
                # Crash after source commit, before parking: replay must not
                # create another transition or approval.
                with patch.object(kb,'schedule_task',return_value=False):
                    try: apply_resume(receipt)
                    except ValueError: pass
                    else: raise AssertionError('simulated interrupted parking ignored')
                assert broker('resume',revision=evidence['revision'],block_event=evidence['block_event'])==receipt
                assert apply_resume(receipt)['incident_resolved'] is False
            assert kb.get_task(conn,task).status=='review'
            assert kb.get_task(conn,diagnosis).status=='scheduled'
            assert conn.execute("SELECT count(*) FROM task_events WHERE kind='review_recovered'").fetchone()[0]==1
            assert controller.db.execute('SELECT count(*) FROM approvals').fetchone()[0]==0
            reviewer=kb.claim_review_task(conn,task,claimer='recovered-reviewer')
            with env(reviewer):
                import tools.kanban_tools
                from tools.registry import registry
                assert json.loads(registry.dispatch('review_probe_write',{}))['error']=='operation_forbidden'
                assert not (work/'DELIVERY_NOTES.md').exists()
                try: kb.request_changes(conn,task,reason='unverified claim',expected_run_id=reviewer.current_run_id)
                except ValueError as exc: assert 'review_validate required' in str(exc)
                else: raise AssertionError('changes without tests accepted')
                with patch.object(controller,'validate',return_value=dict(passed=True)):
                    broker('validate',revision=first)
                ok,_=kb.request_changes(conn,task,reason='Add DELIVERY_NOTES.md; preserve tests',expected_run_id=reviewer.current_run_id)
                assert ok
            assert kb.get_task(conn,task).assignee=='backend_data'
            author=kb.claim_task(conn,task,claimer='author2')
            with env(author):
                assert boundary.worker_state()['mode']=='rework'
                for name in ['terminal','write_file','patch','execute_code','kanban_complete']:
                    assert boundary.intercept(name,{})['error']=='operation_forbidden'
                import tools.kanban_tools
                from tools.registry import registry
                from semantic_delivery import CLAIMS
                try: registry.dispatch('rework_document',{'content':'3D game deployed and homologated'})
                except ValueError: pass
                assert not (work/'DELIVERY_NOTES.md').exists()
                result=json.loads(registry.dispatch('rework_document',{'content':json.dumps(CLAIMS)}))
                assert result['tests_and_code_unchanged'],result
                assert kb.request_review(conn,task,reviewer='techlead',expected_run_id=author.current_run_id)
            reviewer=kb.claim_review_task(conn,task,claimer='reviewer2')
            with env(reviewer):
                second=broker('inspect')['delivery']['revision']; assert second!=first
                assert broker('inspect')['documentation']['valid']
                # Even a snapshot introduced outside the normal submission
                # path cannot receive approval for unsupported documentation.
                import shutil
                bad=Path(tmp)/'bad-document'; shutil.copytree(work,bad)
                (bad/'DELIVERY_NOTES.md').write_text('A complete 3D game was deployed and approved.')
                forged=controller.store.capture(bad,attempt='attempt',task=task,author='backend_data',run=999)
                controller.db.execute('UPDATE deliveries SET revision=? WHERE task=? AND run=?',(forged,task,author.current_run_id)); controller.db.commit()
                with patch.object(controller,'validate',return_value=dict(passed=True)):
                    broker('validate',revision=forged)
                try: broker('approve',revision=forged)
                except ValueError as exc: assert 'documentation' in str(exc)
                else: raise AssertionError('unsupported documentation approved')
                controller.db.execute('UPDATE deliveries SET revision=? WHERE task=? AND run=?',(second,task,author.current_run_id)); controller.db.commit()
                try: broker('approve',revision=first)
                except ValueError: pass
                else: raise AssertionError('obsolete approval accepted')
                try: broker('approve',revision=second)
                except ValueError: pass
                else: raise AssertionError('approval without isolated tests accepted')
                with patch.object(controller,'validate',return_value=dict(passed=True)):
                    broker('validate',revision=second)
                assert kb.complete_task(conn,task,expected_run_id=reviewer.current_run_id,result='reviewed',fire_lifecycle_hook=False)
            assert kb.get_task(conn,task).status=='done'
            assert controller.db.execute('SELECT count(*) FROM deliveries').fetchone()[0]==2
            assert controller.db.execute('SELECT count(*) FROM approvals').fetchone()[0]==1
            controller.store.load('attempt',task,first)
            controller.store.load('attempt',task,second)
            qa_work=board/'workspaces'/qa; qa_work.mkdir()
            conn.execute('UPDATE tasks SET workspace_path=? WHERE id=?',(str(qa_work),qa)); conn.commit()
            qa_contract=dict(contract,implementer='quality_security',review_probe=False,parent=task)
            contracts[qa]=qa_contract
            (board/'validation-contracts.json').write_text(json.dumps(contracts))
            from delivery_gate import check_delivery
            assert qa in check_delivery(conn,diagnosis), 'incident closed before QA'
            kb.unblock_task(conn,qa)
            qa_author=kb.claim_task(conn,qa,claimer='qa')
            with env(qa_author):
                import tools.kanban_tools
                from tools.registry import registry
                imported=json.loads(registry.dispatch('review_fetch_parent',{}))
                assert imported['revision']==second,imported
                assert (qa_work/'DELIVERY_NOTES.md').read_bytes()==(work/'DELIVERY_NOTES.md').read_bytes()
                run(qa_work,'qa',qa_contract)
                assert kb.request_review(conn,qa,reviewer='techlead',expected_run_id=qa_author.current_run_id)
            qa_reviewer=kb.claim_review_task(conn,qa,claimer='qa-review')
            with env(qa_reviewer):
                qa_revision=broker('inspect')['delivery']['revision']
                with patch.object(controller,'validate',return_value=dict(passed=True)):
                    broker('validate',revision=qa_revision)
                assert kb.complete_task(conn,qa,expected_run_id=qa_reviewer.current_run_id,result='QA reviewed',fire_lifecycle_hook=False)
            assert controller.db.execute('SELECT revision FROM parent_links WHERE task=?',(qa,)).fetchone()[0]==second
            assert check_delivery(conn,diagnosis) is None, 'verified QA did not release incident gate'
        print('PASS: real handoff, denied write, changes request, original author rework, new review and completion')
        print('PASS: frozen handoff retry deduplicates; stale and unvalidated approvals rejected; both snapshots preserved')
        print('PASS: QA imports approved snapshot through registered tool and retains exact parent revision')
        print('PASS: CTO resumes only exact frozen review; interrupted parking retries without duplicate or false resolution')
        print('PASS: native incident gate waits for QA and exact parent review')
    finally: conn.close(); controller.db.close()
