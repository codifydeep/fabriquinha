import json
import os
import unittest
from unittest.mock import Mock, patch
from broker import review_tool_policy as policy
from broker import review_read_gate as gate


class ReviewReadGateTests(unittest.TestCase):
    def setUp(self):
        gate.READS.clear()
        self.path='/delivery/app.js'
        self.env=patch.dict(os.environ,{'DELIVERY_EXECUTION_MODE':'review',
            'DELIVERY_REVIEW_READ_PATHS_JSON':json.dumps([self.path])})
        self.env.start(); self.addCleanup(self.env.stop)

    def read(self,offset,content,total=3):
        args=dict(path=self.path,offset=offset,limit=2)
        handler=Mock(return_value=json.dumps(dict(content=content,total_lines=total)))
        policy.fence('read_file',handler)(args)

    def test_actual_consecutive_pages_required_not_claims_or_requested_ranges(self):
        self.assertEqual(gate.pending()[0]['next_offset'],1)
        self.read(1,'1|one\n2|two\n3|')
        self.assertEqual(gate.pending()[0]['next_offset'],3)
        self.read(3,'3|three\n4|')
        self.assertEqual(gate.pending(),[])

    def test_cut_or_conflicting_lines_never_count_as_full_read(self):
        self.read(1,'1|one... [truncated]\n2|two\n3|')
        self.assertEqual(gate.pending()[0]['next_offset'],1)
        self.read(1,'1|changed\n2|different\n3|')
        self.assertTrue(gate.pending())

    def test_large_or_implicit_pages_rejected_before_handler(self):
        for args in (dict(path=self.path),dict(path=self.path,offset=1,limit=500),
                     dict(path=self.path,offset=True,limit=2)):
            handler=Mock()
            result=json.loads(policy.fence('read_file',handler)(args))
            self.assertEqual(result['error'],'bounded_review_page_required')
            handler.assert_not_called()

    def test_fixed_suite_requires_read_completion_before_any_rpc(self):
        command='cd /workspace && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1'
        with patch.dict(os.environ,{'DELIVERY_TEST_COMMANDS_JSON':json.dumps([command]),
                                   'DELIVERY_REVIEW_SUITE_CAPABILITY':'a'*64}),\
                patch.object(policy.urllib.request,'urlopen') as rpc:
            result=json.loads(policy.controlled('terminal',{'command':command.replace('/workspace','/delivery')}))
            self.assertEqual(result['error'],'review_reads_incomplete')
            self.assertEqual(result['missing'][0]['next_offset'],1)
            rpc.assert_not_called()

    def test_async_read_handler_records_actual_result(self):
        import asyncio
        async def handler(args):return json.dumps(dict(content='1|one\n2|',total_lines=1))
        asyncio.run(policy.fence('read_file',handler,True)(dict(path=self.path,offset=1,limit=1)))
        self.assertEqual(gate.pending(),[])

    def test_no_contract_leaves_existing_review_behavior_unchanged(self):
        with patch.dict(os.environ,{'DELIVERY_REVIEW_READ_PATHS_JSON':''}):
            self.assertIsNone(gate.request(dict(path=self.path)))
            self.assertEqual(gate.pending(),[])
