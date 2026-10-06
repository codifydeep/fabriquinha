import json
from pathlib import Path
import sqlite3
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from planning_status import derive

class StatusTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:'); self.db.row_factory=sqlite3.Row; self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE tasks(id,status); CREATE TABLE task_runs(id,task_id,metadata); INSERT INTO tasks VALUES("t_one","done");')
        self.card=dict(author='produto',reviewer='techlead')
        self.cfg=dict(cards={'t_one':self.card})
        self.state=dict(phase='PLANEJAMENTO_DOCUMENTAL_ATIVO',product_dispatch_enabled=False)
        self.delivery=dict(self.card,revision='a'*64)
        self.approval=dict(self.delivery,approved=True,review_run=2)
        self.db.execute('INSERT INTO task_runs VALUES(?,?,?)',(1,'t_one',json.dumps(dict(immutable_delivery=self.delivery))))
        self.db.execute('INSERT INTO task_runs VALUES(?,?,?)',(2,'t_one',json.dumps(dict(immutable_review=self.approval))))
    def test_completed_without_enabling_implementation(self):
        result=derive(self.state,self.db,self.cfg)
        self.assertEqual(result['planning_status']['state'],'CONCLUIDO')
        self.assertEqual(result['phase'],'PLANEJAMENTO_CONCLUIDO_AGUARDANDO_INTEGRACAO')
        self.assertFalse(result['product_dispatch_enabled'])
    def test_new_submission_invalidates_old_approval(self):
        self.db.execute('INSERT INTO task_runs VALUES(?,?,?)',(3,'t_one',json.dumps(dict(immutable_delivery=dict(self.delivery,revision='b'*64)))))
        self.assertEqual(derive(self.state,self.db,self.cfg)['planning_status']['approved'],0)
    def test_done_without_receipt_is_not_complete(self):
        self.db.execute('DELETE FROM task_runs WHERE id=2')
        self.assertEqual(derive(self.state,self.db,self.cfg)['planning_status']['approved'],0)
    def test_reopened_document_is_pending(self):
        self.db.execute('UPDATE tasks SET status="review"')
        self.assertEqual(derive(self.state,self.db,self.cfg)['planning_status']['state'],'EM_ANDAMENTO')
    def test_preserves_later_operational_phase(self):
        self.state['phase']='VALIDACAO_WORKTREES'
        self.assertEqual(derive(self.state,self.db,self.cfg)['phase'],'VALIDACAO_WORKTREES')
    def test_pr_assessment_separate_and_never_merge(self):
        self.cfg['cards']['t_one']['scope']='pr_review'
        self.state['phase']='REVISAO_PR_EM_ANDAMENTO'
        result=derive(self.state,self.db,self.cfg)
        self.assertEqual(result['planning_status']['total'],0)
        self.assertEqual(result['pr_review_status']['approved'],1)
        self.assertEqual(result['phase'],'PARECER_PR_CONCLUIDO_AGUARDANDO_CONFERENCIA')
        self.assertFalse(result['product_dispatch_enabled'])
    def test_successor_requires_new_approval_and_preserves_history(self):
        self.cfg['cards']['t_one']['superseded_by']='t_two'
        self.cfg['cards']['t_two']=dict(author='produto',reviewer='techlead')
        self.db.execute('INSERT INTO tasks VALUES("t_two","ready")')
        result=derive(self.state,self.db,self.cfg)
        self.assertEqual(result['planning_status']['total'],1)
        self.assertEqual(result['planning_status']['approved'],0)
        self.assertEqual(result['planning_status']['pending'],['t_two'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM task_runs').fetchone()[0],2)

    def test_exact_merge_receipt_updates_status_without_product_release(self):
        self.card.update(scope='pr_review',integration_action='merge_foundation',pr_number=14,head_sha='c'*40,base_sha='d'*40)
        self.state['phase']='REVISAO_PR_EM_ANDAMENTO'
        receipt=dict(merged=True,task='t_one',revision='a'*64,review_run=2,pr=14,head='c'*40,base='d'*40,merge_commit='e'*40)
        self.approval['integration']=receipt
        self.db.execute('UPDATE task_runs SET metadata=? WHERE id=2',(json.dumps(dict(immutable_review=self.approval)),))
        result=derive(self.state,self.db,self.cfg)
        self.assertEqual(result['publication_integrations'],[receipt])
        self.assertFalse(result['product_dispatch_enabled'])
        self.assertNotIn('Concluir revisão',result['next_action'])
        self.assertEqual(derive(result,self.db,self.cfg)['next_action'],result['next_action'])
        receipt['review_run']=1
        self.db.execute('UPDATE task_runs SET metadata=? WHERE id=2',(json.dumps(dict(immutable_review=self.approval)),))
        self.assertEqual(derive(self.state,self.db,self.cfg)['publication_integrations'],[])
