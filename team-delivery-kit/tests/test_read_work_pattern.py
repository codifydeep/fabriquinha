import json
import unittest
from read_work_pattern import summarize


class ReadWorkPatternTests(unittest.TestCase):
    def read(self,identifier,offset,content):
        return [{'role':'assistant','tool_calls':[{'id':identifier,'function':{'name':'read_file',
            'arguments':json.dumps(dict(path='/workspace/private.py',offset=offset,limit=2))}}]},
            {'role':'tool','tool_call_id':identifier,'content':json.dumps(dict(content=content,total_lines=3))}]

    def test_distinguishes_coverage_and_duplicates_without_printing_source(self):
        messages=self.read('one',1,'1|private\n2|secret')+self.read('two',3,'3|value')
        messages+=self.read('three',3,'3|value')
        result=summarize(messages)
        self.assertEqual(result['duplicate_pages'],1)
        self.assertTrue(result['files'][0]['complete_before_first_edit'])
        self.assertNotIn('private',json.dumps(result));self.assertNotIn('secret',json.dumps(result))

    def test_postedit_reads_do_not_count_as_preedit_evidence(self):
        messages=self.read('one',1,'1|a\n2|b')
        messages+=[{'role':'assistant','tool_calls':[{'function':{'name':'patch'}}]}]
        messages+=self.read('two',3,'3|c')
        self.assertFalse(summarize(messages)['files'][0]['complete_before_first_edit'])

    def test_arguments_and_partial_content_never_fabricate_inspection(self):
        result=summarize(self.read('one',1,'1|... [truncated]'))
        self.assertFalse(result['files'][0]['complete_before_first_edit'])
