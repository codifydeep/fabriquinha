"""History is source-backed context, never a new approval or a session dump."""
from contextlib import nullcontext
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store,digest
from fabriquinha.board import Run
from fabriquinha.config import Project
from fabriquinha.intake import DraftActivity,DraftTools
from test_intake import configured,document,work


class ProjectHistory(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.store=Store(Path(folder.name)/'private');self.project=Project.parse(configured())
        self.conn=sqlite3.connect(':memory:');self.conn.row_factory=sqlite3.Row;self.addCleanup(self.conn.close)
        self.conn.execute('create table tasks(id text,body text,created_at integer)')
        self.tasks={};self.runs={}
        self.current=Run('current-brief',30,'product','brief',False,'product','v3','contract')
        self.tasks[self.current.task]=SimpleNamespace(body=json.dumps(dict(objective='Next version',release='v3')))
        self.board=SimpleNamespace(ensure=Mock(),input=Mock(),review=Mock(),review_feedback=Mock(return_value=[]))
        self.kb=SimpleNamespace(get_task=lambda conn,key:self.tasks[key],latest_run=lambda conn,key:self.runs.get(key))
        self.native=(self.kb,SimpleNamespace(connect_closing=lambda:nullcontext(self.conn)),None)

    def old(self,index=1,*,name=None):
        release='v'+str(index);task=name or 'old-release-'+str(index)
        body=dict(version=1,kind='release',project=self.project.fingerprint(),release=release)
        self.tasks[task]=SimpleNamespace(id=task,status='done',body=json.dumps(body))
        self.conn.execute('insert into tasks values(?,?,?)',(task,json.dumps(body),1))
        author=Run('old-brief-'+str(index),index,'product','brief',False,'product',release,'brief-contract')
        proposal=self.store.record('product_brief',author.binding(),dict(project=self.project.fingerprint(),document=document()))
        approval=self.store.record('brief_approval',dict(actor='ceo',task=author.task,release=release,brief=proposal),dict(project=self.project.fingerprint(),decision='approve'))
        planner=replace(author,task='old-plan-'+str(index),actor='lead',author='lead',kind='plan')
        plan=self.store.record('work_plan',planner.binding(),dict(project=self.project.fingerprint(),approval=approval,document=work()))
        review=self.store.record('plan_review',replace(planner,actor='cto',reviewing=True).binding(),dict(project=self.project.fingerprint(),plan=plan,verdict=dict(decision='approve',reason='Reviewed',findings=[])))
        binding=dict(actor='controller',task=task,release=release,contract=digest(body))
        payload=dict(project=self.project.fingerprint(),state='HOMOLOGADA',qualification=True,delivery_approval=False,brief=approval,plan_review=review,commit=f'{index:040x}')
        acceptance=self.store.record('release_acceptance',binding,payload)
        self.runs[task]=SimpleNamespace(id=10+index,outcome='completed',metadata={'release_acceptance':acceptance})
        return dict(task=task,approval=approval,plan=plan,review=review,acceptance=acceptance,payload=payload,binding=binding)

    def evidence(self,run=None):
        tools=DraftTools(DraftActivity(self.project,self.store,self.board,run or self.current))
        with patch('fabriquinha.intake.native',return_value=self.native):return tools.evidence()

    def test_new_project_has_no_invented_memory(self):
        self.assertNotIn('previous_release_context',self.evidence())

    def test_product_receives_prior_decision_without_old_authority_or_sessions(self):
        old=self.old();before=(self.store.root/'receipts'/(old['plan']+'.json')).read_bytes()
        result=self.evidence();self.assertIn('previous_release_context',result)
        history=result['previous_release_context']
        self.assertEqual(history['acceptance'],old['acceptance'])
        self.assertEqual(history['technical_decision']['plan'],old['plan'])
        self.assertEqual(history['technical_decision']['architecture'],work()['architecture'])
        self.assertEqual(history['technical_decision']['author'],'lead');self.assertEqual(history['technical_decision']['reviewer'],'cto')
        self.assertTrue(history['historical_only']);self.assertFalse(history['grants_authority'])
        self.assertNotIn('session',json.dumps(history));self.assertNotIn('tasks',history['technical_decision'])
        self.assertEqual(before,(self.store.root/'receipts'/(old['plan']+'.json')).read_bytes())

    def test_latest_acceptance_uses_native_run_order_not_timestamp_or_lexical_id(self):
        self.old(1,name='zzz');new=self.old(2,name='aaa')
        result=self.evidence();self.assertIn('previous_release_context',result)
        self.assertEqual(result['previous_release_context']['acceptance'],new['acceptance'])

    def test_foreign_acceptance_is_rejected_not_silently_imported(self):
        old=self.old();bad=self.store.record('release_acceptance',old['binding'],{**old['payload'],'project':'f'*64})
        self.runs[old['task']].metadata={'release_acceptance':bad}
        with self.assertRaises(ValueError):self.evidence()

    def test_self_reviewed_old_decision_cannot_become_project_memory(self):
        old=self.old();record=self.store.receipt(old['review']);binding={**record['binding'],'actor':'lead'}
        bad_review=self.store.record('plan_review',binding,record['payload'])
        bad=self.store.record('release_acceptance',old['binding'],{**old['payload'],'plan_review':bad_review})
        self.runs[old['task']].metadata={'release_acceptance':bad}
        with self.assertRaises(ValueError):self.evidence()

    def test_modified_receipt_does_not_survive_content_address_verification(self):
        old=self.old();path=self.store.root/'receipts'/(old['plan']+'.json');data=json.loads(path.read_bytes())
        data['payload']['document']['architecture']='Forged decision';path.chmod(0o600);path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):self.evidence()

    def test_old_business_approval_stays_invalid_for_the_new_plan(self):
        old=self.old();self.board.input.return_value=old['approval']
        run=replace(self.current,kind='plan',actor='lead',author='lead')
        with self.assertRaisesRegex(ValueError,'foreign approved brief'):self.evidence(run)


if __name__=='__main__':unittest.main()
