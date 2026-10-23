"""Whole-tree contract generation, not agent execution or product evidence."""
import copy
import hashlib
import unittest
import prepare_quality_enrollment as prepare


class EnrollmentPreparationTests(unittest.TestCase):
    def setUp(self):
        self.selection=dict(run_id='10000000-0000-4000-8000-000000000001',
            issue_id='10000000-0000-4000-8000-000000000002',author='10000000-0000-4000-8000-000000000003',
            reviewer='10000000-0000-4000-8000-000000000004',criteria=['A01'],new_tests=['tests/test_new.py'],
            product_files=['app.py'],criterion_tests={'A01':[dict(path='tests/test_new.py',method='test_new')]},
            qa_cases=[dict(path='/health',status=200,expected_json={'status':'ok'})],test_image='python@sha256:'+'a'*64)
        self.blobs={'app.py':b'pass\n','AGENTS.md':b'preserve\n','test_old.py':b'import unittest\n',
            'nested/test_other.py':b'import unittest\n','web/old.test.js':b'// frozen\n'}
    def build(self):
        return prepare.build('codifydeep/descartavel2','b'*40,self.blobs,self.selection,
            '10000000-0000-4000-8000-000000000005')

    def test_whole_tree_protects_nested_python_node_and_every_other_file(self):
        payload=self.build();plan=payload['plan'];contract=payload['contract']
        self.assertEqual(set(contract['files']),set(self.blobs)|{'tests/test_new.py'})
        self.assertEqual(set(plan['baseline_tests']),{'test_old.py','nested/test_other.py'})
        self.assertEqual(plan['node_baseline_tests'],{'web/old.test.js':hashlib.sha256(self.blobs['web/old.test.js']).hexdigest()})
        self.assertEqual(contract['test_command'],['python3','-m','unittest','discover','-s','.','-q'])
        self.assertEqual(set(plan['protected_files']),set(contract['files'])-{'app.py'})
        self.assertIn('tests/test_new.py',plan['protected_files'])
        self.assertNotIn('tests/test_new.py',contract['protected_files'])

    def test_no_existing_test_can_be_declared_new_or_editable(self):
        self.selection['new_tests']=['test_old.py']
        with self.assertRaises(ValueError):self.build()
        self.setUp();self.selection['product_files']=['test_old.py']
        with self.assertRaises(ValueError):self.build()
        self.setUp();self.selection['product_files']=['web/old.test.js']
        with self.assertRaises(ValueError):self.build()

    def test_identity_scope_or_test_command_cannot_be_injected(self):
        for change in (dict(author=self.selection['reviewer']),dict(product_files=['missing.py']),
                dict(test_command=['pytest']),dict(new_tests=['../test_new.py']),dict(run_id='not-a-uuid')):
            original=copy.deepcopy(self.selection);self.selection.update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):self.build()
            self.selection=original


if __name__=='__main__':unittest.main()
