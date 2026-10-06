import json
import os
import unittest
from unittest.mock import patch
from broker import review_tool_policy as policy


class SurgicalFeedbackTests(unittest.TestCase):
    def test_node_feedback_is_source_free_bounded_and_acp_visible(self):
        from surgical_test_edit import DriverSyntaxError,rejection_feedback
        result=rejection_feedback(DriverSyntaxError(
            '[stdin]:2\nPRIVATE_TOKEN\nSyntaxError: missing ) after argument list',
            'first\nsecond\nthird'))
        self.assertEqual(result['driver_diagnostic'],
            {'syntax_category':'missing_parenthesis','driver_line':2})
        self.assertIn('driver_line=2',result['error'])
        self.assertNotIn('PRIVATE',json.dumps(result))
        self.assertFalse(result['delivery_approval'])
        for location in ('0','99999','999999999999999999999999'):
            result=rejection_feedback(DriverSyntaxError('[stdin]:'+location+'\nSECRET', 'line'))
            self.assertNotIn('driver_line',result['driver_diagnostic'])
            self.assertNotIn('SECRET',json.dumps(result))

    def test_rejected_proposal_persists_and_changed_proposal_remains_eligible(self):
        import tempfile,hashlib
        from pathlib import Path
        from surgical_test_edit import edit_file,rejection_feedback
        source=b'import unittest\nDRIVER_BODY = """\nconsole.log("ok");\n"""\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();target=root/'test_new.py';target.write_bytes(source)
            ledger=root/'receipts.json'
            args={'expected_sha256':hashlib.sha256(source).hexdigest(),
                'edits':[{'start_line':3,'end_line':3,'new':'console.log("PRIVATE";\n'}]}
            kwargs=dict(root=root,observed_read=True,driver_only=True,line_ranges=True,rejection_ledger=ledger)
            # Real Node check, never execute the proposed driver.
            with self.assertRaises(ValueError) as first:edit_file(target,args,**kwargs)
            feedback=rejection_feedback(first.exception)
            self.assertEqual(feedback['category'],'driver_syntax_invalid')
            self.assertEqual(feedback['driver_diagnostic']['driver_line'],2)
            self.assertEqual(target.read_bytes(),source)
            self.assertNotIn('PRIVATE',ledger.read_text())
            with patch('surgical_test_edit.subprocess.run',side_effect=AssertionError('must not revalidate identical proposal')):
                with self.assertRaises(ValueError) as duplicate:edit_file(target,args,**kwargs)
            self.assertEqual(rejection_feedback(duplicate.exception)['category'],'identical_rejected_proposal')
            self.assertEqual(target.read_bytes(),source)
            args['edits'][0]['new']='console.log("fixed");\n'
            self.assertTrue(edit_file(target,args,**kwargs)['verified'])

    def test_rejection_ledger_corruption_and_symlink_fail_closed(self):
        import tempfile,hashlib
        from pathlib import Path
        from surgical_test_edit import edit_file
        source=b'import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();target=root/'test_new.py';target.write_bytes(source)
            ledger=root/'receipts.json';ledger.write_text('not json');ledger.chmod(0o600)
            args={'expected_sha256':hashlib.sha256(source).hexdigest(),
                'edits':[{'old':'import unittest','new':'import unittest\nVALUE=1'}]}
            kwargs=dict(root=root,observed_read=True,rejection_ledger=ledger)
            with self.assertRaises(ValueError):edit_file(target,args,**kwargs)
            self.assertEqual(target.read_bytes(),source)
            link=root/'link.json';link.symlink_to(ledger)
            with self.assertRaises(OSError):edit_file(target,args,**{**kwargs,'rejection_ledger':link})
            self.assertEqual(target.read_bytes(),source)

    def test_fragment_diagnostic_is_bounded_source_free_and_acp_visible(self):
        from surgical_test_edit import prepare,rejection_feedback
        from broker.test_author_activity import result_status
        import hashlib
        source=b'import unittest\na="PRIVATE"\nb="PRIVATE"\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n'
        for old,new,reason,count in [('"PRIVATE"','"other"','ambiguous',2),('absent','other','missing',0),('a="PRIVATE"','a="PRIVATE"','unchanged',1)]:
            with self.assertRaises(ValueError) as caught:
                prepare(source,{'expected_sha256':hashlib.sha256(source).hexdigest(),'edits':[{'old':old,'new':new}]})
            result=rejection_feedback(caught.exception)
            self.assertEqual(result['fragment_diagnostic']['index'],1)
            self.assertEqual(result['fragment_diagnostic']['match_count'],count)
            self.assertEqual(result['fragment_diagnostic']['reason'],reason)
            self.assertIn('fragment_index=1',result['error'])
            self.assertNotIn('PRIVATE',json.dumps(result))
            self.assertFalse(result['delivery_approval'])
            self.assertEqual(result_status('surgical_test_edit','surgical_test_edit failed: '+result['error']),'structured_failure')
        with self.assertRaises(ValueError) as caught:
            prepare(source,{'expected_sha256':'0'*64,'edits':[{'old':'"PRIVATE"','new':'other'}]})
        self.assertNotIn('fragment_diagnostic',rejection_feedback(caught.exception))

    def test_late_ambiguous_fragment_rejects_before_any_file_write(self):
        from surgical_test_edit import edit_file,rejection_feedback
        import tempfile,hashlib
        from pathlib import Path
        source=b'import unittest\na="same"\nb="same"\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n'
        with tempfile.TemporaryDirectory() as folder:
            # macOS /var aliases /private/var; the tool correctly requires an
            # already canonical workspace path, just as the Linux worker does.
            root=Path(folder).resolve();target=root/'test_new.py';target.write_bytes(source)
            args={'expected_sha256':hashlib.sha256(source).hexdigest(),'edits':[
                {'old':'a="same"','new':'a="different"'}, {'old':'"','new':"'"}]}
            with self.assertRaises(ValueError) as caught:edit_file(target,args,root=root,observed_read=True)
            self.assertEqual(rejection_feedback(caught.exception)['fragment_diagnostic']['index'],2)
            self.assertEqual(target.read_bytes(),source)
    def test_safe_error_includes_action_and_survives_acp_error_field(self):
        config=dict(path='/workspace/test_new.py',expected_sha256='a'*64,protocol='typed_v2')
        args=dict(path=config['path'],expected_sha256='a'*64,edits=[dict(old='a',new='b')])
        for message,category,action in [
            ('all tests must remain unittest discoverable','unittest_discovery_required','wrap_in_unittest_testcase'),
            ('no preserved test methods','test_methods_missing','retain_original_test_methods'),
            ('test bodies or methods changed','test_bodies_changed','restore_original_test_bodies'),
            ('PRIVATE source or credential','internal_error','request_controller_diagnosis')]:
            with patch.dict(os.environ,{'DELIVERY_EXECUTION_MODE':'implementation',
                    'DELIVERY_SURGICAL_TEST_JSON':json.dumps(config)}),patch('pathlib.Path.read_text',return_value='source'),\
                    patch('surgical_test_edit.edit_file',side_effect=ValueError(message)):
                result=json.loads(policy.controlled('surgical_test_edit',args))
            self.assertEqual(result['category'],category)
            self.assertEqual(result['next_operation'],action)
            self.assertIn(category,result['error'])
            self.assertIn(action,result['error'])
            self.assertFalse(result['delivery_approval'])
            self.assertNotIn('PRIVATE',json.dumps(result))

    def test_no_dynamic_exception_or_filename_disclosure(self):
        from surgical_test_edit import rejection_feedback
        for exception in (SyntaxError('PRIVATE'),PermissionError('/secret/key'),OSError('PRIVATE')):
            result=rejection_feedback(exception)
            self.assertNotIn('PRIVATE',json.dumps(result))
            self.assertNotIn('/secret',json.dumps(result))
            self.assertFalse(result['delivery_approval'])

    def test_native_formatted_error_is_counted_as_failure_never_write(self):
        from broker.test_author_activity import result_status
        self.assertEqual(result_status('surgical_test_edit',
            'Error: surgical_edit_rejected:unittest_discovery_required:wrap_in_unittest_testcase'),
            'structured_failure')
        self.assertEqual(result_status('surgical_test_edit',
            'surgical_test_edit failed: surgical_edit_rejected:unittest_discovery_required:wrap_in_unittest_testcase'),
            'structured_failure')
