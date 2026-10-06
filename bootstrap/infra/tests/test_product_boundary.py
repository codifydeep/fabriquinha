import unittest
from unittest.mock import patch
import product_boundary as boundary

class BoundaryTests(unittest.TestCase):
    def test_pr_review_excludes_implementation_and_test_execution(self):
        with patch.object(boundary,'config',return_value={'cards':{'t_pr':{'scope':'pr_review'}}}):
            scope=boundary.allowed(dict(task='t_pr',mode='review'))
            self.assertIn('product_verdict',scope)
            self.assertNotIn('product_edit',scope)
            self.assertNotIn('product_review_test',scope)
            self.assertEqual(boundary.allowed(dict(task='t_pr',mode='implementation')),set())
    def setUp(self):
        self.config=patch.object(boundary,'config',return_value={'attempt':'trial','cards':{'t_one':{}}})
        self.config.start();self.addCleanup(self.config.stop)
        self.author=dict(task='t_one',mode='implementation')
        self.reviewer=dict(task='t_one',mode='review')

    def test_mode_catalogue(self):
        self.assertIn('product_edit',boundary.allowed(self.author))
        self.assertNotIn('product_edit',boundary.allowed(self.reviewer))
        self.assertNotIn('kanban_complete',boundary.allowed(self.reviewer))

    def test_direct_bypass_denied(self):
        for name in ('terminal','write_file','kanban_complete','kanban_request_review','product_test'):
            self.assertEqual(boundary.intercept(self.reviewer,name,{})['error'],'operation_forbidden')

    def test_foreign_card_denied(self):
        self.assertEqual(boundary.intercept(self.author,'kanban_comment',{'task_id':'other'})['error'],'operation_forbidden')

    def test_closed_has_no_capability(self):
        self.assertEqual(boundary.allowed(dict(task='t_one',mode='closed')),set())

    def test_registered_handlers_recheck_permission(self):
        class Registry:
            def __init__(self):self.handlers={}
            def register(self,**kw):self.handlers[kw['name']]=kw['handler']
        registry=Registry();boundary.register(registry,lambda:True)
        with patch('review_boundary.worker_state',return_value=self.reviewer):
            with self.assertRaises(PermissionError):registry.handlers['product_edit']({})

    def test_unregistered_board_unchanged(self):
        self.assertIsNone(boundary.allowed(dict(task='other',mode='implementation')))
