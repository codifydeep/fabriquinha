"""Review recovery must not masquerade as test-author syntax recovery."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import TestCase
from unittest.mock import Mock, patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store,digest
from fabriquinha.recovery import Recovery
from fabriquinha.repairs import Repairs

class ReviewHoldRouting(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'private');work=Path(self.tmp.name)/'work';work.mkdir();(work/'app.py').write_text('VALUE=1\n')
        snapshot=self.store.capture(work)
        self.project=NS(fingerprint=lambda:'project',technical_roles={'cto':'cto','lead':'lead'})
        self.source=NS(id='tests',body=json.dumps({'kind':'tests','inputs':{'repair_review':'parent'}}),status='triage',workspace_path=work,title='Tests')
        binding=dict(task='tests',number=10,contract=digest(json.loads(self.source.body)),kind='tests',reviewing=True)
        incident=self.store.record('incident',binding,dict(source='tests',source_run=10,snapshot=snapshot,review_escalation='escalation',block_event=1,cause='cause'))
        body=dict(stage='cto',release='release',inputs={'incident':incident},kind='diagnostic',source='tests',source_run=10)
        self.task=NS(id='cto-task',body=json.dumps(body),status='done',assignee='cto')
        db=dict(actor='cto',kind='diagnostic',reviewing=False,release='release',task=self.task.id,number=11,contract=digest(body))
        experiment=self.store.record('diagnostic_experiment',db,dict(incident=incident))
        self.decision=self.store.record('diagnostic_decision',db,dict(project='project',action='hold',incident=incident,experiment=experiment))
        self.run=NS(id=10,ended_at=1)
        self.kb=NS(get_task=lambda c,id:self.source if id=='tests' else NS(status='done'),latest_run=lambda c,id:self.run if id=='tests' else NS(id=11,ended_at=1,outcome='completed',metadata={'diagnosis':self.decision}),create_task=Mock(return_value='followup'))
        self.conn=Mock();self.conn.execute.return_value.fetchone.return_value=None
        self.recovery=Recovery(self.project,self.store,NS(guard=None))
    def test_settled_review_triage_creates_cto_followup_without_approval(self):
        with patch('fabriquinha.recovery.native',return_value=(self.kb,None,None)):
            self.assertEqual(self.recovery.coordinate_hold(self.conn,self.task,self.decision),['followup'])
        body=json.loads(self.kb.create_task.call_args.kwargs['body'])
        self.assertEqual(body['hold_resolution']['protocol'],'review-author-return-1')
        self.assertEqual(body['inputs'],json.loads(self.task.body)['inputs'])
    def test_active_stale_or_changed_source_cannot_create_followup(self):
        for field,value in [('status','running'),('status','review')]:
            self.source.status=value
            with patch('fabriquinha.recovery.native',return_value=(self.kb,None,None)),self.assertRaises(ValueError):
                self.recovery.coordinate_hold(self.conn,self.task,self.decision)
        self.source.status='triage';self.run.id=9
        with patch('fabriquinha.recovery.native',return_value=(self.kb,None,None)),self.assertRaises(ValueError):
            self.recovery.coordinate_hold(self.conn,self.task,self.decision)
        self.kb.create_task.assert_not_called()
    def test_restart_reuses_same_followup(self):
        with patch('fabriquinha.recovery.native',return_value=(self.kb,None,None)):
            first=self.recovery.coordinate_hold(self.conn,self.task,self.decision)
            body=self.kb.create_task.call_args.kwargs['body']
            self.conn.execute.return_value.fetchone.return_value={'id':first[0],'body':body}
            self.assertEqual(self.recovery.coordinate_hold(self.conn,self.task,self.decision),first)
        self.assertEqual(self.kb.create_task.call_count,1)
    def test_pending_effect_or_changed_snapshot_blocks_handoff(self):
        with patch('fabriquinha.recovery.native',return_value=(self.kb,None,None)),patch.object(self.recovery,'expired_effects',return_value=['pending']),self.assertRaises(ValueError):
            self.recovery.coordinate_hold(self.conn,self.task,self.decision)
        (self.source.workspace_path/'app.py').write_text('VALUE=2\n')
        with patch('fabriquinha.recovery.native',return_value=(self.kb,None,None)),self.assertRaises(ValueError):
            self.recovery.coordinate_hold(self.conn,self.task,self.decision)
        self.kb.create_task.assert_not_called()
    def test_review_hold_does_not_enter_author_syntax_repair(self):
        releases=NS(project=self.project,store=self.store,board=NS(guard=None),binding=lambda anchor:{})
        graph={'items':[{'cards':{'tests':{'id':'tests'},'implementation':{'id':'implementation'}}}]}
        with patch('fabriquinha.repairs.native',return_value=(self.kb,None,None)),patch.object(Recovery,'cards',return_value=[self.task]),patch('fabriquinha.repairs.fixture_author_context',side_effect=AssertionError('review sent to author syntax path')):
            result=Repairs(releases).continue_submission(self.conn,NS(id='anchor'),{},graph)
        self.assertEqual(result,graph)
