"""Native Hermes board, real tool registry, private snapshots; no external mocks."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from hermes_cli import kanban_db as kb
from review_controller import Controller
from planning_flow import ROLES, SECTIONS
import review_boundary as boundary

with tempfile.TemporaryDirectory() as tmp:
    board = Path(tmp) / 'planning-native'; board.mkdir()
    kb.init_db(board / 'kanban.db'); db = kb.connect(board / 'kanban.db')
    private = Path(tmp) / 'private'; private.mkdir()
    brief = 'Native approved planning brief'; digest = hashlib.sha256(brief.encode()).hexdigest()
    cards = {}
    for role, (author, reviewer) in ROLES.items():
        tid = kb.create_task(db, title='PLAN-' + role, assignee=author, initial_status='blocked')
        cards[tid] = dict(role=role, author=author, reviewer=reviewer, parents=[], objective='Concrete ' + role)
        root = board / 'workspaces' / tid; root.mkdir(parents=True)
        db.execute('UPDATE tasks SET workspace_path=? WHERE id=?', (str(root), tid)); db.commit()
    unknown = kb.create_task(db, title='IMPLEMENTATION-FORBIDDEN', assignee='backend_data', initial_status='blocked')
    packet=dict(pr=14,repository='codifydeep/truco-online',head_sha='a'*40,base_sha='b'*40,
        diff='complete diff',files={'doc.md':'content'},ci=dict(headSha='a'*40,conclusion='success'),trusted_guard_passed=True)
    raw=json.dumps(packet).encode()
    packet_digest=hashlib.sha256(raw).hexdigest()
    (private/'pr-review-packets').mkdir()
    (private/'pr-review-packets'/(packet_digest+'.json')).write_bytes(raw)
    for card in cards.values():
        if card['role']=='plan':
            card.update(scope='pr_review',pr_number=14,integration_action='merge_foundation',packet_storage='sha256',packet_sha256=packet_digest,head_sha='a'*40,base_sha='b'*40)
    data = dict(attempt='planning-native', brief_sha256=digest, cards=cards)
    (board / 'planning.json').write_text(json.dumps(data))
    (private / 'planning-config.json').write_text(json.dumps(data))
    (private / 'planning-brief.md').write_text(brief)
    controller = Controller(board, private, 'planning-native', 'unused', 'unused')
    def broker(operation, **args):
        state = boundary.worker_state()
        return controller.handle(dict(args, operation=operation, task=state['task'], run=state['run'], claim=state['claim']))
    def environment(tid, run):
        return patch.dict(os.environ, HERMES_KANBAN_TASK=tid, HERMES_KANBAN_DB=str(board / 'kanban.db'),
            HERMES_KANBAN_WORKSPACE=str(board / 'workspaces' / tid), HERMES_KANBAN_RUN_ID=str(run.current_run_id), HERMES_KANBAN_CLAIM_LOCK=run.claim_lock)
    def text(extra=''):
        decision='\n```json\n'+json.dumps(dict(head_sha='a'*40,base_sha='b'*40,decision='approve',findings=[]))+'\n```'
        return digest + '\n' + '\n'.join('## ' + heading + '\nSpecific decisions, criteria and risk mitigations.' for heading in SECTIONS) + extra + (decision if cards[tid].get('scope')=='pr_review' else '')
    with patch.object(boundary, 'call', broker):
        import tools.kanban_tools
        from tools.registry import registry
        kb.unblock_task(db, unknown)
        assert kb.claim_task(db, unknown, claimer='not-permitted') is None
        for tid, card in cards.items():
            kb.unblock_task(db, tid)
            author = kb.claim_task(db, tid, claimer='author')
            with environment(tid, author):
                assert 'PLANNING ONLY' in kb.build_worker_context(db, tid)
                from model_tools import get_tool_definitions
                names = {d['function']['name'] for d in get_tool_definitions(['kanban'], quiet_mode=True)}
                assert {'planning_read', 'planning_write', 'kanban_request_review'} <= names, names
                assert 'terminal' not in names and 'kanban_complete' not in names
                shown = json.loads(registry.dispatch('kanban_show', dict(task_id=tid)))
                assert 'PLANNING ONLY' in shown['instructions'], shown
                assert json.loads(registry.dispatch('terminal', {'command': 'id'}))['error'] == 'operation_forbidden'
                inputs=json.loads(registry.dispatch('planning_read', {}))
                if card.get('scope')=='pr_review':
                    for page in range(inputs['pr_packet']['page_count']): registry.dispatch('planning_read',dict(page=page))
                else: assert inputs['brief']==brief
                assert 'written' in json.loads(registry.dispatch('planning_write', dict(content=text())))
                assert kb.request_review(db, tid, reviewer=card['reviewer'], expected_run_id=author.current_run_id)
            reviewer = kb.claim_review_task(db, tid, claimer='reviewer')
            with environment(tid, reviewer):
                names = {d['function']['name'] for d in get_tool_definitions(['kanban'], quiet_mode=True)}
                assert {'planning_read', 'review_inspect', 'review_validate', 'kanban_complete'} <= names, names
                assert 'planning_write' not in names and 'terminal' not in names
                assert json.loads(registry.dispatch('planning_write', dict(content=text('unauthorized'))))['error'] == 'operation_forbidden'
                assert json.loads(registry.dispatch('review_probe_write', {}))['error'] == 'operation_forbidden'
                revision = broker('inspect')['delivery']['revision']
                if card.get('scope')=='pr_review':
                    for page in range(broker('planning_read')['pr_packet']['page_count']): broker('planning_read',page=page)
                registry.dispatch('review_validate', dict(revision=revision))
                assert kb.request_changes(db, tid, reason='Clarify concurrent room entry acceptance criteria.', expected_run_id=reviewer.current_run_id)[0]
            author = kb.claim_task(db, tid, claimer='rework')
            assert author.assignee == card['author']
            with environment(tid, author):
                assert boundary.worker_state()['mode'] == 'implementation'
                if card.get('scope')=='pr_review':
                    for page in range(broker('planning_read')['pr_packet']['page_count']): broker('planning_read',page=page)
                registry.dispatch('planning_write', dict(content=text('Revision addresses independent review.')))
                assert kb.request_review(db, tid, reviewer=card['reviewer'], expected_run_id=author.current_run_id)
            reviewer = kb.claim_review_task(db, tid, claimer='reviewer2')
            with environment(tid, reviewer):
                if card.get('scope')=='pr_review':
                    for page in range(broker('planning_read')['pr_packet']['page_count']): broker('planning_read',page=page)
                fresh = broker('inspect')['delivery']['revision']; assert fresh != revision
                try: broker('approve', revision=revision)
                except ValueError: pass
                else: raise AssertionError('obsolete approval accepted')
                registry.dispatch('review_validate', dict(revision=fresh))
                if card.get('scope')=='pr_review':
                    import publication_merge as publication
                    import subprocess
                    execution=Path(tmp)/'execution.json'
                    execution.write_text(json.dumps(dict(attempt='planning-native',product_dispatch_enabled=False,implementation_dispatch_enabled=False)))
                    def fixed_publisher(command,**kwargs):
                        assert '--read-only' in command and '--cap-drop=ALL' in command
                        assert '--cap-add=DAC_READ_SEARCH' in command
                        assert not any('docker.sock' in arg for arg in command)
                        if '--preflight' in command:
                            assert '--network=none' in command
                            return subprocess.CompletedProcess(command,0,json.dumps(dict(passed=True,files=[],policy='native-fixture')),'')
                        assert '--network=bridge' in command
                        if '--policy-preflight' in command:
                            return subprocess.CompletedProcess(command,0,json.dumps(dict(passed=True,merge_method='merge')),'')
                        evidence=publication.context(tid,reviewer.current_run_id,fresh,reviewer.claim_lock)
                        assert evidence['pr']==14
                        try: publication.context(tid,reviewer.current_run_id,fresh,'wrong-claim')
                        except PermissionError: pass
                        else: raise AssertionError('stale claim accepted for merge')
                        result=dict(merged=True,pr=14,head='a'*40,base='b'*40,merge_commit='c'*40,
                                    task=tid,review_run=reviewer.current_run_id,revision=fresh)
                        return subprocess.CompletedProcess(command,0,json.dumps(result),'')
                    with patch.multiple(publication,BOARD=board,ROOT=private,EXECUTION=execution,ATTEMPT='planning-native'), patch('review_controller.bounded_run',fixed_publisher):
                        assert kb.complete_task(db, tid, expected_run_id=reviewer.current_run_id, result='Independent review and fixed integration accepted', fire_lifecycle_hook=False)
                    assert controller.db.execute('SELECT receipt FROM publication_intents WHERE task=?',(tid,)).fetchone()[0]
                else:
                    assert kb.complete_task(db, tid, expected_run_id=reviewer.current_run_id, result='Independent document review passed', fire_lifecycle_hook=False)
            assert kb.get_task(db, tid).status == 'done'
            controller.store.load('planning-native', tid, revision)
    db.close(); controller.db.close()
print('PASS native planning: four review mappings, private drafts/snapshots, denied writes/commands, author rework, stale approval rejected; unknown implementation card cannot claim.')
