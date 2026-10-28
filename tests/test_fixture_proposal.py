"""Fixture proposals are scoped, idempotent native work, not repair approval."""
import json
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_fixture_red as fixtures
from fabriquinha.artifacts import digest
from fabriquinha.repairs import Repairs,fixture_failure,repair_document,reviewed as real_reviewed,FIXTURE_PROTOCOL
from fabriquinha.board import Run
from fabriquinha.effects import EffectBlocked


class FixtureProposal(unittest.TestCase):
    execute=fixtures.FixtureRed.execute
    setUp=fixtures.FixtureRed.setUp

    def test_only_new_unpublished_acceptance_files_are_eligible(self):
        facts=dict(source='implementation',source_run=8,source_contract='contract',snapshot=self.candidate,
            tests=self.freeze,incident='incident',reviewed_diagnosis='decision',delivery_approval=False)
        with patch('fabriquinha.executor.browser_contract',return_value=2),patch('fabriquinha.repairs.submission_failure',return_value=facts):
            value=fixture_failure(self.project,self.store,'incident','decision',self.freeze,self.candidate)
            self.assertEqual(value['qa_paths'],[self.path])
            self.assertEqual(value['snapshot'],self.frozen_snapshot)
            self.assertEqual(value['implementation_snapshot'],self.candidate)
            self.assertEqual(value['red_baseline'],self.baseline)
            with patch('fabriquinha.quality.Quality.frozen_plan',return_value=dict(baseline=self.frozen_snapshot,snapshot=self.frozen_snapshot)):
                with self.assertRaisesRegex(ValueError,'unpublished'):fixture_failure(self.project,self.store,'incident','decision',self.freeze,self.candidate)
        with patch('fabriquinha.executor.browser_contract',return_value=1):
            with self.assertRaises(ValueError):fixture_failure(self.project,self.store,'incident','decision',self.freeze,self.candidate)

    def test_proposal_receives_complete_frozen_sources_not_author_workspace(self):
        from fabriquinha.repairs import context_view
        context=dict(repair_kind='fixture',tests=self.freeze,snapshot=self.frozen_snapshot,qa_paths=[self.path])
        result=context_view(self.store,context)
        self.assertEqual(result['fixture_sources'][self.path]['text'],fixtures.OLD)
        self.assertNotEqual(result['fixture_sources'][self.path]['text'],(self.work/self.path).read_text())
        for update in ({'qa_paths':['app.py']},{'snapshot':self.candidate},{'qa_paths':[self.path,self.path]}):
            with self.assertRaises(ValueError):context_view(self.store,{**context,**update})

    def test_proposal_cannot_authorize_product_or_business_change(self):
        context=dict(repair_kind='fixture',qa_paths=[self.path])
        proposal=dict(classification='test_contract',reason='Missing setup before the assertion.',test_paths=[self.path])
        self.assertEqual(repair_document(proposal,context),proposal)
        for update in ({'classification':'product'},{'classification':'submission'},
                       {'test_paths':[]},{'test_paths':['tests/test_existing.py']}):
            with self.subTest(update=update),self.assertRaises(ValueError):repair_document({**proposal,**update},context)
        self.assertEqual(repair_document(dict(classification='infrastructure',reason='Different actual blocker.',test_paths=[]),context)['classification'],'infrastructure')

    def test_independent_review_revalidates_exact_fixture_facts(self):
        facts=dict(source='source',source_run=8,source_contract='original',snapshot=self.frozen_snapshot,
            implementation_snapshot=self.candidate,tests=self.freeze,incident='incident',reviewed_diagnosis='decision',
            red_baseline=self.baseline,qa_paths=[self.path],delivery_approval=False)
        project=SimpleNamespace(fingerprint=self.project.fingerprint,coordination_roles={'lead':'lead'},
                                reviewers_for=self.project.reviewers_for)
        def make(*,actor='cto',protocol=FIXTURE_PROTOCOL,source='source'):
            context=self.store.record('repair_context',dict(release='execution'),dict(**facts,
                repair_kind='fixture',project=project.fingerprint()))
            body=dict(repair_context=context,repair_protocol=protocol,repair_of=source)
            author=Run('proposal',9,'lead','plan',False,'lead','execution',digest(body))
            plan=self.store.record('work_plan',author.binding(),dict(project=project.fingerprint(),repair_body=body,
                document=dict(classification='test_contract',reason='Missing room setup; assertions remain.',test_paths=[self.path])))
            reviewer=Run('proposal',10,actor,'plan',True,'lead','execution',digest(body))
            return self.store.record('plan_review',reviewer.binding(),dict(project=project.fingerprint(),plan=plan,
                verdict=dict(decision='approve',reason='Independent scoped review.',findings=[])))
        with patch('fabriquinha.repairs.fixture_failure',return_value=facts):
            result=real_reviewed(project,self.store,make())
            self.assertEqual(result['proposal']['test_paths'],[self.path])
            for changed in ({'actor':'lead'},{'actor':'backend'},{'protocol':'legacy'},{'source':'other'}):
                with self.subTest(changed=changed),self.assertRaises(ValueError):real_reviewed(project,self.store,make(**changed))

    def test_native_proposal_is_exact_idempotent_and_keeps_source_triage(self):
        body=dict(kind='implementation',release_anchor='anchor')
        source=SimpleNamespace(id='implementation',status='triage',body=json.dumps(body),workspace_path=self.work)
        tests=SimpleNamespace(id='tests',status='done');anchor=SimpleNamespace(id='anchor')
        item=dict(cards=dict(implementation={'id':source.id},tests={'id':tests.id}),package=dict(title='Second'))
        graph=dict(items=[item],submission_depth=2)
        facts=dict(source=source.id,source_run=8,source_contract=digest(body),snapshot=self.frozen_snapshot,
            implementation_snapshot=self.candidate,tests=self.freeze,incident='incident',reviewed_diagnosis='decision',
            red_baseline=self.baseline,qa_paths=[self.path],delivery_approval=False)
        conn=sqlite3.connect(':memory:');self.addCleanup(conn.close);conn.row_factory=sqlite3.Row
        conn.execute('CREATE TABLE tasks(id TEXT,body TEXT,idempotency_key TEXT)');created=[]
        def create(connection,**kwargs):
            created.append(kwargs);connection.execute('INSERT INTO tasks VALUES(?,?,?)',('proposal',kwargs['body'],kwargs['idempotency_key']))
            return 'proposal'
        kb=SimpleNamespace(latest_run=lambda *a:SimpleNamespace(id=8,ended_at=1),create_task=create)
        project=SimpleNamespace(coordination_roles={'lead':'lead'},fingerprint=self.project.fingerprint)
        releases=SimpleNamespace(project=project,store=self.store,board=SimpleNamespace(guard=None),
            check_card=lambda c,card:source if card['id']==source.id else tests,
            closed=lambda *a:(self.freeze,None,None),binding=lambda a:dict(actor='controller',task=a.id,release='execution',contract='anchor'))
        spec=dict(task='approved-plan',approval='approved-brief',document=dict(architecture='HTTP',observability='local'))
        with patch('fabriquinha.repairs.native',return_value=(kb,None,None)),patch('fabriquinha.repairs.fixture_failure',return_value=facts),patch('fabriquinha.repairs.Recovery.expired_effects',return_value=[]):
            operation=Repairs(releases);args=(conn,anchor,spec,item,'incident','decision',graph)
            self.assertEqual(operation.propose_fixture(*args),'proposal')
            self.assertEqual(operation.propose_fixture(*args),'proposal')
            self.assertEqual(len(created),1);self.assertEqual(source.status,'triage')
            self.assertEqual(graph['submission_depth'],2)
            self.assertEqual(created[0]['assignee'],'lead')
            with self.assertRaises(EffectBlocked):operation.propose_fixture(*args[:-1],{**graph,'fixture_depth':1})
            conn.execute('UPDATE tasks SET body=?',('{}',))
            with self.assertRaises(ValueError):operation.propose_fixture(*args)

if __name__=='__main__':unittest.main()
