import unittest

from broker.test_author_activity import result_status, summarize


class TestAuthorActivityTests(unittest.TestCase):
    def test_exception_names_in_successful_source_read_are_not_failures(self):
        output = 'Read /workspace/tests/test_fixture.py — 2 total lines\n\n```\n1|raise TypeError("error")\n2|password = "example"\n```'
        self.assertEqual(result_status('read_file', output), 'read_returned')
        report = summarize([{'type': 'tool_result', 'tool': 'read_file', 'output': output}],
                           '/workspace/tests/test_new.py')
        self.assertNotIn('password', str(report))
        self.assertNotIn('TypeError', str(report))

    def test_structured_error_overrides_apparent_write_success(self):
        self.assertEqual(result_status('write_file', '{"error":"denied","bytes_written":200}'),
                         'structured_failure')
        self.assertEqual(result_status('write_file', '{"bytes_written":200}'), 'write_returned')
        self.assertEqual(result_status('write_file', '{"bytes_written":0}'), 'unclassified')

    def test_read_code_and_terminal_text_never_prove_a_write(self):
        report = summarize([{'type': 'tool_use', 'tool': 'terminal', 'input': {'text': 'secret command'}},
                            {'type': 'text', 'content': 'I wrote the test'},
                            {'type': 'tool_use', 'tool': 'read_file', 'input': {}}],
                           '/workspace/tests/test_new.py')
        self.assertEqual(report['write_file_call_count'], 0)
        self.assertEqual(report['terminal_side_effects'], 'not_inferred')
        self.assertEqual(report['unrecorded_argument_count'], 1)
        self.assertNotIn('secret command', str(report))

    def test_only_matching_actual_write_calls_are_counted(self):
        report = summarize([{'type': 'tool_use', 'tool': 'write_file',
                             'input': {'path': '/workspace/tests/test_new.py', 'content': 'test'}},
                            {'type': 'tool_use', 'tool': 'write_file',
                             'input': {'path': '/workspace/other.py', 'content': 'test'}}],
                           '/workspace/tests/test_new.py')
        self.assertEqual(report['write_file_call_count'], 2)
        self.assertEqual(report['declared_write_file_call_count'], 1)
        self.assertEqual(report['artifact_existence'], 'must_be_verified_by_controller_snapshot')


if __name__ == '__main__':
    unittest.main()
