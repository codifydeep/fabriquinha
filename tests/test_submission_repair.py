"""Pre-merge continuation facts never release native triage or waive quality."""
from dataclasses import replace
import json
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock
import test_control_targets as fixture_tools
from test_delivery_core import configuration
from fabriquinha.board import Run
from fabriquinha.artifacts import digest
from fabriquinha.repairs import submission_failure,repair_document,Repairs,reviewed,SUBMISSION_PROTOCOL


class SubmissionRepairAdmission(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_tools.BehaviorControlTargets(methodName='runTest')
        with patch('test_control_targets.configuration',return_value={**configuration(),
                'technical_roles':dict(lead='lead',cto='cto'),
                'coordination_roles':dict(product='product',lead='lead')}):self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f=self.fixture;self.source_body=dict(version=1,kind='implementation',release='v1',release_anchor='anchor',inputs={'tests':'parent:tests:tests'})
        f.implementer=replace(f.implementer,contract=digest(self.source_body))
        self.freeze=f.freeze([dict(case='passing_risk',reason='Independent behavior risk')])
        green,mutant=f.green_and_mutant()
        with self.assertRaises(ValueError):f.q.controls(f.implementer,green,[mutant])
        self.snapshot=f.store.receipt(green)['payload']['snapshot']
        self.incident=dict(project=f.project.fingerprint(),source=f.implementer.task,
            source_run=f.implementer.number,source_state='triage',resume_allowed=False,
            controller_effects=[],snapshot=self.snapshot,control_refusal=f.q.control_refusal)
        self.diagnostic=Run('diagnosis',5,'cto','diagnostic',False,'cto','v1','diag-contract')

    def evaluate(self,*,incident=None,actor=None,experiment_snapshot=None,freeze=None,current=None):
        f=self.fixture;binding=(actor or self.diagnostic).binding()
        key=f.store.record('incident',f.implementer.binding(),incident or self.incident)
        experiment=f.store.record('diagnostic_experiment',binding,dict(project=f.project.fingerprint(),
            incident=key,snapshot=experiment_snapshot or self.snapshot))
        decision=f.store.record('diagnostic_decision',binding,dict(project=f.project.fingerprint(),
            incident=key,experiment=experiment,action='hold',delivery_approval=False))
        return submission_failure(f.project,f.store,key,decision,freeze or self.freeze,current or self.snapshot)

    def test_missing_terminal_protocol_allows_only_reviewed_future_attempt(self):
        incident={k:v for k,v in self.incident.items() if k!='control_refusal'}
        incident['failure']='activity ended without a controller-validated native handoff; SDK status '+json.dumps(
            dict(code='missing_terminal_operation',output_limit=16384,failed=False,api_calls=13))
        # A fresh attempt may begin before Green; it must still preserve the
        # independently frozen tests and produce fresh Green/controls later.
        self.snapshot=self.fixture.store.receipt(self.freeze)['payload']['snapshot']
        incident['snapshot']=self.snapshot
        result=self.evaluate(incident=incident)
        self.assertEqual(result['protocol_failure']['code'],'missing_terminal_operation')
        self.assertIsNone(result['control_refusal'])
        self.assertTrue(result['requires_independent_plan_review'])
        self.assertTrue(result['requires_fresh_green_and_controls'])
        self.assertFalse(result['delivery_approval'])
        for failure in ('missing_terminal_operation',incident['failure'].replace('missing_terminal_operation','sdk_failed')):
            with self.assertRaises(ValueError):self.evaluate(incident={**incident,'failure':failure})

    def test_exact_facts_only_authorize_a_future_independent_proposal(self):
        value=self.evaluate()
        self.assertFalse(value['delivery_approval'])
        self.assertTrue(value['requires_independent_plan_review'])
        self.assertTrue(value['requires_fresh_green_and_controls'])
        self.assertEqual(value['tests'],self.freeze)
        self.assertEqual(value['control_refusal']['missing'],['passing_risk'])

    def test_live_or_changed_or_uncertain_source_is_not_a_continuation(self):
        for change in ({'source_state':'blocked'},{'resume_allowed':True},
                       {'source_run':99},{'source':'other'},{'controller_effects':['uncertain']}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.evaluate(incident={**self.incident,**change})
        with self.assertRaises(ValueError):self.evaluate(current=self.fixture.candidate)

    def test_other_role_release_or_experiment_is_rejected(self):
        for actor in (replace(self.diagnostic,actor='lead'),replace(self.diagnostic,release='other'),
                      replace(self.diagnostic,reviewing=True)):
            with self.subTest(actor=actor),self.assertRaises(ValueError):self.evaluate(actor=actor)
        with self.assertRaises(ValueError):self.evaluate(experiment_snapshot=self.fixture.candidate)

    def test_changed_frozen_tests_cannot_be_reused_as_continuation(self):
        f=self.fixture
        old=f.store.receipt(self.freeze,kind='tests_frozen')
        foreign=f.store.record('tests_frozen',{**old['binding'],'release':'other'},old['payload'])
        with self.assertRaises(ValueError):self.evaluate(freeze=foreign)

    def test_submission_proposal_cannot_authorize_test_or_business_changes(self):
        context=dict(repair_kind='submission',qa_paths=[])
        proposal=dict(classification='submission',reason='Submit all independently targeted mutations together.',test_paths=[])
        self.assertEqual(repair_document(proposal,context),proposal)
        for classification in ('product','test_contract'):
            with self.assertRaises(ValueError):repair_document({**proposal,'classification':classification},context)
        with self.assertRaises(ValueError):repair_document({**proposal,'test_paths':['tests/test_existing.py']},context)
        with self.assertRaises(ValueError):repair_document(proposal,dict(qa_paths=[]))
        for classification in ('infrastructure','scope'):
            self.assertEqual(repair_document({**proposal,'classification':classification},context)['classification'],classification)

    def test_native_proposal_is_idempotent_and_does_not_release_source(self):
        f=self.fixture;facts=self.evaluate();(f.work/'app.py').write_text('VALUE = 1\n')
        source=SimpleNamespace(id=f.implementer.task,status='triage',body=json.dumps(self.source_body),workspace_path=f.work)
        tests=SimpleNamespace(id='tests',status='done');anchor=SimpleNamespace(id='anchor')
        conn=sqlite3.connect(':memory:');self.addCleanup(conn.close);conn.row_factory=sqlite3.Row
        conn.execute('CREATE TABLE tasks(id TEXT,body TEXT,idempotency_key TEXT)');created=[]
        def create(connection,**kwargs):
            created.append(kwargs);connection.execute('INSERT INTO tasks VALUES(?,?,?)',('proposal',kwargs['body'],kwargs['idempotency_key']))
            return 'proposal'
        kb=SimpleNamespace(latest_run=lambda *a:SimpleNamespace(id=f.implementer.number,ended_at=1),create_task=create)
        releases=SimpleNamespace(project=f.project,store=f.store,board=SimpleNamespace(guard=None),
            check_card=lambda c,card:source if card['id']==source.id else tests,
            closed=lambda *a:(self.freeze,None,None),binding=lambda a:dict(actor='controller',task=a.id,release='v1',contract='anchor'))
        spec=dict(task='approved-plan',approval='approved-brief',document=dict(architecture='HTTP',observability='local'))
        item=dict(cards=dict(implementation={'id':source.id},tests={'id':tests.id}),package=dict(id='first',title='First'))
        with patch('fabriquinha.repairs.native',return_value=(kb,None,None)),patch('fabriquinha.repairs.Recovery.expired_effects',return_value=[]):
            operation=Repairs(releases)
            first=operation.propose_submission(conn,anchor,spec,item,facts['incident'],facts['reviewed_diagnosis'],dict(items=[item]))
            self.assertEqual(operation.propose_submission(conn,anchor,spec,item,facts['incident'],facts['reviewed_diagnosis'],dict(items=[item])),first)
            with patch('fabriquinha.quality.CONTROL_SUBMISSION_CONTRACT','New tool help; same evidence gates'):
                self.assertEqual(operation.propose_submission(conn,anchor,spec,item,facts['incident'],facts['reviewed_diagnosis'],dict(items=[item])),first)
            self.assertEqual(len(created),1);self.assertEqual(source.status,'triage')
            self.assertEqual(created[0]['assignee'],'lead');self.assertEqual(created[0]['parents'],['approved-plan'])
            self.assertEqual(json.loads(created[0]['body'])['repair_of'],source.id)
            conn.execute('UPDATE tasks SET body=?',(json.dumps({'altered':True}),))
            with self.assertRaises(ValueError):operation.propose_submission(conn,anchor,spec,item,facts['incident'],facts['reviewed_diagnosis'],dict(items=[item]))

    def test_submission_context_exposes_exact_protected_paths_without_edit_authority(self):
        from fabriquinha.repairs import context_view
        f=self.fixture
        result=context_view(f.store,dict(repair_kind='submission',tests=self.freeze))
        frozen=f.store.receipt(self.freeze)['payload']
        self.assertEqual(result['protected_tests']['files'],frozen['tests'])
        self.assertEqual(result['protected_tests']['snapshot'],frozen['snapshot'])
        self.assertIn('not permission',result['protected_tests']['contract'])

    def test_context_upgrade_preserves_legacy_hold_and_waits_for_new_review(self):
        f=self.fixture;facts=self.evaluate();(f.work/'app.py').write_text('VALUE = 1\n')
        source=SimpleNamespace(id=f.implementer.task,status='triage',body=json.dumps(self.source_body),workspace_path=f.work)
        tests=SimpleNamespace(id='tests',status='done');anchor=SimpleNamespace(id='anchor')
        legacy=SimpleNamespace(id='old-proposal',status='done')
        conn=sqlite3.connect(':memory:');self.addCleanup(conn.close);conn.row_factory=sqlite3.Row
        conn.execute('CREATE TABLE tasks(id TEXT,body TEXT,idempotency_key TEXT)')
        key=digest([f.project.fingerprint(),source.id,f.implementer.number,'complete-control-set-2','proposal'])
        conn.execute('INSERT INTO tasks VALUES(?,?,?)',(legacy.id,'{}',key))
        older=digest([f.project.fingerprint(),source.id,f.implementer.number,'complete-control-set-1','proposal'])
        conn.execute('INSERT INTO tasks VALUES(?,?,?)',('oldest-proposal','{}',older));created=[]
        def create(connection,**kwargs):
            created.append(kwargs);connection.execute('INSERT INTO tasks VALUES(?,?,?)',('new-proposal',kwargs['body'],kwargs['idempotency_key']))
            return 'new-proposal'
        kb=SimpleNamespace(latest_run=lambda *a:SimpleNamespace(id=f.implementer.number,ended_at=1),
            get_task=lambda c,ident:legacy if ident==legacy.id else None,create_task=create)
        releases=SimpleNamespace(project=f.project,store=f.store,board=SimpleNamespace(guard=None),
            check_card=lambda c,card:source if card['id']==source.id else tests,
            closed=lambda task,*a:('old-review' if task==legacy.id else self.freeze,None,None),
            binding=lambda a:dict(actor='controller',task=a.id,release='v1',contract='anchor'))
        spec=dict(task='approved-plan',approval='approved-brief',document=dict(architecture='HTTP',observability='local'))
        item=dict(cards=dict(implementation={'id':source.id},tests={'id':tests.id}),package=dict(id='first',title='First'))
        prior=dict(context=facts,proposal={'classification':'infrastructure'})
        with patch('fabriquinha.repairs.native',return_value=(kb,None,None)),patch('fabriquinha.repairs.Recovery.expired_effects',return_value=[]),\
             patch('fabriquinha.repairs.reviewed',return_value=prior):
            operation=Repairs(releases);args=(conn,anchor,spec,item,facts['incident'],facts['reviewed_diagnosis'],dict(items=[item]))
            legacy.status='review';self.assertEqual(operation.propose_submission(*args),legacy.id);self.assertEqual(created,[])
            legacy.status='done';prior['proposal']['classification']='submission'
            self.assertEqual(operation.propose_submission(*args),legacy.id);self.assertEqual(created,[])
            prior['proposal']['classification']='infrastructure'
            self.assertEqual(operation.propose_submission(*args),'new-proposal')
            self.assertEqual(operation.propose_submission(*args),'new-proposal');self.assertEqual(len(created),1)
            self.assertEqual(created[0]['parents'],['approved-plan',legacy.id])
            context=f.store.receipt(json.loads(created[0]['body'])['repair_context'])['payload']
            self.assertEqual(context['prior_proposal_review'],'old-review')
            self.assertEqual(conn.execute('SELECT body FROM tasks WHERE id=?',(legacy.id,)).fetchone()[0],'{}')
            self.assertEqual(source.status,'triage')

    def test_continuation_requires_independent_review_of_exact_source_facts(self):
        f=self.fixture;facts=self.evaluate()
        def approval(actor='cto',source_run=None,protocol=SUBMISSION_PROTOCOL):
            context={**facts,'project':f.project.fingerprint(),'repair_kind':'submission',
                'submission_protocol':protocol,'qa_paths':[]}
            if source_run is not None:context['source_run']=source_run
            key=f.store.record('repair_context',dict(release='v1'),context)
            body=dict(repair_context=key,repair_protocol=protocol,repair_of=f.implementer.task)
            author=Run('proposal',6,'lead','plan',False,'lead','v1',digest(body))
            proposal=f.store.record('work_plan',author.binding(),dict(project=f.project.fingerprint(),repair_body=body,
                document=dict(classification='submission',reason='Retain all useful controls in a single submission.',test_paths=[])))
            reviewer=replace(author,number=7,actor=actor,reviewing=True)
            return f.store.record('plan_review',reviewer.binding(),dict(project=f.project.fingerprint(),plan=proposal,
                verdict=dict(decision='approve',reason='The scoped proposal preserves quality gates.',findings=[])))
        self.assertEqual(reviewed(f.project,f.store,approval())['proposal']['classification'],'submission')
        self.assertEqual(reviewed(f.project,f.store,approval(protocol='complete-control-set-1'))['proposal']['classification'],'submission')
        self.assertEqual(reviewed(f.project,f.store,approval(protocol='complete-control-set-2'))['proposal']['classification'],'submission')
        with self.assertRaises(ValueError):reviewed(f.project,f.store,approval(protocol='unknown'))
        with self.assertRaises(ValueError):reviewed(f.project,f.store,approval(actor='lead'))
        with self.assertRaises(ValueError):reviewed(f.project,f.store,approval(source_run=999))

    def test_dispatch_waits_for_review_then_follows_replacement_without_reset(self):
        f=self.fixture;facts=self.evaluate();source=f.implementer.task
        row=SimpleNamespace(id=f.implementer.number,ended_at=1)
        tasks={source:SimpleNamespace(id=source,status='triage'),
               'diagnosis':SimpleNamespace(id='diagnosis',status='done',body=json.dumps(dict(
                   kind='diagnostic',source=source,source_run=row.id,stage='cto'))),
               'proposal':SimpleNamespace(id='proposal',status='review'),
               'replacement':SimpleNamespace(id='replacement',status='ready')}
        def latest(conn,ident):
            return SimpleNamespace(metadata={'diagnosis':facts['reviewed_diagnosis']}) if ident=='diagnosis' else row
        kb=SimpleNamespace(get_task=lambda conn,ident:tasks.get(ident),latest_run=latest)
        releases=SimpleNamespace(project=f.project,store=f.store,board=Mock(),closed=Mock(return_value=('approved',None,None)))
        operation=Repairs(releases);operation.propose_submission=Mock(return_value='proposal')
        graph=dict(items=[dict(cards=dict(implementation={'id':source}))])
        replacement=dict(items=[dict(cards=dict(implementation={'id':'replacement'}))],submission_depth=1)
        operation.materialize_submission=Mock(return_value=replacement)
        with patch('fabriquinha.repairs.native',return_value=(kb,None,None)),\
             patch('fabriquinha.repairs.Recovery.cards',return_value=[tasks['diagnosis']]):
            self.assertEqual(operation.continue_submission(None,None,None,graph),graph)
            operation.materialize_submission.assert_not_called();releases.closed.assert_not_called()
            tasks['proposal'].status='done'
            self.assertEqual(operation.continue_submission(None,None,None,graph),replacement)
            releases.closed.assert_called_once_with('proposal','plan_review','plan_review')
            self.assertEqual(tasks[source].status,'triage')
            from fabriquinha.effects import EffectBlocked
            operation.propose_fixture=Mock(return_value='proposal');tasks['proposal'].status='review'
            bounded={**graph,'submission_depth':2}
            self.assertEqual(operation.continue_submission(None,None,None,bounded),bounded)
            operation.propose_fixture.assert_called_once()
            self.assertEqual(operation.materialize_submission.call_count,1)

    def test_replacement_tail_preserves_tests_dependencies_and_recovers_after_graph_write(self):
        self.replacement_tail()

    def test_fixture_tail_replaces_tests_without_reset_and_recovers_after_graph_write(self):
        self.replacement_tail(fixture=True)

    def test_cto_admitted_blocked_fixture_recovers_without_submission_retries(self):
        self.replacement_tail(fixture=True,direct=True)

    def replacement_tail(self,fixture=False,direct=False):
        from fabriquinha.releases import Releases
        from fabriquinha.effects import write_json
        f=self.fixture;facts=self.evaluate()
        source_work=f.root/'source-work';f.work.rename(source_work);f.work=source_work
        (f.work/'app.py').write_text('VALUE = 1\n')
        conn=sqlite3.connect(':memory:');self.addCleanup(conn.close)
        conn.execute('CREATE TABLE task_links(parent_id TEXT,child_id TEXT)')
        tasks={};keys={};counter=[0];created=[];activated=[]
        def task(ident,body,parents,status,workspace,owner='backend'):
            value=SimpleNamespace(id=ident,body=json.dumps(body),status=status,assignee=owner,workspace_kind='dir',
                workspace_path=str(workspace),completion_contract='local-only')
            tasks[ident]=value
            conn.executemany('INSERT INTO task_links VALUES(?,?)',[(p,ident) for p in parents])
            return dict(id=ident,body=body,parents=parents,workspace=str(workspace),owner=owner,completion_contract='local-only')
        first_tests=task('tests',dict(kind='tests',inputs={}),[],'done',f.work)
        first_impl=task('implementation',self.source_body,['tests'],'triage',f.work)
        first_integration=task('integration',dict(kind='integration',inputs={'delivery':'parent:implementation:delivery'}),['implementation'],'todo',f.work)
        second_tests=task('tests2',dict(kind='tests',inputs={'baseline':'parent:integration:baseline','base_commit':'parent:integration:base_commit'}),['integration'],'todo',f.work)
        second_impl=task('implementation2',dict(kind='implementation',inputs={'tests':'parent:tests2:tests'}),['tests2'],'todo',f.work)
        second_integration=task('integration2',dict(kind='integration',inputs={'delivery':'parent:implementation2:delivery'}),['implementation2'],'todo',f.work)
        original={key:vars(value).copy() for key,value in tasks.items()}
        anchor=SimpleNamespace(id='anchor',body=json.dumps({'release':'v1'}));plan='t_11223344'
        tasks[plan]=SimpleNamespace(id=plan,status='done')
        items=[dict(package=dict(id='first',title='First'),cards=dict(tests=first_tests,implementation=first_impl,integration=first_integration)),
               dict(package=dict(id='second',title='Second'),cards=dict(tests=second_tests,implementation=second_impl,integration=second_integration))]
        graph=dict(project=f.project.fingerprint(),items=items,validation_bundle='bundle',submission_depth=2 if fixture and not direct else 0)
        releases=Releases(f.project,f.store,SimpleNamespace(guard=None),Mock());releases.closed=Mock(return_value=('approval',None,None))
        releases.folder=lambda a:f.store.root/'releases'/digest('v1')
        old=f.store.record('release_graph',releases.binding(anchor),graph)
        authority=dict(task=plan,proposal=dict(classification='submission'),context={**facts,'repair_kind':'submission','prior_graph':old})
        if fixture:
            authority['proposal']['classification']='test_contract'
            authority['context'].update(repair_kind='fixture',implementation_snapshot=self.snapshot,
                snapshot=f.store.receipt(self.freeze)['payload']['snapshot'])
        if direct:
            tasks['implementation'].status='blocked'
            original['implementation']['status']='blocked'
            authority['controller_admission']=True
        expected_count=6 if fixture else 5
        target=releases.folder(anchor)/('continuation-'+plan+'.json')
        def latest(connection,ident):
            return SimpleNamespace(id=f.implementer.number,ended_at=1) if ident=='implementation' else None
        def create(connection,**kwargs):
            key=kwargs['idempotency_key']
            if key in keys:return keys[key]
            counter[0]+=1;ident='t_'+format(counter[0],'08x');keys[key]=ident;created.append(ident)
            task(ident,json.loads(kwargs['body']),kwargs['parents'],kwargs['initial_status'],kwargs['workspace_path'],kwargs['assignee'])
            return ident
        def unblock(connection,ident):
            self.assertTrue(target.exists(),'the graph must be durable before activation')
            tasks[ident].status='ready';activated.append(ident);return True
        kb=SimpleNamespace(get_task=lambda c,i:tasks.get(i),latest_run=latest,create_task=create,unblock_task=unblock)
        def interrupted(path,value):
            write_json(path,value)
            if path==target:raise OSError('after graph persistence')
        with patch('fabriquinha.repairs.native',return_value=(kb,None,None)),patch('fabriquinha.releases.native',return_value=(kb,None,None)),\
             patch('fabriquinha.repairs.reviewed',return_value=authority),patch('fabriquinha.executor.validation_files',return_value=('bundle',{})):
            operation=Repairs(releases)
            if direct:operation.succession_parent=Mock(return_value=tasks[plan])
            from fabriquinha.effects import EffectBlocked
            tasks['tests2'].status='running'
            with self.assertRaises(EffectBlocked):operation.materialize_submission(conn,anchor,graph,'approval')
            tasks['tests2'].status='todo';self.assertEqual(created,[])
            (f.work/'app.py').write_text('VALUE = 99\n')
            with self.assertRaises(ValueError):operation.materialize_submission(conn,anchor,graph,'approval')
            (f.work/'app.py').write_text('VALUE = 1\n');self.assertEqual(created,[])
            with patch('fabriquinha.repairs.write_json',side_effect=OSError('before graph persistence')),self.assertRaises(OSError):
                operation.materialize_submission(conn,anchor,graph,'approval')
            self.assertEqual(len(created),expected_count);self.assertEqual(activated,[]);self.assertFalse(target.exists())
            with patch('fabriquinha.repairs.write_json',side_effect=interrupted),self.assertRaises(OSError):
                operation.materialize_submission(conn,anchor,graph,'approval')
            self.assertEqual(len(created),expected_count);self.assertEqual(activated,[])
            result=operation.materialize_submission(conn,anchor,graph,'approval')
            self.assertEqual(operation.materialize_submission(conn,anchor,graph,'approval'),result)
            self.assertEqual(len(created),expected_count);self.assertEqual(len(activated),expected_count)
            if not fixture:self.assertEqual(result['items'][0]['cards']['tests'],first_tests)
            else:
                self.assertEqual(result['submission_depth'],0 if direct else 2);self.assertEqual(result['fixture_depth'],1)
                self.assertNotEqual(result['items'][0]['cards']['tests']['id'],first_tests['id'])
            new_first=result['items'][0]['cards'];new_second=result['items'][1]['cards']
            self.assertEqual(new_second['tests']['body']['inputs']['baseline'],'parent:'+new_first['integration']['id']+':baseline')
            self.assertIn(new_first['integration']['id'],new_second['tests']['parents'])
            if not fixture:self.assertEqual(f.store.capture(new_first['implementation']['workspace']),self.snapshot)
            else:
                from pathlib import Path
                self.assertEqual(list(Path(new_first['implementation']['workspace']).iterdir()),[])
                self.assertEqual(new_first['tests']['body']['inputs']['baseline'],authority['context']['snapshot'])
                self.assertEqual(new_first['implementation']['body']['inputs']['repair_review'],'approval')
            self.assertEqual({key:vars(tasks[key]) for key in original},original)
            self.assertEqual(set(result['superseded_cards']),set(original)-(set() if fixture else {'tests'}))


if __name__=='__main__':unittest.main()
