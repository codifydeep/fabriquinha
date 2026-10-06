import json,sqlite3,unittest
from unittest.mock import Mock
from product_work_recall import recall
from product_workspace import digest

class WorkRecallTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE team_decisions(task TEXT,proposal TEXT,verdict TEXT,state TEXT)')
        self.binding=Mock(return_value=dict(attempt='current',task='active'))
        self.binding.cards={'active':{},'known':{'scope':'coordination'},'rejected':{'scope':'coordination'}}
        self.request=dict(operation='work_recall',attempt='current',task='active',run=2,claim='live',query='build')
    def add(self,task='known',decision='approve',state='DELIVERED',tamper=False):
        p=dict(task=task,author='cto',head='a'*40,action='enable_shared_build',reason='Build contract diagnosis',specification={'brief':'Preserve discovery and verify the new build image.'})
        v=dict(reviewer='techlead',run=1,decision=decision,proposal_sha256='bad' if tamper else digest(p),reason='Independent review of build evidence.')
        self.db.execute('INSERT INTO team_decisions VALUES(?,?,?,?)',(task,json.dumps(p),json.dumps(v),state));self.db.commit()
    def test_returns_provenance_without_granting_authority(self):
        self.add();result=recall(self.db,self.binding,self.request)
        self.assertEqual(len(result['items']),1)
        self.assertEqual(result['items'][0]['task'],'known')
        self.assertEqual(result['items'][0]['decision'],'approve')
        self.assertEqual(result['items'][0]['base'],'a'*40)
        self.assertFalse(result['authority'])
        self.assertEqual(result['items'][0]['validity'],'historical_evidence_revalidate_for_current_task')
    def test_unknown_attempt_cards_and_unfinished_decisions_excluded(self):
        self.add('foreign');self.add(state='IN_REVIEW');self.add('rejected',decision='request_changes')
        result=recall(self.db,self.binding,self.request)
        self.assertEqual([x['task'] for x in result['items']],['rejected'])
        self.assertEqual(result['items'][0]['decision'],'request_changes')
    def test_tampered_evidence_not_returned(self):
        self.add(tamper=True);self.assertEqual(recall(self.db,self.binding,self.request)['items'],[])
    def test_query_does_not_execute_sql_or_read_files(self):
        self.add();req=dict(self.request,query="'; DROP TABLE team_decisions; --")
        self.assertEqual(recall(self.db,self.binding,req)['items'],[])
        self.assertEqual(self.db.execute('SELECT count(*) FROM team_decisions').fetchone()[0],1)
    def test_stale_claim_denied_before_read(self):
        self.binding.side_effect=PermissionError('stale claim')
        with self.assertRaises(PermissionError):recall(self.db,self.binding,self.request)
    def test_results_are_bounded_and_no_evidence_mutation(self):
        for _ in range(8):self.add()
        before=self.db.total_changes;result=recall(self.db,self.binding,self.request)
        self.assertEqual(len(result['items']),5);self.assertLess(len(json.dumps(result)),14000)
        self.assertEqual(self.db.total_changes,before)
