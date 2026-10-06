import unittest
from broker.harness_repair_task import author_note,maintenance_prompt,preparation_marker


class HarnessRepairTaskTests(unittest.TestCase):
    def test_current_maintenance_context_uses_persistent_phase_not_historical_issue(self):
        import sqlite3,json
        from unittest.mock import patch
        from broker import harness_repair_task as h,driver_checkpoint_policy as p
        con=sqlite3.connect(':memory:')
        with self.assertRaises(ValueError):h.current_maintenance_context(con,{'id':'issue'},{})
        con.execute('CREATE TABLE harness_repair_tasks(config TEXT,state TEXT)')
        state={'staged':{'current':1},'diagnosis_decision':{'reason':'balanced syntax'}}
        con.execute('INSERT INTO harness_repair_tasks VALUES (?,?)',(json.dumps({'author':'author'}),json.dumps(state)))
        with patch.object(p,'select',return_value={'surgical':{}}):
            context=h.current_maintenance_context(con,{'id':'issue','description':'obsolete'}, {'id':'task'})
            self.assertIn('CHECKPOINT1 SYNTAX ONLY',context['description'])
            self.assertNotIn('obsolete',context['description'])
        with patch.object(p,'select',return_value=None):
            with self.assertRaises(ValueError):h.current_maintenance_context(con,{'id':'issue'},{'id':'task'})
        con.close()
    def test_format_recovery_requires_exact_failure_and_is_one_shot(self):
        import copy
        from broker import harness_repair_task as h
        config={'cto':'cto'}
        state={'stage':'blocked','category':'invalid_or_unread_driver_diagnosis','issue_id':'child',
            'diagnosis':{'wakeup_id':'wake'},'rejection_replan':{'note':h.rejection_diagnosis_note({},[])}}
        task={'id':'failed','status':'failed','agent_id':'cto','issue_id':'child','wakeup_id':'wake'}
        reads={p:{'lines':5,'total_lines':5} for p in h.diagnosis_paths()}
        event={'execution_id':'exec','status':502,'category':'structured_decision_response_invalid',
            'structured_rejection_category':'typed_schema_maxLength','decision_rejection_persisted':True,
            'call_number':4109,'decision_upstream_sha256':'a'*64}
        result=h.prepare_diagnosis_format_recovery(config,copy.deepcopy(state),task,reads,event,'exec')
        self.assertEqual(result['stage'],'rejection_diagnosis_dispatch')
        self.assertIn('at most600characters',result['rejection_replan']['note'])
        self.assertFalse(result['diagnosis_format_recovery']['delivery_approval'])
        self.assertEqual(result['diagnosis_format_recovery']['failed_task'],'failed')
        with self.assertRaises(ValueError):h.prepare_diagnosis_format_recovery(config,result,task,reads,event,'exec')
        for bad in (dict(event,execution_id='other'),dict(event,structured_rejection_category='typed_enum'),
                dict(event,decision_rejection_persisted=False),dict(event,call_number=None)):
            with self.assertRaises(ValueError):h.prepare_diagnosis_format_recovery(config,copy.deepcopy(state),task,reads,bad,'exec')
        with self.assertRaises(ValueError):h.prepare_diagnosis_format_recovery(config,copy.deepcopy(state),dict(task,status='completed'),reads,event,'exec')
        incomplete=copy.deepcopy(reads);incomplete[h.diagnosis_paths()[0]]['lines']=4
        with self.assertRaises(ValueError):h.prepare_diagnosis_format_recovery(config,copy.deepcopy(state),task,incomplete,event,'exec')

    def test_driver_rejection_receipt_requires_two_real_complete_distinct_results(self):
        from broker.harness_repair_task import rejected_driver_operations,rejection_diagnosis_note
        messages=[]
        for call,category in (('first','no_bounded_change'),('second','driver_syntax_invalid')):
            messages.extend([{'type':'tool_use','tool':'surgical_test_edit','call_id':call},
                {'type':'tool_result','tool':'surgical_test_edit','call_id':call,
                 'output':'surgical_edit_rejected:'+category+':next_operation','output_truncated':False}])
        receipt=rejected_driver_operations(messages)
        self.assertEqual({r['category'] for r in receipt},{'no_bounded_change','driver_syntax_invalid'})
        self.assertTrue(all(len(r['output_sha256'])==64 for r in receipt))
        note=rejection_diagnosis_note({},receipt)
        self.assertLess(len(note),3900);self.assertIn('unchanged',note);self.assertIn('Do NOT implement C10 yet',note)
        self.assertNotIn('non-driver Python AST changed',note)
        with self.assertRaises(ValueError):rejected_driver_operations(messages[:2])
        with self.assertRaises(ValueError):rejected_driver_operations(messages+[messages[-1]])
        with self.assertRaises(ValueError):rejected_driver_operations(messages[:-1]+[dict(messages[-1],output_truncated=True)])

    def test_verified_changed_cto_strategy_is_required_before_one_guarded_restart(self):
        import sqlite3,json
        from contextlib import contextmanager
        from pathlib import Path
        import tempfile,threading
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        from broker import harness_repair_task as h
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        h.initialize(con);con.execute('CREATE TABLE leases(status TEXT)')
        config={'author':'author','cto':'cto'}
        decision={'action':'request_test_revision','reason':'Close the exact nested promise in source order using driver-only changed fragments.','optional_files':[]}
        task={'id':'new-cto','agent_id':'cto','status':'completed','issue_id':'child','wakeup_id':'new-wake'}
        reads={p:{'lines':5,'total_lines':5} for p in h.diagnosis_paths()}
        state={'stage':'guarded_replan_dispatch_intent','issue_id':'child','snapshot':{'volume':'frozen'},
            'validation':{'test_sha256':'a'*64},'diagnosis':{'wakeup_id':'new-wake'},'diagnosis_decision':decision,
            'staged':{'current':1,'history':[],'driver_guard':{}},
            'rejection_replan':{'author_task':'rejected','operations':[{'category':'driver_syntax_invalid'}],
                'prior_diagnosis':{'diagnosis_decision':dict(decision,reason='Previous broad guidance.')}}}
        state['diagnosis_certificate']=h.qualify_diagnosis(config,state,task,decision,reads)
        con.execute('INSERT INTO harness_repair_tasks VALUES (?,?,?)',('source',json.dumps(config),json.dumps(state)));con.commit()
        @contextmanager
        def db():
            with con:yield con
        fx=Mock();fx.decision.return_value=decision;fx.read_evidence.return_value=reads;fx.remaining_calls.return_value=84
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'native.json').write_text('{}');b=SimpleNamespace(db=db,LOCK=threading.RLock(),STATE=root)
            with patch.object(h.admission_controls_spike,'verify_current'),patch.object(h.handoff_runtime,'Effects',return_value=fx),patch.object(h.native,'task_record',return_value=task):
                h.resume_replanned_driver(b,'source')
            result=json.loads(con.execute('SELECT state FROM harness_repair_tasks').fetchone()[0])
            self.assertEqual(result['stage'],'checkpoint_dispatch_intent')
            self.assertEqual(result['staged']['driver_guard']['origin_task'],'new-cto')
            self.assertEqual(result['staged']['driver_guard']['replanned_after_rejections']['attempt_limit'],1)
            state['rejection_replan']['prior_diagnosis']['diagnosis_decision']=decision
            con.execute('UPDATE harness_repair_tasks SET state=?',(json.dumps(state),));con.commit()
            with patch.object(h.admission_controls_spike,'verify_current'),patch.object(h.handoff_runtime,'Effects',return_value=fx),patch.object(h.native,'task_record',return_value=task):h.resume_replanned_driver(b,'source')
            blocked=json.loads(con.execute('SELECT state FROM harness_repair_tasks').fetchone()[0])
            self.assertEqual(blocked['stage'],'blocked')
        con.close()
    def test_checkpoint_seed_uses_genuine_snapshot_not_a_fabricated_red(self):
        import sqlite3,json
        from contextlib import contextmanager
        from types import SimpleNamespace
        from broker import test_revision_review as revision
        from broker.harness_repair_task import initialize
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        initialize(con)
        con.execute('CREATE TABLE test_revision_trials(issue_id TEXT PRIMARY KEY,parent_issue TEXT,config TEXT,state TEXT)')
        con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
        facts=dict(source_changed=True,python_syntax_valid=True,node_syntax_valid=True,test_methods_preserved=True,
            non_driver_ast_preserved=True,bytes=100,manifest_sha256='a'*64,test_sha256='b'*64)
        receipt={'checkpoint':1,'task_id':'author-task','snapshot':{'volume':'snapshot'},'validation':facts}
        root={'author':'author'};state={'issue_id':'child','staged':{'history':[receipt]}}
        con.execute('INSERT INTO harness_repair_tasks VALUES (?,?,?)',('source',json.dumps(root),json.dumps(state)))
        config={'parent_issue':'parent','seed_previous_tests':True,'harness_maintenance_only':True,'base_sha':'base',
            'maintenance_seed':{'source':'source','receipt':receipt}}
        con.execute('INSERT INTO test_revision_trials VALUES (?,?,?,?)',('child','parent',json.dumps(config),'{}'))
        route={'enabled':False,'author':'author','contract_sha256':'contract','test_first_files':['tests/test_incremental_u3.py']}
        for issue in ('parent','child'):con.execute('INSERT INTO delivery_routes VALUES (?,?)',(issue,json.dumps(route)))
        con.commit()
        @contextmanager
        def db():yield con
        broker=SimpleNamespace(db=db,OWNER='owner',issue_base=lambda _:dict(base_sha='base'),docker=lambda *_:
            {'Labels':{'delivery-kit.owner':'owner','delivery-kit.source-task':'author-task'}})
        selected=revision.seed_source(broker,'child')
        self.assertTrue(selected['mount']['ReadOnly'])
        self.assertEqual(selected['selection']['test_sha256'],{'tests/test_incremental_u3.py':'b'*64})
        self.assertNotIn('old_red',config)
        current={'checkpoint':2,'task_id':'author-task','snapshot':{'volume':'snapshot'},'validation':dict(facts,test_sha256='c'*64)}
        state['functional_correction']={'seed':current,'attempt_limit':1,'certificate':{'task_id':'cto'}}
        state['functional_diagnosis_receipt']={'certificate':{'task_id':'cto'},'classification':'DRIVER_OBSERVATION'}
        state['functional_diagnosis']={'snapshot':current['snapshot'],'validation':current['validation']}
        config['maintenance_seed']['receipt']=current
        con.execute('UPDATE harness_repair_tasks SET state=?',(json.dumps(state),))
        con.execute('UPDATE test_revision_trials SET config=?',(json.dumps(config),));con.commit()
        self.assertEqual(revision.seed_source(broker,'child')['selection']['test_sha256'],{'tests/test_incremental_u3.py':'c'*64})
        state['functional_correction']['certificate']={'task_id':'wrong'}
        con.execute('UPDATE harness_repair_tasks SET state=?',(json.dumps(state),));con.commit()
        with self.assertRaises(ValueError):revision.seed_source(broker,'child')
        con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(dict(route,enabled=True)),'child'))
        with self.assertRaises(ValueError):revision.seed_source(broker,'child')
        con.close()
    def test_c10_cannot_start_without_a_changed_syntax_preserving_checkpoint(self):
        from broker.harness_repair_task import checkpoint_passed,checkpoint_note
        facts=dict(source_changed=True,python_syntax_valid=True,node_syntax_valid=True,
            test_methods_preserved=True,non_driver_ast_preserved=True,bytes=31684,manifest_sha256='a'*64)
        self.assertTrue(checkpoint_passed(facts))
        for key in ('source_changed','python_syntax_valid','node_syntax_valid','test_methods_preserved','non_driver_ast_preserved'):
            self.assertFalse(checkpoint_passed(dict(facts,**{key:False})))
        self.assertFalse(checkpoint_passed(dict(facts,bytes=32769)))
        self.assertIn('Do NOT implement C10 yet',checkpoint_note(1,{'reason':'close promise constructs'}))
        self.assertIn('controller-validated syntax checkpoint',checkpoint_note(2,{'reason':'C10 observations'}))
        self.assertIn('no skips, fabricated constants',checkpoint_note(2,{'reason':'C10 observations'}))
    def test_diagnosis_requires_exact_independent_recipient_and_complete_reads(self):
        from broker.harness_repair_task import diagnosis_paths,qualify_diagnosis,diagnosis_note
        config={'cto':'cto','author':'author'}
        state={'issue_id':'child','diagnosis':{'wakeup_id':'wake'},'snapshot':{'volume':'frozen'},'validation':{'test_sha256':'a'*64}}
        task={'id':'task','status':'completed','agent_id':'cto','issue_id':'child','wakeup_id':'wake'}
        decision={'action':'request_test_revision','reason':'Exact staged driver repair required.','optional_files':[]}
        reads={p:{'lines':10,'total_lines':10} for p in diagnosis_paths()}
        self.assertFalse(qualify_diagnosis(config,state,task,decision,reads)['delivery_approval'])
        for changed in (dict(task,agent_id='author'),dict(task,wakeup_id='stale')):
            with self.assertRaises(ValueError):qualify_diagnosis(config,state,changed,decision,reads)
        with self.assertRaises(ValueError):qualify_diagnosis(config,state,task,decision,{})
        self.assertLess(len(diagnosis_note(state)),3900)
        self.assertIn('do not increase caps',diagnosis_note(state))
    def test_inspection_cannot_promote_invalid_or_weakened_candidate(self):
        from broker.harness_repair_task import classification
        facts=dict(source_changed=True,python_syntax_valid=True,node_syntax_valid=True,
            test_methods_preserved=True,non_driver_ast_preserved=True)
        self.assertEqual(classification(facts),'independent_review_required')
        for key,category in [('node_syntax_valid','driver_syntax_error'),('test_methods_preserved','test_methods_changed'),
                ('non_driver_ast_preserved','outside_driver_scope_changed')]:
            self.assertEqual(classification(dict(facts,**{key:False})),category)
        self.assertEqual(classification(dict(facts,source_changed=False)),'unchanged_invalid_driver')
    def test_bounded_correction_keeps_final_limit_and_preserves_assertions(self):
        from broker.harness_repair_task import bounded_correction_note
        note=bounded_correction_note('repair only tests',{'bytes':31683,'sha256':'a'*64})
        self.assertIn('remaining growth 1085 bytes',note)
        self.assertIn('WHOLE resulting file <=32768',note)
        self.assertIn('without removing or changing methods/assertions',note)
        self.assertIn('do not repeat the same patch',note)
        for size in (32769,True,-1):
            with self.assertRaises(ValueError):bounded_correction_note('repair',{'bytes':size,'sha256':'a'*64})
    def test_paused_author_context_requires_exact_registered_maintenance(self):
        import sqlite3,json
        from broker.harness_repair_task import initialize,registered_author
        with sqlite3.connect(':memory:') as con:
            initialize(con)
            con.execute('CREATE TABLE test_revision_trials(issue_id TEXT,config TEXT)')
            config={'author':'author'}
            state={'issue_id':'child','stage':'awaiting_author','cto_task':'cto','delivery_approval':False}
            con.execute('INSERT INTO harness_repair_tasks VALUES (?,?,?)',('source',json.dumps(config),json.dumps(state)))
            con.execute('INSERT INTO test_revision_trials VALUES (?,?)',('child',json.dumps({'harness_maintenance_only':True})))
            self.assertTrue(registered_author(con,'child','author'))
            self.assertFalse(registered_author(con,'child','other'))
            self.assertFalse(registered_author(con,'other','author'))
            con.execute('UPDATE test_revision_trials SET config=?',(json.dumps({'harness_maintenance_only':False}),))
            self.assertFalse(registered_author(con,'child','author'))
    def test_preparation_identity_includes_exact_instruction(self):
        proof={'decision_sha256':'a'*64}
        marker=preparation_marker('source',proof,'original instruction')
        self.assertEqual(marker,preparation_marker('source',proof,'original instruction'))
        self.assertNotEqual(marker,preparation_marker('source',proof,'corrected permitted instruction'))

    def test_prompt_keeps_actual_artifact_fences_without_claiming_functional_red(self):
        markers='\nDELIVERY_TEST_ARTIFACT_V1:/workspace/tests/test_new.py\nDELIVERY_TEST_REVISION_V1:/workspace/tests/test_new.py\n'
        prompt=maintenance_prompt('Old generic instruction will execute Red.'+markers)
        self.assertTrue(prompt.endswith(markers))
        self.assertNotIn('will execute Red',prompt)
        self.assertIn('not functional TDD Red',prompt)

    def test_maintenance_is_not_a_functional_red_or_product_delivery(self):
        note=author_note({},dict(reason='Repair the unterminated promise chain and populate actual status observations.'))
        self.assertLess(len(note),3900)
        for phrase in ('NOT PRODUCT IMPLEMENTATION OR FUNCTIONAL RED','Preserve every existing method and assertion',
                'new negative controls are a later task','Node --check','Do not label a syntax fix as functional Red'):
            self.assertIn(phrase,note)

    def test_maintenance_phase_stays_tests_only_even_with_a_red_row(self):
        import json,sqlite3,tempfile
        from pathlib import Path
        from unittest.mock import patch
        import os
        with patch.dict(os.environ,{'BROKER_WORKER_IMAGE':'sha256:'+'a'*64}):
            from broker import server
        with tempfile.TemporaryDirectory() as directory:
            database=Path(directory)/'leases.sqlite'
            with sqlite3.connect(database) as con:
                con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
                con.execute('CREATE TABLE test_revision_trials(issue_id TEXT PRIMARY KEY,parent_issue TEXT UNIQUE,config TEXT,state TEXT)')
                con.execute('CREATE TABLE test_first_red(issue_id TEXT)')
                con.execute('INSERT INTO delivery_routes VALUES (?,?)',('child',json.dumps({'test_first':True})))
                con.execute('INSERT INTO test_revision_trials VALUES (?,?,?,?)',('child','parent',json.dumps({'harness_maintenance_only':True}),json.dumps({'status':'approved'})))
                con.execute('INSERT INTO test_first_red VALUES (?)',('child',))
            with patch.object(server,'STATE',Path(directory)):
                self.assertEqual(server.implementation_phase('child'),'tests_only')
