import importlib.util
import os
from pathlib import Path
import unittest
import uuid
import tempfile
import hashlib
import json
import sys
import types
from unittest.mock import patch

with patch.dict(os.environ, {'BROKER_WORKER_IMAGE': 'sha256:' + 'a' * 64}):
    spec = importlib.util.spec_from_file_location('broker', Path(__file__).parents[1] / 'broker/server.py')
    broker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(broker)


class BrokerTests(unittest.TestCase):
    def test_oversized_review_uses_exact_frozen_registered_instruction(self):
        instruction='Review every criterion.\nCONTROLLER VERIFIED TDD RECEIPT: receipt'
        marker='a'*64
        data=dict(target='reviewer',reviewer='reviewer',author='author',dispatch_stage='ready_review',
            dispatch_marker=marker,wakeup_id='wake',instruction=instruction,
            evidence=dict(baseline_tests_intact=True,manifest_sha256='b'*64,
                          tdd=dict(green=dict(executed_by_controller=True))))
        with broker.db() as con:
            con.execute('CREATE TABLE delivery_handoffs(source_task TEXT,issue_id TEXT,stage TEXT,owner TEXT,data TEXT)')
            con.execute('CREATE TABLE snapshots(task_id TEXT,status TEXT)')
            con.execute('INSERT INTO snapshots VALUES (?,?)',('source','complete'))
            con.execute('INSERT INTO delivery_handoffs VALUES (?,?,?,?,?)',
                        ('source','issue','awaiting_acceptance','reviewer',json.dumps(data)))
        exact='DELIVERY_HANDOFF '+marker+'\n'+instruction
        note=exact+'\nNative ambient event metadata '+ 'x'*4000
        # Native task_binding returns task_id, not the task-record field id.
        task=dict(task_id='task',agent_id='reviewer',wakeup_id='wake')
        self.assertEqual(broker.compact_review_note(dict(id='issue'),task,note),exact)
        self.assertEqual(broker.compact_review_note(dict(id='issue'),task,exact),exact)
        for wrong in ({**task,'agent_id':'author'},{**task,'wakeup_id':'stale'}):
            with self.assertRaises(ValueError):broker.compact_review_note(dict(id='issue'),wrong,note)
        with self.assertRaises(ValueError):
            broker.compact_review_note(dict(id='issue'),task,note.replace('every','some'))
        with broker.db() as con:con.execute("UPDATE snapshots SET status='pending'")
        with self.assertRaises(ValueError):broker.compact_review_note(dict(id='issue'),task,note)
    def test_current_cto_diagnosis_excludes_historical_issue_and_stale_wakeup(self):
        from broker import harness_repair_task as h
        note='CTO review current response contract\nDELIVERY_CURRENT_HARNESS_DIAGNOSIS_V1\n'
        state={'issue_id':'issue','stage':'awaiting_cto_diagnosis','diagnosis':{'wakeup_id':'wake'},'functional_diagnosis':{'note':note}}
        with broker.db() as con:
            h.initialize(con)
            con.execute('INSERT INTO harness_repair_tasks VALUES (?,?,?)',('source',json.dumps({'cto':'cto'}),json.dumps(state)))
        issue={'id':'issue','title':'Historical syntax job','description':'OLD_CTO_DIRECTIVE syntax broken'}
        task={'id':'task','agent_id':'cto','issue_id':'issue','wakeup_id':'wake','handoff_note':note}
        frame={'method':'session/prompt','params':{'prompt':[]}}
        text=broker.native_task_prompt(frame,'planning',issue,task)['params']['prompt'][0]['text']
        self.assertNotIn('OLD_CTO_DIRECTIVE',text);self.assertIn('current response contract',text)
        with self.assertRaises(ValueError):broker.native_task_prompt(frame,'planning',issue,dict(task,wakeup_id='stale'))
    def test_active_maintenance_context_replaces_stale_issue_brief_and_fails_closed(self):
        from broker import harness_repair_task as h
        with broker.db() as con:
            con.execute('CREATE TABLE delivery_routes(issue_id TEXT PRIMARY KEY,config TEXT)')
        frame={'method':'session/prompt','params':{'sessionId':'session','prompt':[{'type':'text','text':'caller'}]}}
        issue={'id':'issue','title':'Legacy task','description':'HISTORICAL: fix invalid syntax and implement C10 now.'}
        task={'handoff_note':'OLD_DIRECTIVE old/new edit\nDELIVERY_DRIVER_CHECKPOINT_V3\n'}
        with patch.object(h,'current_maintenance_context',return_value={'title':'Active maintenance','description':'CURRENT C09 payload envelope only.','handoff_note':'CURRENT C09 line ranges'}):
            text=broker.native_task_prompt(frame,'implementation',issue,task)['params']['prompt'][0]['text']
        self.assertIn('CURRENT C09 payload envelope only.',text)
        self.assertNotIn('HISTORICAL:',text);self.assertNotIn('invalid syntax',text)
        self.assertNotIn('OLD_DIRECTIVE',text);self.assertIn('CURRENT C09 line ranges',text)
        with patch.object(h,'current_maintenance_context',side_effect=ValueError('stale wakeup')):
            with self.assertRaises(ValueError):broker.native_task_prompt(frame,'implementation',issue,task)
    def test_close_intent_is_committed_before_container_removal(self):
        with broker.db() as con:
            con.execute('CREATE TABLE grants(digest TEXT,request_id TEXT,deadline REAL)')
            con.execute('CREATE TABLE leases(request_id TEXT,name TEXT,status TEXT,deadline REAL)')
            con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT)')
            con.execute('INSERT INTO grants VALUES (?,?,?)',
                        (hashlib.sha256(b'close-token').hexdigest(),'request',9999999999))
            con.execute('INSERT INTO leases VALUES (?,?,?,?)',
                        ('request','owned-job','running',9999999999))
        def interrupted_remove(name, request):
            with broker.db() as con:
                self.assertEqual(con.execute('SELECT status FROM leases').fetchone()[0], 'closing')
            raise OSError('interrupted after durable intent')
        with patch.dict(broker.SESSIONS, {'request': object()}), \
             patch.object(broker, 'remove_owned', side_effect=interrupted_remove):
            with self.assertRaises(OSError):broker.session_operation('close-token', {}, close=True)
        with broker.db() as con:
            self.assertEqual(con.execute('SELECT status FROM leases').fetchone()[0], 'closing')
        with patch.object(broker,'remove_owned') as remove:
            broker.tick()
            remove.assert_called_once_with('owned-job','request')
        with broker.db() as con:
            self.assertEqual(con.execute('SELECT status FROM leases').fetchone()[0], 'closed')
        self.assertEqual(broker.session_operation('close-token', {}, close=True), {'status':'closed'})

    def test_missing_worker_without_close_intent_remains_lost(self):
        with broker.db() as con:
            con.execute('CREATE TABLE leases(request_id TEXT,name TEXT,status TEXT,deadline REAL,scenario TEXT)')
            con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT)')
            con.execute('INSERT INTO leases VALUES (?,?,?,?,?)',('request','owned-job','running',9999999999,'acp-session'))
        with patch.object(broker,'docker',return_value=None), patch.object(broker,'remove_owned'):
            broker.tick()
        with broker.db() as con:
            self.assertEqual(con.execute('SELECT status FROM leases').fetchone()[0], 'lost')

    def test_compact_diagnosis_requires_registered_owner_and_omits_ambient_brief(self):
        marker='a'*64
        instruction='DELIVERY_UNCHANGED_CORRECTION_DIAGNOSIS_V1\nDELIVERY_STRUCTURED_DECISION_V1:technical\nDecide concisely'
        data=dict(target='cto',dispatch_stage='diagnose_cto',dispatch_marker=marker,wakeup_id='wake',
                  instruction=instruction,evidence=dict(correction_diagnosis=dict(category='unchanged_rejected_delivery')))
        with broker.db() as con:
            con.execute('CREATE TABLE delivery_handoffs(issue_id TEXT,stage TEXT,owner TEXT,data TEXT)')
            con.execute('INSERT INTO delivery_handoffs VALUES(?,?,?,?)',('issue','awaiting_acceptance','cto',json.dumps(data)))
        issue=dict(id='issue',title='Ambient title',description='AMBIENT_PRIVATE_BACKLOG')
        task=dict(agent_id='cto',wakeup_id='wake',handoff_note='DELIVERY_HANDOFF '+marker+'\n'+instruction)
        frame=dict(method='session/prompt',params=dict(prompt=[]))
        prompt=broker.native_task_prompt(frame,'planning',issue,task)['params']['prompt'][0]['text']
        self.assertEqual(prompt,instruction);self.assertNotIn('AMBIENT_PRIVATE_BACKLOG',prompt)
        for wrong in ({**task,'agent_id':'author'},{**task,'wakeup_id':'old'}):
            with self.assertRaises(ValueError):broker.native_task_prompt(frame,'planning',issue,wrong)
        with broker.db() as con:con.execute("UPDATE delivery_handoffs SET stage='approved'")
        with self.assertRaises(ValueError):broker.native_task_prompt(frame,'planning',issue,task)

    def test_validation_jobs_for_same_source_have_distinct_cleanup_identity(self):
        for kind in ('suite','validate'):
            names={broker.validation_job_name(kind,'same-source') for _ in range(20)}
            self.assertEqual(len(names),20)
            self.assertTrue(all(n.startswith(broker.PREFIX+'-'+kind+'-same-source-') for n in names))
        with self.assertRaises(ValueError):broker.validation_job_name('arbitrary','same-source')

    def test_artifact_gate_is_opt_in_and_uses_registered_grants_only(self):
        with patch.dict(os.environ, {'BROKER_TEST_ARTIFACT_GATE': '0'}):
            self.assertEqual(broker.test_artifact_phase_context('issue', 'author'), '')
        with broker.db() as con:
            con.execute('CREATE TABLE delivery_routes(issue_id TEXT PRIMARY KEY,config TEXT)')
            con.execute('CREATE TABLE issue_editables(issue_id TEXT,path TEXT)')
            con.execute('INSERT INTO delivery_routes VALUES (?,?)', ('issue', json.dumps({
                'enabled': True, 'test_first': True, 'author': 'author',
                'test_first_files': ['tests/test_new.py']})))
            con.executemany('INSERT INTO issue_editables VALUES (?,?)',
                [('issue', '/workspace/app.py'), ('issue', '/workspace/tests/test_new.py')])
        with patch.dict(os.environ, {'BROKER_TEST_ARTIFACT_GATE': '1'}):
            marker = broker.test_artifact_phase_context('issue', 'author')
            self.assertIn('DELIVERY_TEST_ARTIFACT_V1:/workspace/tests/test_new.py', marker)
            self.assertIn('DELIVERY_TEST_SOURCE_V1:/workspace/app.py', marker)
            self.assertIn('\nDELIVERY_DETERMINISTIC_READ_V1\n', marker)
            with self.assertRaisesRegex(ValueError, 'exact registered'):
                broker.test_artifact_phase_context('issue', 'wrong-author')
            with broker.db() as con:
                con.execute('UPDATE delivery_routes SET config=?', (json.dumps({
                    'enabled':False,'test_first':True,'author':'author','test_first_files':['tests/test_new.py']}),))
            with self.assertRaisesRegex(ValueError, 'exact registered'):
                broker.test_artifact_phase_context('issue','author')
            from broker.harness_repair_task import initialize
            with broker.db() as con:
                initialize(con)
                con.execute('CREATE TABLE test_revision_trials(issue_id TEXT,config TEXT)')
                con.execute('INSERT INTO test_revision_trials VALUES (?,?)',('issue',json.dumps({'harness_maintenance_only':True})))
                con.execute('INSERT INTO harness_repair_tasks VALUES (?,?,?)',('source',json.dumps({'author':'author'}),json.dumps({
                    'issue_id':'issue','stage':'awaiting_author','cto_task':'cto','delivery_approval':False})))
            self.assertIn('DELIVERY_TEST_ARTIFACT_V1:',broker.test_artifact_phase_context('issue','author'))
            with broker.db() as con:
                con.execute("DELETE FROM issue_editables WHERE path='/workspace/tests/test_new.py'")
            with self.assertRaisesRegex(ValueError, 'existing editable'):
                broker.test_artifact_phase_context('issue', 'author')

    def test_qa_planning_prompt_uses_read_artifacts_without_wrong_decision_schema(self):
        from broker import qa_artifacts
        config = {'request': {'read_files': ['app/static/app.js']}}
        frame = {'method': 'session/prompt', 'params': {'prompt': [{'type': 'text','text': 'run'}]}}
        issue = {'id': 'issue', 'title': 'QA incident', 'description': 'QA_DIAGNOSIS_V1 diagnose read-only'}
        task = {'id': 'task', 'agent_id': 'lead'}
        with patch.object(qa_artifacts, 'config_for', return_value=config):
            result = broker.native_task_prompt(frame,'planning',issue,task)
        text = result['params']['prompt'][0]['text']
        self.assertIn('/evidence/previous/qa.json', text)
        self.assertIn('/evidence/previous/scenario.py', text)
        self.assertIn('limit=60', text)
        self.assertIn('repository-relative paths', text)
        self.assertIn('root_cause max1000', text)
        self.assertIn('DELIVERY_STRUCTURED_DECISION_V1:qa', text)
        self.assertIn('/evidence/candidate/app/static/app.js', text)
        self.assertNotIn('DELIVERY_STRUCTURED_DECISION_V1:technical', text)
        with patch.object(qa_artifacts,'config_for',return_value=None):
            with self.assertRaisesRegex(ValueError,'registration'):
                broker.native_task_prompt(frame,'planning',issue,task)
    def test_worker_image_is_resolvable_before_accepting_tasks(self):
        with patch.object(broker, 'docker', return_value={'Id': broker.IMAGE}):
            self.assertEqual(broker.verify_worker_image(), broker.IMAGE)
        for details in (None, {'Id': 'sha256:' + 'b' * 64}):
            with patch.object(broker, 'docker', return_value=details):
                with self.assertRaisesRegex(ValueError, 'does not resolve'):
                    broker.verify_worker_image()
        with patch.object(broker, 'IMAGE', 'mutable:latest'), patch.object(broker, 'docker') as request:
            with self.assertRaisesRegex(ValueError, 'immutable Docker image ID'):
                broker.verify_worker_image()
            request.assert_not_called()

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        state = patch.object(broker, 'STATE', Path(directory.name))
        state.start()
        self.addCleanup(state.stop)

    def test_portable_node_test_command_is_exact_and_immutable(self):
        issue = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(broker, 'STATE', Path(directory)), \
                patch.object(broker, 'issue_base', return_value={'base_sha': 'a' * 40}):
            with broker.db() as con:
                con.execute('CREATE TABLE issue_editables(issue_id TEXT,path TEXT,PRIMARY KEY(issue_id,path))')
                con.execute('CREATE TABLE issue_test_commands(issue_id TEXT PRIMARY KEY,command TEXT)')
            payload = {'issue_id': issue, 'paths': ['/workspace/app.js',
                                                    '/workspace/tests/app.test.js'],
                       'test_command': 'cd /workspace && node --test 2>&1'}
            self.assertEqual(broker.register_issue_editables(payload)['test_command'],
                             payload['test_command'])
            with self.assertRaisesRegex(ValueError, 'qualified policy'):
                broker.register_issue_editables({**payload,
                    'test_command': 'cd /workspace && node --test; id 2>&1'})
            with self.assertRaisesRegex(ValueError, 'immutable'):
                broker.register_issue_editables({**payload,
                    'test_command': 'cd /workspace && PYTHONDONTWRITEBYTECODE=1 '
                                    'python3 -m unittest discover -s tests -q 2>&1'})

    def test_test_first_file_fence_changes_with_controller_red(self):
        files = ['/workspace/app.py', '/workspace/tests/test_new.py']
        route = {'test_first': True, 'test_first_files': ['tests/test_new.py']}
        self.assertEqual(broker.phase_editables(files, route, 'tests_only'),
                         ['/workspace/tests/test_new.py'])
        self.assertEqual(broker.phase_editables(files, route, 'implement_after_red'),
                         ['/workspace/app.py'])
        with self.assertRaisesRegex(ValueError, 'phase missing'):
            broker.phase_editables(files, route, None)
        with self.assertRaisesRegex(ValueError, 'review required'):
            broker.phase_editables(files, route, 'await_test_review')

    def test_markdown_review_decision_is_recognized_without_prose_guessing(self):
        self.assertEqual(broker.review_decisions([{'type':'text', 'content':'**Decision: APPROVE**'}]), ['APPROVE'])
        self.assertEqual(broker.review_decisions([{'type':'text', 'content':'Decision: REQUEST_CHANGES;Reason: test missing'}]), ['REQUEST_CHANGES'])
        self.assertEqual(broker.review_decisions([{'type':'text', 'content':'## Review verdict: **APPROVE**\nTests passed.'}]), ['APPROVE'])
        self.assertEqual(broker.review_decisions([{'type':'text', 'content':'**Verdict: APPROVE**\nTests passed.'}]), ['APPROVE'])
        self.assertEqual(broker.review_decisions([{'type':'text', 'content':'I might APPROVE later'}]), [])
        self.assertEqual(broker.review_decisions([{'type':'thinking', 'content':'Decision: APPROVE'}]), [])

    def test_native_prompt_contains_issue_and_handoff_without_cli_dependency(self):
        frame = {'jsonrpc': '2.0', 'id': 1, 'method': 'session/prompt',
                 'params': {'sessionId': 'session', 'prompt': [{'type': 'text', 'text': 'Run multica issue get'}]}}
        issue = {'title': 'Cube feature', 'description': 'Add cube(value) with TDD.'}
        task = {'handoff_note': 'Reviewer requested test_cube_negative.'}
        result = broker.native_task_prompt(frame, 'implementation', issue, task)
        prompt = result['params']['prompt'][0]['text']
        self.assertIn('Add cube(value) with TDD.', prompt)
        self.assertIn('test_cube_negative', prompt)
        self.assertNotIn('Run multica issue get', prompt)
        self.assertIn('Red-Green-Refactor', prompt)

    def test_native_prompt_resolves_only_registered_immutable_context(self):
        from execution_context import freeze, reference
        capsule = freeze('Complete requirement. ' * 240, 'Exact independent review criteria.')
        with broker.db() as con:
            con.execute('CREATE TABLE delivery_routes(issue_id TEXT PRIMARY KEY,config TEXT)')
            con.execute('INSERT INTO delivery_routes VALUES (?,?)', ('issue', json.dumps({
                'enabled': True, 'author': 'author', 'reviewer': 'reviewer',
                'execution_context': capsule})))
        frame = {'method': 'session/prompt', 'params': {'sessionId': 's', 'prompt': []}}
        issue = {'id': 'issue', 'title': 'Feature', 'description': reference(capsule, 'implementation')}
        task = {'id': 'context-task', 'agent_id': 'author', 'handoff_note': ''}
        prompt = broker.native_task_prompt(frame, 'implementation', issue, task)['params']['prompt'][0]['text']
        self.assertIn(capsule['description'], prompt)
        with broker.db() as con:
            proof = json.loads(con.execute('SELECT receipt FROM execution_context_presentations WHERE task_id=?',
                                          ('context-task',)).fetchone()[0])
        self.assertEqual(proof['context_sha256'], capsule['sha256'])
        self.assertIs(proof['delivery_approval'], False)
        with self.assertRaises(ValueError):
            broker.native_task_prompt(frame, 'implementation', issue, {**task, 'agent_id': 'reviewer'})

    def test_test_first_prompt_changes_only_after_controller_red(self):
        with broker.db() as con:
            con.execute('CREATE TABLE delivery_routes(issue_id TEXT PRIMARY KEY,config TEXT)')
            con.execute('CREATE TABLE test_first_red(issue_id TEXT PRIMARY KEY,task_id TEXT)')
            con.execute('INSERT INTO delivery_routes VALUES (?,?)',
                        ('issue', json.dumps({'test_first': True})))
        frame = {'method': 'session/prompt', 'params': {'sessionId': 's', 'prompt': []}}
        issue = {'id': 'issue', 'title': 'Feature', 'description': 'Provide tests and implementation.'}
        task = {'handoff_note': ''}
        first = broker.native_task_prompt(frame, 'implementation', issue, task)
        self.assertIn('TEST-FIRST PHASE', first['params']['prompt'][0]['text'])
        self.assertIn('Do not create or modify application code',
                      first['params']['prompt'][0]['text'])
        with broker.db() as con:
            con.execute('INSERT INTO test_first_red VALUES (?,?)', ('issue', 'test-task'))
        with self.assertRaisesRegex(ValueError, 'independent new-test review'):
            broker.native_task_prompt(frame, 'implementation', issue, task)
        with broker.db() as con:
            con.execute('INSERT INTO test_revision_trials VALUES (?,?,?,?)',
                        ('issue', None, '{}', json.dumps({'status': 'approved'})))
        second = broker.native_task_prompt(frame, 'implementation', issue, task)
        self.assertIn('IMPLEMENTATION PHASE', second['params']['prompt'][0]['text'])
        self.assertIn('Do not edit or replace any tests', second['params']['prompt'][0]['text'])

    def test_planning_prompt_has_brief_but_no_execution_claim(self):
        self.assertEqual(broker.phase_editables(['/workspace/app.py'],
            {'test_first': True}, 'await_test_review', mode='planning'), [])
        with self.assertRaisesRegex(ValueError, 'review required'):
            broker.phase_editables(['/workspace/app.py'], {'test_first': True,
                'test_first_files': ['test_new.py']}, 'await_test_review')
        frame = {'jsonrpc': '2.0', 'id': 1, 'method': 'session/prompt',
                 'params': {'sessionId': 's', 'prompt': []}}
        issue = {'title': 'Feedback board brief',
                 'description': 'Create and complete suggestions across two browsers.'}
        prompt = broker.native_task_prompt(frame, 'planning', issue,
                                           {'handoff_note': ''})['params']['prompt'][0]['text']
        self.assertIn(issue['description'], prompt)
        self.assertIn('no repository, shell, file', prompt)
        self.assertIn('Do not claim to have created cards', prompt)
        self.assertNotIn('DELIVERY_DETERMINISTIC_READ_V1',prompt)

    def test_artifact_planning_accepts_bounded_native_wrapper_not_write_access(self):
        frame = {'method': 'session/prompt', 'params': {}}
        issue = {'title': 'Diagnosis', 'description': 'Inspect the immutable failed delivery.'}
        note = '/evidence/candidate ' + 'x' * 4200
        prompt = broker.native_task_prompt(frame, 'planning', issue,
                                           {'handoff_note': note})['params']['prompt'][0]['text']
        self.assertIn('using file-read tools', prompt)
        self.assertIn('No shell, writes', prompt)
        self.assertIn('DELIVERY_DETERMINISTIC_READ_V1',prompt)
        with self.assertRaisesRegex(ValueError, 'handoff note'):
            broker.native_task_prompt(frame, 'planning', issue, {'handoff_note': 'x' * 8001})

    def test_verified_correction_overrides_initial_wait_for_review(self):
        frame = {'method': 'session/prompt', 'params': {'sessionId': 's', 'prompt': []}}
        issue = {'title': 'Double', 'description': 'Initially add only the positive test. Wait for reviewer request.'}
        task = {'handoff_note': 'Wakeup triggered.'}
        correction = {'review_task_id': 'review-1', 'finding': 'add test_double_negative'}
        prompt = broker.native_task_prompt(frame, 'implementation', issue, task, correction)['params']['prompt'][0]['text']
        self.assertIn('has ALREADY requested', prompt)
        self.assertIn('Do not wait for another request', prompt)
        self.assertIn('add test_double_negative', prompt)
        self.assertLess(prompt.index('CURRENT CONTROLLER-VERIFIED'), prompt.index('Initially add only'))

    def test_long_child_brief_requires_controller_lineage_and_remains_bounded(self):
        frame = {'method': 'session/prompt', 'params': {}}
        issue = {'id': 'child', 'title': 'Test revision', 'description': 'x' * 5941}
        for mode in ('implementation', 'review'):
            with patch.object(broker, 'has_verified_revision_brief', return_value=False):
                with self.assertRaisesRegex(ValueError, 'bounded issue brief'):
                    broker.native_task_prompt(frame, mode, issue, {'handoff_note': ''})
            with patch.object(broker, 'has_verified_revision_brief', return_value=True), \
                    patch.object(broker, 'implementation_phase', return_value='tests_only'):
                prompt = broker.native_task_prompt(frame, mode, issue, {'handoff_note': ''})
                self.assertIn(issue['description'], prompt['params']['prompt'][0]['text'])
                with self.assertRaisesRegex(ValueError, 'bounded issue brief'):
                    broker.native_task_prompt(frame, mode, {**issue, 'description': 'x' * 8001}, {'handoff_note': ''})
                with self.assertRaisesRegex(ValueError, 'task prompt too large'):
                    broker.native_task_prompt(frame, mode, issue, {'handoff_note': 'x' * 3999})

    def test_child_brief_exception_reuses_frozen_lineage_checks(self):
        from broker import test_revision_review
        with broker.db() as con:
            con.execute('CREATE TABLE test_revision_trials(issue_id TEXT,parent_issue TEXT,config TEXT)')
            con.execute('INSERT INTO test_revision_trials VALUES (?,?,?)',
                        ('child', 'parent', json.dumps({'parent_issue': 'parent'})))
        with patch.object(test_revision_review, 'seed_source', return_value={'mount': 'verified'}) as proof:
            self.assertTrue(broker.has_verified_revision_brief('child'))
            proof.assert_called_once()
        with patch.object(test_revision_review, 'seed_source', side_effect=ValueError('revision seed lineage mismatch')):
            with self.assertRaisesRegex(ValueError, 'lineage mismatch'):
                broker.has_verified_revision_brief('child')
        self.assertFalse(broker.has_verified_revision_brief('unknown'))

    def test_prompt_bounds_has_a_precise_safe_failure_category(self):
        self.assertEqual(broker.failure_category(ValueError('bounded issue brief required')), 'native_prompt_bounds')
        self.assertEqual(broker.failure_category(ValueError('private error contents')), 'broker_internal')

    def test_correction_requires_matching_wakeup_and_issue(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(broker, 'STATE', Path(directory)):
            with broker.db() as con:
                con.execute('CREATE TABLE change_handoffs(review_task_id TEXT, reviewer_wakeup_id TEXT, implementer_wakeup_id TEXT)')
                con.execute('CREATE TABLE review_findings(review_task_id TEXT, finding TEXT)')
                con.execute('CREATE TABLE reviews(review_task_id TEXT, source_task_id TEXT)')
                con.execute('CREATE TABLE native_bindings(task_id TEXT, issue_id TEXT)')
                con.execute('INSERT INTO change_handoffs VALUES (?,?,?)', ('review', 'review-wakeup', 'author-wakeup'))
                con.execute('INSERT INTO review_findings VALUES (?,?)', ('review', 'add test_double_negative'))
                con.execute('INSERT INTO reviews VALUES (?,?)', ('review', 'source'))
                con.execute('INSERT INTO native_bindings VALUES (?,?)', ('source', 'issue-1'))
            self.assertEqual(broker.verified_correction({'wakeup_id': 'author-wakeup'}, 'issue-1'),
                             {'review_task_id': 'review', 'finding': 'add test_double_negative'})
            self.assertIsNone(broker.verified_correction({'wakeup_id': 'author-wakeup'}, 'issue-2'))
            self.assertIsNone(broker.verified_correction({'wakeup_id': 'unregistered'}, 'issue-1'))

    def test_cancelled_native_task_retires_owned_lease(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(broker, 'STATE', Path(directory)):
            (Path(directory) / 'native.json').write_text('{}')
            with broker.db() as con:
                con.execute('CREATE TABLE leases(request_id TEXT, scenario TEXT, name TEXT, status TEXT, deadline REAL)')
                con.execute('CREATE TABLE native_bindings(request_id TEXT, task_id TEXT, agent_id TEXT)')
                con.execute('INSERT INTO leases VALUES (?,?,?,?,?)',
                            ('request', 'acp-session', 'owned-job', 'running', 9999999999))
                con.execute('INSERT INTO native_bindings VALUES (?,?,?)',
                            ('request', 'task', 'agent'))
            fake_native = types.SimpleNamespace(task_record=lambda *_: {'status': 'cancelled'})
            with patch.dict(sys.modules, {'native': fake_native}), \
                 patch.object(broker, 'remove_owned') as remove, \
                 patch.object(broker, 'docker') as docker:
                broker.tick()
            remove.assert_called_once_with('owned-job', 'request')
            docker.assert_not_called()
            with broker.db() as con:
                self.assertEqual(con.execute('SELECT status FROM leases').fetchone()[0], 'cancelled')

    def test_truncated_verbose_test_receipt_requires_real_call_and_zero_exit(self):
        call = {'type':'tool_use', 'tool':'terminal', 'call_id':'abc',
                'input':{'text':'PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v'}}
        result = {'type':'tool_result', 'tool':'terminal', 'call_id':'abc',
                  'output':'terminal result\n- **output:** test_one ... ok\ntest_two ... ok\ntest_three ... ok\n... truncated\n- **exit_code:** 0'}
        self.assertTrue(broker.observed_passing_unittest([call, result]))
        self.assertFalse(broker.observed_passing_unittest([result]))
        self.assertFalse(broker.observed_passing_unittest([call, {**result, 'output':result['output'].replace('0', '1')}]))
        self.assertFalse(broker.observed_passing_unittest([call, {**result, 'output':result['output'].replace('test_three ... ok', 'test_three ... FAILED')}]))

    def test_old_approval_cannot_be_replayed_after_reassignment(self):
        old_task, old_source, new_source, reviewer = [str(uuid.uuid4()) for _ in range(4)]
        with tempfile.TemporaryDirectory() as directory, patch.object(broker, 'STATE', Path(directory)):
            with broker.db() as con:
                con.execute('CREATE TABLE reviews(review_task_id TEXT PRIMARY KEY,source_task_id TEXT,reviewer_agent_id TEXT,manifest_sha256 TEXT,status TEXT)')
                con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT)')
                con.execute('CREATE TABLE grants(request_id TEXT,mode TEXT,attempt INTEGER)')
                con.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
                con.execute('CREATE TABLE review_assignments(review_agent_id TEXT,source_task_id TEXT,volume TEXT)')
                con.execute('CREATE TABLE review_bindings(request_id TEXT,source_task_id TEXT,volume TEXT)')
                con.execute('CREATE TABLE snapshots(task_id TEXT,volume TEXT,status TEXT)')
                con.execute('INSERT INTO reviews VALUES (?,?,?,?,?)', (old_task, old_source, reviewer, 'a'*64, 'approved'))
                con.execute('INSERT INTO native_bindings VALUES (?,?,?)', ('old-request', old_task, reviewer))
                con.execute('INSERT INTO grants VALUES (?,?,?)', ('old-request', 'review', 1))
                con.execute('INSERT INTO leases VALUES (?,?)', ('old-request', 'closed'))
                con.execute('INSERT INTO review_bindings VALUES (?,?,?)', ('old-request', old_source, 'old-volume'))
                con.execute('INSERT INTO review_assignments VALUES (?,?,?)', (reviewer, new_source, 'new-volume'))
                con.execute('INSERT INTO snapshots VALUES (?,?,?)', (new_source, 'new-volume', 'complete'))
            with patch.dict(sys.modules, {'native': types.SimpleNamespace(task_record=None, task_messages=None)}):
                with self.assertRaisesRegex(ValueError, 'stale review binding'):
                    broker.record_review({'review_task_id': old_task})

    def test_late_review_completion_cannot_approve_after_reassignment(self):
        late_task, old_source, new_source, reviewer = [str(uuid.uuid4()) for _ in range(4)]
        with tempfile.TemporaryDirectory() as directory, patch.object(broker, 'STATE', Path(directory)):
            with broker.db() as con:
                con.execute('CREATE TABLE reviews(review_task_id TEXT PRIMARY KEY,source_task_id TEXT,reviewer_agent_id TEXT,manifest_sha256 TEXT,status TEXT)')
                con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT)')
                con.execute('CREATE TABLE grants(request_id TEXT,mode TEXT,attempt INTEGER)')
                con.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
                con.execute('CREATE TABLE review_assignments(review_agent_id TEXT,source_task_id TEXT,volume TEXT)')
                con.execute('CREATE TABLE review_bindings(request_id TEXT,source_task_id TEXT,volume TEXT)')
                con.execute('CREATE TABLE snapshots(task_id TEXT,volume TEXT,status TEXT)')
                con.execute('INSERT INTO native_bindings VALUES (?,?,?)', ('late-request', late_task, reviewer))
                con.execute('INSERT INTO grants VALUES (?,?,?)', ('late-request', 'review', 1))
                con.execute('INSERT INTO leases VALUES (?,?)', ('late-request', 'closed'))
                con.execute('INSERT INTO review_bindings VALUES (?,?,?)', ('late-request', old_source, 'old-volume'))
                con.execute('INSERT INTO review_assignments VALUES (?,?,?)', (reviewer, new_source, 'new-volume'))
                con.execute('INSERT INTO snapshots VALUES (?,?,?)', (new_source, 'new-volume', 'complete'))
            with patch.dict(sys.modules, {'native': types.SimpleNamespace(task_record=None, task_messages=None)}):
                with self.assertRaisesRegex(ValueError, 'stale review binding'):
                    broker.record_review({'review_task_id': late_task})
            with broker.db() as con:
                self.assertEqual(con.execute('SELECT count(*) FROM reviews').fetchone()[0], 0)

    def test_review_session_is_per_run_but_implementation_retains_issue_scope(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('native_under_test', Path(__file__).parents[1] / 'broker/native.py')
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        issue, first, second, author, reviewer, workspace = [str(uuid.uuid4()) for _ in range(6)]
        settings = {'workspace_id': workspace, 'agents': {author: 'implementation', reviewer: 'review'}}
        with patch.object(native, 'task_record', side_effect=lambda s, task, agent: {
                'id': task, 'issue_id': issue, 'status': 'running'}):
            author_first = native.task_binding(settings, first, author)['scope']
            author_second = native.task_binding(settings, second, author)['scope']
            review_first = native.task_binding(settings, first, reviewer)['scope']
            review_second = native.task_binding(settings, second, reviewer)['scope']
        self.assertEqual(author_first, author_second)
        self.assertNotEqual(review_first, review_second)

    def test_change_request_handoff_extracts_reason_not_report_prefix(self):
        report = 'Evidence: ' + 'a' * 900 + '\nDecision: REQUEST_CHANGES;Reason: add test_multiply_commutative.\n'
        self.assertEqual(broker.change_request_reason(report), 'add test_multiply_commutative.')
        self.assertEqual(broker.change_request_reason('Decision: REQUEST_CHANGES — test_multiply_commutative absent\n'),
                         'test_multiply_commutative absent')

    def test_review_uses_latest_completed_correction(self):
        first, latest, review, reviewer, issue = [str(uuid.uuid4()) for _ in range(5)]
        settings = {'agents': {'author': 'implementation', reviewer: 'review'}}
        fake_native = types.SimpleNamespace(
            task_record=lambda *_: {'id': review, 'issue_id': issue, 'status': 'running'},
            issue_task_runs=lambda *_: [
                {'id': first, 'issue_id': issue, 'agent_id': 'author', 'status': 'completed',
                 'completed_at': '2026-09-23T10:00:00Z'},
                {'id': latest, 'issue_id': issue, 'agent_id': 'author', 'status': 'completed',
                 'completed_at': '2026-09-23T11:00:00Z'}])
        order = []
        with patch.dict(sys.modules, {'native': fake_native}), \
             patch.object(broker, 'snapshot_submission', side_effect=lambda p: order.append(p['task_id'])), \
             patch.object(broker, 'assign_review', side_effect=lambda p: order.append(p['source_task_id'])):
            broker.auto_prepare_review(settings, review, reviewer)
        self.assertEqual(order, [latest, latest])

    def test_new_issue_can_use_reviewer_after_unresolved_old_issue(self):
        old_source, new_source, reviewer, author = [str(uuid.uuid4()) for _ in range(4)]
        with tempfile.TemporaryDirectory() as directory, patch.object(broker, 'STATE', Path(directory)):
            (Path(directory) / 'native.json').write_text(json.dumps({'agents': {reviewer: 'review'}}))
            with broker.db() as con:
                con.execute('CREATE TABLE snapshots(task_id TEXT,volume TEXT,status TEXT)')
                con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,scope TEXT)')
                con.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
                con.execute('CREATE TABLE review_assignments(review_agent_id TEXT,source_task_id TEXT,volume TEXT)')
                con.execute('INSERT INTO snapshots VALUES (?,?,?)', (new_source,'new-volume','complete'))
                con.execute('INSERT INTO native_bindings VALUES (?,?,?,?)', ('author-request',new_source,author,'scope'))
                con.execute('INSERT INTO review_assignments VALUES (?,?,?)', (reviewer,old_source,'old-volume'))
            result = broker.assign_review({'source_task_id':new_source,'review_agent_id':reviewer})
            self.assertEqual(result['source_task_id'], new_source)
            with broker.db() as con:
                self.assertEqual(con.execute('SELECT source_task_id FROM review_assignments').fetchone()[0], new_source)

    def test_inconclusive_review_registers_one_native_retry(self):
        task, source, reviewer, issue = [str(uuid.uuid4()) for _ in range(4)]
        with tempfile.TemporaryDirectory() as directory, patch.object(broker, 'STATE', Path(directory)):
            (Path(directory) / 'native.json').write_text(json.dumps({'agents': {reviewer: 'review'}}))
            with broker.db() as con:
                con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,scope TEXT)')
                con.execute('CREATE TABLE review_bindings(request_id TEXT,source_task_id TEXT)')
                con.execute('CREATE TABLE reviews(source_task_id TEXT,status TEXT)')
                con.execute('CREATE TABLE review_incidents(review_task_id TEXT PRIMARY KEY,reason TEXT,status TEXT,created_at REAL)')
                con.execute('CREATE TABLE review_retry_attempts(review_task_id TEXT PRIMARY KEY,attempts INTEGER)')
                con.execute('CREATE TABLE review_retry_wakeups(review_task_id TEXT PRIMARY KEY,wakeup_id TEXT)')
                con.execute('INSERT INTO native_bindings VALUES (?,?,?,?)', ('request',task,reviewer,'scope'))
                con.execute('INSERT INTO review_bindings VALUES (?,?)', ('request',source))
                con.execute('INSERT INTO review_incidents VALUES (?,?,?,?)', (task,'missing decision','open',0))
            wakeup = str(uuid.uuid4())
            fake_native = types.SimpleNamespace(
                task_record=lambda *_: {'status':'completed','issue_id':issue},
                ensure_review_retry_wakeup=unittest.mock.Mock(return_value=wakeup))
            with patch.dict(sys.modules, {'native': fake_native}):
                broker.reconcile_review_retries()
                broker.reconcile_review_retries()
            fake_native.ensure_review_retry_wakeup.assert_called_once()
            with broker.db() as con:
                self.assertEqual(con.execute('SELECT status FROM review_incidents').fetchone()[0], 'retry_queued')
                self.assertEqual(con.execute('SELECT wakeup_id FROM review_retry_wakeups').fetchone()[0], wakeup)

    def test_second_inconclusive_review_requires_escalation(self):
        first, second, source, reviewer = [str(uuid.uuid4()) for _ in range(4)]
        with tempfile.TemporaryDirectory() as directory, patch.object(broker, 'STATE', Path(directory)):
            (Path(directory) / 'native.json').write_text(json.dumps({'agents': {reviewer: 'review'}}))
            with broker.db() as con:
                con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,scope TEXT)')
                con.execute('CREATE TABLE review_bindings(request_id TEXT,source_task_id TEXT)')
                con.execute('CREATE TABLE reviews(source_task_id TEXT,status TEXT)')
                con.execute('CREATE TABLE review_incidents(review_task_id TEXT PRIMARY KEY,reason TEXT,status TEXT,created_at REAL)')
                for request, task in [('request1',first),('request2',second)]:
                    con.execute('INSERT INTO native_bindings VALUES (?,?,?,?)', (request,task,reviewer,'scope'))
                    con.execute('INSERT INTO review_bindings VALUES (?,?)', (request,source))
                con.execute('INSERT INTO review_incidents VALUES (?,?,?,?)', (second,'missing decision','open',0))
            fake_native = types.SimpleNamespace(task_record=unittest.mock.Mock(),
                                                 ensure_review_retry_wakeup=unittest.mock.Mock())
            with patch.dict(sys.modules, {'native': fake_native}):
                broker.reconcile_review_retries()
            fake_native.ensure_review_retry_wakeup.assert_not_called()
            with broker.db() as con:
                self.assertEqual(con.execute('SELECT status FROM review_incidents').fetchone()[0], 'escalation_required')

    def test_inconclusive_review_becomes_durable_incident(self):
        task = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as directory, patch.object(broker, 'STATE', Path(directory)):
            with broker.db() as con:
                con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,scope TEXT)')
                con.execute('CREATE TABLE grants(request_id TEXT,mode TEXT)')
                con.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
                con.execute('CREATE TABLE reviews(review_task_id TEXT,source_task_id TEXT)')
                con.execute('CREATE TABLE review_incidents(review_task_id TEXT PRIMARY KEY,reason TEXT,status TEXT,created_at REAL)')
                con.execute('CREATE TABLE review_bindings(request_id TEXT,source_task_id TEXT)')
                con.execute('INSERT INTO native_bindings VALUES (?,?,?,?)', ('request',task,'reviewer','scope'))
                con.execute('INSERT INTO grants VALUES (?,?)', ('request','review'))
                con.execute('INSERT INTO leases VALUES (?,?)', ('request','closed'))
                con.execute('INSERT INTO review_bindings VALUES (?,?)', ('request','source'))
            with patch.object(broker, 'record_review', side_effect=ValueError('review approval or observed tests missing')) as record:
                broker.reconcile_review_outcomes()
                broker.reconcile_review_outcomes()
            record.assert_called_once()
            with broker.db() as con:
                incident = con.execute('SELECT reason,status FROM review_incidents WHERE review_task_id=?', (task,)).fetchone()
            self.assertEqual(tuple(incident), ('review approval or observed tests missing', 'open'))

    def test_legacy_review_without_snapshot_binding_is_not_reconciled(self):
        task = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as directory, patch.object(broker, 'STATE', Path(directory)):
            with broker.db() as con:
                con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,scope TEXT)')
                con.execute('CREATE TABLE grants(request_id TEXT,mode TEXT)')
                con.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
                con.execute('CREATE TABLE reviews(review_task_id TEXT,source_task_id TEXT)')
                con.execute('CREATE TABLE review_incidents(review_task_id TEXT PRIMARY KEY,reason TEXT,status TEXT,created_at REAL)')
                con.execute('CREATE TABLE review_bindings(request_id TEXT,source_task_id TEXT)')
                con.execute('INSERT INTO native_bindings VALUES (?,?,?,?)', ('request',task,'reviewer','scope'))
                con.execute('INSERT INTO grants VALUES (?,?)', ('request','review'))
                con.execute('INSERT INTO leases VALUES (?,?)', ('request','closed'))
            with patch.object(broker, 'record_review') as record:
                broker.reconcile_review_outcomes()
            record.assert_not_called()

    def test_issue_handoff_freezes_before_assigning_reviewer(self):
        source, review, reviewer, issue = [str(uuid.uuid4()) for _ in range(4)]
        settings = {'agents': {'author': 'implementation', reviewer: 'review'}}
        fake_native = types.SimpleNamespace(
            task_record=lambda *_: {'id': review, 'issue_id': issue, 'status': 'running'},
            issue_task_runs=lambda *_: [{'id': source, 'issue_id': issue,
                                         'agent_id': 'author', 'status': 'completed'}])
        order = []
        with patch.dict(sys.modules, {'native': fake_native}), \
             patch.object(broker, 'snapshot_submission', side_effect=lambda p: order.append(('snapshot', p['task_id']))), \
             patch.object(broker, 'assign_review', side_effect=lambda p: order.append(('assign', p['source_task_id']))):
            broker.auto_prepare_review(settings, review, reviewer)
        self.assertEqual(order, [('snapshot', source), ('assign', source)])

    def test_tool_receipts_only_count_acp_tool_updates(self):
        events = [
            {'method': 'session/update', 'params': {'update': {'sessionUpdate': 'agent_message_chunk'}}},
            {'method': 'session/update', 'params': {'update': {'sessionUpdate': 'tool_call', 'toolCallId': 'one'}}},
            {'method': 'session/update', 'params': {'update': {'sessionUpdate': 'tool_call_update', 'toolCallId': 'one'}}},
            {'method': 'session/update', 'params': {'update': {'sessionUpdate': 'tool_call', 'toolCallId': 'two'}}},
            {'method': 'session/update', 'params': {'update': {'sessionUpdate': 'tool_call'}}},
        ]
        self.assertEqual(broker.tool_call_receipts(events), 2)

    def test_resume_cannot_cross_scope(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(broker, 'STATE', Path(directory)):
            (Path(directory) / 'native.json').write_text('{}')
            token = 'synthetic'
            with broker.db() as con:
                con.execute('CREATE TABLE grants(digest TEXT, task_id TEXT, attempt INTEGER, mode TEXT, request_id TEXT, deadline REAL, used INTEGER)')
                con.execute('CREATE TABLE leases(request_id TEXT, scenario TEXT, name TEXT, status TEXT, deadline REAL)')
                con.execute('CREATE TABLE native_bindings(request_id TEXT, task_id TEXT, agent_id TEXT, scope TEXT)')
                con.execute('CREATE TABLE acp_sessions(scope TEXT, session_id TEXT)')
                con.execute('INSERT INTO grants VALUES (?,?,?,?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(),'task',1,'review','request',9999999999,1))
                con.execute('INSERT INTO leases VALUES (?,?,?,?,?)', ('request','acp-session','container','running',9999999999))
                con.execute('INSERT INTO native_bindings VALUES (?,?,?,?)', ('request','task','agent','scope-a'))
                con.execute('INSERT INTO acp_sessions VALUES (?,?)', ('scope-b','foreign-session'))
            session = unittest.mock.Mock()
            fake_native = types.SimpleNamespace(task_binding=lambda *args: {'scope': 'scope-a'})
            with patch.dict(sys.modules, {'native': fake_native}), patch.dict(broker.SESSIONS, {'request': session}):
                with self.assertRaises(ValueError):
                    broker.session_operation(token, {'frame': {'jsonrpc':'2.0','id':1,'method':'session/resume','params':{'sessionId':'foreign-session'}}})
                session.exchange.assert_not_called()

    def test_capabilities_are_scoped_single_use_and_fenced(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(broker, 'STATE', Path(directory)):
            with broker.db() as con:
                con.execute('CREATE TABLE grants(digest TEXT PRIMARY KEY, task_id TEXT, attempt INTEGER, mode TEXT, request_id TEXT, deadline REAL, used INTEGER, UNIQUE(task_id,attempt))')
                con.execute('CREATE TABLE leases(request_id TEXT PRIMARY KEY, scenario TEXT, name TEXT, status TEXT, deadline REAL)')
                con.execute('CREATE TABLE native_bindings(request_id TEXT PRIMARY KEY, task_id TEXT, agent_id TEXT, scope TEXT)')
            task = str(uuid.uuid4())
            first = broker.issue_grant(dict(task_id=task, attempt=1, mode='review'))
            with self.assertRaises(ValueError):
                broker.execute_grant(first['capability'], {'mode': 'implementation'})
            with patch.object(broker, 'submit', return_value={'status': 'running'}) as launch:
                broker.execute_grant(first['capability'], {})
                launch.assert_called_once()
                with self.assertRaises(ValueError):
                    broker.execute_grant(first['capability'], {})
            with broker.db() as con:
                con.execute('INSERT INTO leases VALUES (?,?,?,?,?)', (first['request_id'], 'acp', 'n', 'running', 9999999999))
            with self.assertRaises(ValueError):
                broker.issue_grant(dict(task_id=task, attempt=2, mode='review'))
            with broker.db() as con:
                con.execute("UPDATE leases SET status='interrupted'")
            second = broker.issue_grant(dict(task_id=task, attempt=2, mode='review'))
            with self.assertRaises(ValueError):
                broker.execute_grant(first['capability'], {})
            with broker.db() as con:
                con.execute('UPDATE grants SET deadline=0 WHERE attempt=2')
                digests = [row[0] for row in con.execute('SELECT digest FROM grants')]
                self.assertNotIn(second['capability'], digests)
            with self.assertRaises(ValueError):
                broker.execute_grant(second['capability'], {})

    def test_implementation_requires_native_binding(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(broker, 'STATE', Path(directory)):
            with broker.db() as con:
                con.execute('CREATE TABLE grants(digest TEXT PRIMARY KEY, task_id TEXT, attempt INTEGER, mode TEXT, request_id TEXT, deadline REAL, used INTEGER, UNIQUE(task_id,attempt))')
                con.execute('CREATE TABLE leases(request_id TEXT PRIMARY KEY, scenario TEXT, name TEXT, status TEXT, deadline REAL)')
                con.execute('CREATE TABLE native_bindings(request_id TEXT PRIMARY KEY, task_id TEXT, agent_id TEXT, scope TEXT)')
            grant = broker.issue_grant(dict(task_id=str(uuid.uuid4()), attempt=1, mode='implementation'))
            with patch.object(broker, 'submit') as launch, self.assertRaisesRegex(ValueError, 'implementation requires native binding'):
                broker.execute_grant(grant['capability'], {}, streaming=True)
            launch.assert_not_called()
            with broker.db() as con:
                used = con.execute('SELECT used FROM grants WHERE request_id=?', (grant['request_id'],)).fetchone()['used']
            self.assertEqual(used, 0)

    def test_native_implementation_gets_separate_writable_workspace(self):
        request_id = str(uuid.uuid4())
        issue_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as directory, patch.object(broker, 'STATE', Path(directory)):
            with broker.db() as con:
                con.execute('CREATE TABLE native_bindings(request_id TEXT,issue_id TEXT)')
                con.execute('INSERT INTO native_bindings VALUES (?,?)', (request_id, issue_id))
            with patch.object(broker, 'native_scope', return_value='eval-scope'), \
             patch.object(broker, 'native_mode', return_value='implementation'), \
             patch.object(broker, 'MODEL_NETWORK', 'delivery-kit-eval_model'), \
             patch.object(broker, 'seed_workspace') as seed, \
             patch.object(broker, 'docker', return_value=None):
                config = broker.config(request_id, 'acp-session')
            seed.assert_called_once()
        mounts = config['HostConfig']['Mounts']
        self.assertEqual({m['Target'] for m in mounts}, {'/session-state', '/workspace'})
        workspace = next(m for m in mounts if m['Target'] == '/workspace')
        self.assertEqual(workspace['Source'], 'delivery-kit-eval-work-' + hashlib.sha256(b'eval-scope').hexdigest()[:32])
        self.assertFalse(workspace.get('ReadOnly', False))
        self.assertTrue(config['HostConfig']['ReadonlyRootfs'])
        self.assertNotIn('docker.sock', json.dumps(config))

    def test_reviewer_gets_only_read_only_snapshot(self):
        volume = 'delivery-kit-eval-snapshot-' + str(uuid.uuid4())
        source_task = volume.removeprefix('delivery-kit-eval-snapshot-')
        def api(method, path, data=None):
            if method == 'GET' and path == '/volumes/' + volume:
                return {'Labels': {'delivery-kit.owner': broker.OWNER,
                                   'delivery-kit.source-task': source_task}}
            return None
        with patch.object(broker, 'native_scope', return_value='review-scope'), \
             patch.object(broker, 'native_mode', return_value='review'), \
             patch.object(broker, 'review_snapshot', return_value=(volume, source_task)), \
             patch.object(broker, 'docker', side_effect=api):
            config = broker.config(str(uuid.uuid4()), 'acp-session')
        mounts = config['HostConfig']['Mounts']
        self.assertEqual({m['Target'] for m in mounts}, {'/session-state', '/delivery'})
        delivery = next(m for m in mounts if m['Target'] == '/delivery')
        self.assertTrue(delivery['ReadOnly'])
        self.assertNotIn('/workspace', json.dumps(mounts))

    def test_rejects_arbitrary_authority(self):
        valid = {'request_id': str(uuid.uuid4()), 'scenario': 'canary'}
        for key in ('command', 'mount', 'image', 'env', 'reviewer', 'deadline'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                broker.validate({**valid, key: 'injected'})
        for scenario in ('shell', 'acp', 'deploy'):
            with self.assertRaises(ValueError):
                broker.validate({**valid, 'scenario': scenario})

    def test_worker_has_no_credentials_mounts_or_network(self):
        with patch.object(broker, 'native_scope', return_value=None):
            config = broker.config(str(uuid.uuid4()), 'canary')
        self.assertTrue(config['NetworkDisabled'])
        self.assertEqual(config['User'], '10000:10000')
        self.assertTrue(config['HostConfig']['ReadonlyRootfs'])
        self.assertNotIn('Binds', config['HostConfig'])
        self.assertNotIn('Mounts', config['HostConfig'])
        self.assertEqual(config['HostConfig']['CapDrop'], ['ALL'])

    def test_native_model_worker_has_only_proxy_network_and_session_volume(self):
        with patch.object(broker, 'native_scope', return_value='eval-scope'), \
             patch.object(broker, 'native_mode', return_value='review'), \
             patch.object(broker, 'review_snapshot', return_value=None), \
             patch.object(broker, 'MODEL_NETWORK', 'delivery-kit-eval_model'), \
             patch.object(broker, 'docker', return_value=None):
            config = broker.config(str(uuid.uuid4()), 'acp-session')
        self.assertFalse(config['NetworkDisabled'])
        self.assertEqual(config['HostConfig']['NetworkMode'], 'delivery-kit-eval_model')
        self.assertEqual(len(config['HostConfig']['Mounts']), 1)
        self.assertEqual(config['HostConfig']['Mounts'][0]['Target'], '/session-state')
        self.assertNotIn('OPENROUTER_API_KEY', json.dumps(config))
        self.assertNotIn('docker.sock', json.dumps(config))

    def test_cleanup_refuses_foreign_container(self):
        with patch.object(broker, 'docker', return_value={'Config': {'Labels': {}}, 'Id': 'foreign'}) as api:
            with self.assertRaises(RuntimeError):
                broker.remove_owned('name', 'id')
            self.assertEqual(api.call_count, 1)
