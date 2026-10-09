import json
import unittest
from broker.patch_receipt_contract import receipt, adapt


class PatchReceiptContractTests(unittest.TestCase):
    def test_real_diff_has_non_authorizing_durable_metadata(self):
        result=receipt('patch',json.dumps({'success':True,'diff':'private source diff',
                                         'files_modified':['/workspace/tests/test_new.py']}))
        self.assertTrue(result['changed'])
        self.assertFalse(result['delivery_approval'])
        self.assertNotIn('private source',json.dumps(result))
        self.assertEqual(len(result['diff_sha256']),64)

    def test_noop_cannot_be_reported_as_changed(self):
        for raw in ({'success':True,'no_change':True,'diff':'x'},
                    {'success':True}, {'success':False,'diff':'x'},
                    {'success':True,'error':'private error','diff':'x'}):
            result=receipt('patch',json.dumps(raw))
            self.assertFalse(result['changed'])
            self.assertNotIn('private error',json.dumps(result))

    def test_nonpatch_and_unknown_responses_are_not_reinterpreted(self):
        for tool,raw in (('write_file','{}'),('patch','broken'),('patch','[]')):
            self.assertIsNone(receipt(tool,raw))

    def test_formatter_preserves_receipt_without_changing_handler_result(self):
        anchor='    data = _json_loads_maybe(result)\n    path = str((args or {}).get("path") or "file").strip()\n'
        source='def format_result(tool_name,result,args):\n'+anchor+'    return "legacy"\n'
        changed=adapt(source)
        namespace={'_json_loads_maybe':json.loads,'json':json}
        exec(compile(changed,'<formatter>','exec'),namespace)
        result=json.loads(namespace['format_result']('patch','{"success":true,"no_change":true}',{}))
        self.assertTrue(result['no_change'])
        self.assertFalse(result['changed'])
        self.assertEqual(namespace['format_result']('write_file','{}',{}),'legacy')
        for invalid in ('drift',source+source,changed):
            with self.assertRaises(ValueError):adapt(invalid)
