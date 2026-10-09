import copy
import unittest
from scoped_approval_selection import select, PROGRAM


class ScopedApprovalSelectionTests(unittest.TestCase):
    def fixture(self):
        common=('source','reviewer','a'*64,'approved','snapshot','complete','author')
        rows=[('old',*common),('new',*common)]
        delivery=dict(source_task='source',review_task='new',author='author',reviewer='reviewer',
                      manifest_sha256='a'*64,volume='snapshot')
        previous=dict(source_task_id='source',review_task_id='old',reviewer_agent_id='reviewer',
                      manifest_sha256='a'*64,status='approved')
        inspection=dict(operation='qualified_scoped_review_inspection_v1',source_task='source',
            review_task='old',manifest_sha256='a'*64,author_restarted=False,delivery_approval=False,
            read_paths=['/delivery/app.py'],missing_read_paths=['/delivery/app.py'])
        qualification=dict(operation='qualified_product_scope_delivery_v1',issue_id='issue',
                           delivery=delivery,release_homologated=False)
        return rows,dict(delivery=delivery,previous_review=previous,inspection=inspection,qualification=qualification)

    def test_exact_lineage_selects_current_review_without_mutating_history(self):
        rows,report=self.fixture();before=copy.deepcopy(rows)
        self.assertEqual(select('issue',rows,lambda issue,source:report),rows[1])
        self.assertEqual(rows,before)
        self.assertEqual(select('issue',list(reversed(rows)),lambda *_:report),rows[1])
        compile(PROGRAM,'<readonly-canonical-review>','exec')
        self.assertIn('p.qualified(b,issue,delivery)',PROGRAM)
        self.assertNotIn('UPDATE ',PROGRAM)

    def test_multiple_unlinked_approvals_never_choose_latest(self):
        rows,report=self.fixture()
        for bad in (None,{},dict(report,inspection={}),dict(report,previous_review={}),
                    dict(report,qualification={}),dict(report,delivery={}),dict(report,inspection=None)):
            with self.assertRaises(ValueError):select('issue',rows,lambda *_:bad)
        for key,value in (('source_task','other'),('review_task','new'),('author_restarted',True),
                          ('delivery_approval',True),('missing_read_paths',[]),('manifest_sha256','b'*64)):
            bad=copy.deepcopy(report);bad['inspection'][key]=value
            with self.assertRaises(ValueError):select('issue',rows,lambda *_:bad)

    def test_changed_delivery_extra_approval_and_wrong_issue_are_rejected(self):
        rows,report=self.fixture()
        with self.assertRaises(ValueError):select('other',rows,lambda *_:report)
        with self.assertRaises(ValueError):select('issue',rows+[('third',*rows[0][1:])],lambda *_:report)
        for index,value in ((1,'other'),(2,'other'),(3,'b'*64),(5,'other'),(7,'reviewer')):
            bad=[list(row) for row in rows];bad[0][index]=value
            with self.assertRaises(ValueError):select('issue',bad,lambda *_:report)
