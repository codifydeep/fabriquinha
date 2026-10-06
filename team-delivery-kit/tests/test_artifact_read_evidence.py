import json
import unittest
from artifact_read_evidence import observations, next_read


class ReadEvidenceTests(unittest.TestCase):
    def test_actual_delivery_read_is_observed_without_fabricated_input(self):
        messages = [dict(type='tool_use',tool='read_file',call_id='r',input={}),
            dict(type='tool_result',tool='read_file',call_id='r',output=
                 'Read /delivery/tests/test_a.py — 2 total lines\n\n```python\n1|first\n2|second\n```')]
        self.assertEqual(observations(messages)['/delivery/tests/test_a.py']['lines'],2)
        messages[1]['output']=messages[1]['output'].replace('2|second','2|second... [truncated]')
        self.assertNotIn('/delivery/tests/test_a.py',observations(messages))

    def test_clipped_source_line_is_not_a_complete_read_and_can_be_repaired(self):
        path = '/evidence/candidate/test_long.py'
        messages = [{'role': 'assistant', 'tool_calls': [{'id': 'a', 'function': {
            'name': 'read_file', 'arguments': json.dumps({'path': path, 'offset': 1, 'limit': 3})}}]},
            {'role': 'tool', 'tool_call_id': 'a', 'content': json.dumps({
                'content': '1|before\n2|partial... [truncated]\n3|after', 'total_lines': 3})}]
        self.assertNotIn(path, observations(messages, wire=True))
        self.assertEqual(next_read(messages, path), 2)
        messages += [{'role': 'assistant', 'tool_calls': [{'id': 'b', 'function': {
            'name': 'read_file', 'arguments': json.dumps({'path': path, 'offset': 2, 'limit': 1})}}]},
            {'role': 'tool', 'tool_call_id': 'b', 'content': json.dumps({
                'content': '2|complete source', 'total_lines': 3})}]
        self.assertEqual(observations(messages, wire=True)[path]['lines'], 3)

    def test_single_line_cut_at_character_budget_is_not_a_read(self):
        path = '/evidence/candidate/test_long.py'
        messages = [{'type': 'tool_use', 'tool': 'read_file', 'call_id': 'a', 'input': {'path': path}},
            {'type': 'tool_result', 'call_id': 'a', 'output': json.dumps({
                'content': '1|cut', 'total_lines': 1, 'truncated_by': 'bytes'})}]
        self.assertNotIn(path, observations(messages))

    def test_real_hermes_page_sentinel_is_not_a_source_line(self):
        path = '/evidence/candidate/test_new.py'
        messages = []
        for identifier, offset, content in [('a', 1, '1|one\n2|two\n3|'),
                                             ('b', 3, '3|three\n4|four\n5|')]:
            messages += [{'role': 'assistant', 'tool_calls': [{'id': identifier, 'function': {
                'name': 'read_file', 'arguments': json.dumps({'path': path, 'offset': offset, 'limit': 2})}}]},
                         {'role': 'tool', 'tool_call_id': identifier, 'content': json.dumps({
                             'content': content, 'total_lines': 4, 'truncated': offset == 1})}]
        self.assertEqual(next_read(messages[:2], path), 3)
        self.assertEqual(observations(messages, wire=True)[path]['lines'], 4)

    def test_empty_real_line_is_retained_not_treated_as_sentinel(self):
        path = '/evidence/candidate/test_new.py'
        messages = [{'role': 'assistant', 'tool_calls': [{'id': 'a', 'function': {
            'name': 'read_file', 'arguments': json.dumps({'path': path, 'offset': 1, 'limit': 2})}}]},
                    {'role': 'tool', 'tool_call_id': 'a', 'content': json.dumps({
                        'content': '1|one\n2|', 'total_lines': 2})}]
        self.assertEqual(observations(messages, wire=True)[path]['lines'], 2)

    def test_only_matching_actual_read_result_is_evidence(self):
        path = '/evidence/candidate/tests/test_new.py'
        messages = [{'type': 'text', 'content': 'I read ' + path},
                    {'type': 'tool_use', 'tool': 'read_file', 'call_id': 'r',
                     'input': {'text': 'Reading file: ' + path}},
                    {'type': 'tool_result', 'call_id': 'other', 'output': '1|wrong'},
                    {'type': 'tool_result', 'call_id': 'r', 'output': json.dumps({
                        'content': '1|import unittest\n2|assert True', 'total_lines': 2})}]
        receipt = observations(messages)
        self.assertEqual(receipt[path]['call_id'], 'r')
        self.assertEqual(receipt[path]['lines'], 2)
        self.assertEqual(len(receipt[path]['output_sha256']), 64)
        for output in ('File not found', '{"error":"blocked"}', '{"content":"2|partial"}'):
            self.assertEqual(observations(messages[:2] + [{'type': 'tool_result', 'call_id': 'r', 'output': output}]), {})

    def test_actual_acp_omits_input_and_formats_numbered_pages(self):
        path = '/evidence/candidate/tests/test_new.py'
        messages = []
        for identifier, offset, content in [('a', 1, '1|one\n2|two'), ('b', 3, '3|three')]:
            messages += [{'type': 'tool_use', 'tool': 'read_file', 'call_id': identifier},
                         {'type': 'tool_result', 'call_id': identifier, 'output_truncated': False,
                          'output': f'Read {path} (from line {offset}, limit 100) — 3 total lines\n\n```\n{content}\n```'}]
        self.assertEqual(observations(messages)[path]['lines'], 3)
        self.assertEqual(observations(messages[:2]), {})
        messages[-1]['output_truncated'] = True
        self.assertEqual(observations(messages), {})

    def test_partial_wire_read_advances_instead_of_repeating_first_page(self):
        path = '/evidence/candidate/test_new.py'
        messages = [{'role': 'assistant', 'tool_calls': [{'id': 'a', 'function': {
            'name': 'read_file', 'arguments': json.dumps({'path': path, 'offset': 1})}}]},
                    {'role': 'tool', 'tool_call_id': 'a', 'content': json.dumps({
                        'content': '1|one\n2|two', 'total_lines': 3, 'truncated': True})}]
        self.assertEqual(observations(messages, wire=True), {})
        self.assertEqual(next_read(messages, path), 3)

    def test_dedup_stub_is_not_inspection_and_repetition_is_bounded(self):
        path = '/evidence/candidate/test_new.py'
        messages = []
        for identifier in ('a', 'b'):
            messages += [{'role': 'assistant', 'tool_calls': [{'id': identifier, 'function': {
                'name': 'read_file', 'arguments': json.dumps({'path': path})}}]},
                         {'role': 'tool', 'tool_call_id': identifier, 'content': json.dumps({
                             'status': 'unchanged', 'dedup': True, 'content_returned': False, 'path': path})}]
        self.assertEqual(observations(messages, wire=True), {})
        with self.assertRaisesRegex(ValueError, 'inspection stalled'):
            next_read(messages, path)

    def test_conflicting_pages_do_not_create_complete_evidence(self):
        path = '/evidence/candidate/test_new.py'
        messages = []
        for identifier, content in [('a', '1|original'), ('b', '1|changed')]:
            messages += [{'role': 'assistant', 'tool_calls': [{'id': identifier, 'function': {
                'name': 'read_file', 'arguments': json.dumps({'path': path})}}]},
                         {'role': 'tool', 'tool_call_id': identifier, 'content': json.dumps({
                             'content': content, 'total_lines': 1})}]
        self.assertEqual(observations(messages, wire=True), {})
