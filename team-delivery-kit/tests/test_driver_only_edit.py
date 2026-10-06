import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import stat

from surgical_test_edit import prepare_driver,edit_file,marker_config,rejection_feedback
from surgical_test_edit import diagnose_driver_proposal


SOURCE=b'''import unittest
DRIVER_PREAMBLE = "unchanged"
DRIVER_BODY = "Promise.resolve().then(() => {"
class Tests(unittest.TestCase):
    def test_existing(self):
        self.assertEqual(1, 1)
'''


def envelope(old,new):
    return {'expected_sha256':hashlib.sha256(SOURCE).hexdigest(),'edits':[{'old':old,'new':new}]}


class DriverOnlyEditTests(unittest.TestCase):
    def test_oversized_proposal_is_not_reported_as_noop_or_applied(self):
        source=SOURCE.replace(b'Promise.resolve().then(() => {',b'Promise.resolve().then(() => {});')
        source+=b'#'+b'x'*(32600-len(source)-2)+b'\n'
        args={'expected_sha256':hashlib.sha256(source).hexdigest(),
            'edits':[{'old':'Promise.resolve().then(() => {});','new':'Promise.resolve().then(() => {});'+(' '*200)}]}
        report=diagnose_driver_proposal(source,args)
        self.assertEqual(report['category'],'file_size_exceeded')
        self.assertEqual(report['proposed_bytes'],32800);self.assertEqual(report['limit_bytes'],32768)
        self.assertFalse(report['files_modified'])
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();target=root/'test_new.py';target.write_bytes(source)
            with self.assertRaisesRegex(ValueError,'file limit'):
                edit_file(target,args,root=root,observed_read=True,driver_only=True)
            self.assertEqual(target.read_bytes(),source)
    def test_controller_diagnostic_is_bounded_and_does_not_apply_proposal(self):
        report=diagnose_driver_proposal(SOURCE,envelope('Promise.resolve().then(() => {','Promise.resolve().then(() => {{'))
        self.assertEqual(report['category'],'driver_syntax_invalid')
        self.assertEqual(report['syntax_category'],'unexpected_end')
        self.assertEqual(report['driver_line'],1)
        self.assertFalse(report['files_modified']);self.assertFalse(report['delivery_approval'])
        self.assertNotIn('stderr',report);self.assertNotIn('source',report)
        report=diagnose_driver_proposal(SOURCE,envelope('unchanged','unchanged'))
        self.assertEqual(report['category'],'no_bounded_change')
        report=diagnose_driver_proposal(SOURCE,envelope('Promise.resolve().then(() => {','Promise.resolve().then(() => {});'))
        self.assertEqual(report['category'],'structurally_valid_proposal')
    def test_v3_marker_is_distinct_and_feedback_is_bounded(self):
        config=marker_config({'messages':[{'role':'user','content':
            'DELIVERY_SURGICAL_TEST_V3:/workspace/test_new.py:'+hashlib.sha256(SOURCE).hexdigest()}]})
        self.assertEqual(config['protocol'],'typed_driver_v3')
        for message,category in [('driver syntax invalid','driver_syntax_invalid'),
                ('outside driver scope changed','outside_driver_scope_changed')]:
            feedback=rejection_feedback(ValueError(message))
            self.assertEqual(feedback['category'],category)
            self.assertFalse(feedback['delivery_approval'])
    def test_only_balanced_driver_passes_actual_node_check(self):
        result=prepare_driver(SOURCE,envelope('Promise.resolve().then(() => {','Promise.resolve().then(() => {});'))
        self.assertIn(b'self.assertEqual(1, 1)',result)

    def test_preamble_change_is_rejected_even_when_tests_are_preserved(self):
        with self.assertRaisesRegex(ValueError,'outside driver'):
            prepare_driver(SOURCE,envelope('unchanged','changed'))

    def test_invalid_driver_is_rejected_before_existing_file_is_modified(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();target=root/'test_new.py';target.write_bytes(SOURCE)
            with patch('surgical_test_edit.os.fstat',return_value=SimpleNamespace(st_mode=stat.S_IFREG|0o666,st_uid=0,st_nlink=1)):
                with self.assertRaisesRegex(ValueError,'driver syntax invalid'):
                    edit_file(target,envelope('Promise.resolve().then(() => {','Promise.resolve().then(() => {{'),
                        root=root,observed_read=True,required_uid=0,driver_only=True)
            self.assertEqual(target.read_bytes(),SOURCE)

    def test_node_check_uses_fixed_argv_and_no_shell(self):
        with patch('surgical_test_edit.subprocess.run',return_value=SimpleNamespace(returncode=0)) as run:
            prepare_driver(SOURCE,envelope('Promise.resolve().then(() => {','Promise.resolve().then(() => {});'))
        self.assertEqual(run.call_args.args[0],['node','--check'])
        self.assertNotIn('shell',run.call_args.kwargs)
