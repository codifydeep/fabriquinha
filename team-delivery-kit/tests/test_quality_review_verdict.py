"""Strict review rejection categories are advice, never automatic decisions."""
import copy
import json
import unittest
from unittest.mock import patch
import quality_review_verdict as verdict


class QualityReviewVerdictTests(unittest.TestCase):
    def setUp(self):
        self.packet=dict(manifest_sha256='a'*64,plan_sha256='b'*64,red_sha256='c'*64,
            plan=dict(criteria=['A01'],new_tests=['tests/test_new.py']))
        self.choice=dict(action='approve_tests',reason='Independent fixture assessment',
            criteria=['A01'],findings=[],**{k:self.packet[k] for k in (
                'manifest_sha256','plan_sha256','red_sha256')})

    def rejected(self,output,category):
        with self.assertRaises(verdict.VerdictRejected) as caught:verdict.parse(output,self.packet)
        self.assertEqual(caught.exception.category,category)
        self.assertIsInstance(caught.exception,ValueError)
        self.assertNotIn('private-fixture',str(caught.exception))

    def test_concrete_changes_required_without_selecting_a_replacement_action(self):
        value={**self.choice,'action':'request_changes','reason':'private-fixture: wait for Green'}
        before=copy.deepcopy(value)
        self.rejected(json.dumps(value),'changes_require_concrete_findings')
        self.assertEqual(value,before)

    def test_exact_json_not_prose_extraction_and_duplicate_keys(self):
        text=json.dumps(self.choice)
        self.rejected('private-fixture\n'+text,'invalid_json')
        self.rejected(text[:-1]+',"action":"approve_tests"}','duplicate_keys')
        self.rejected(text.replace('"findings": []','"findings": NaN'),'non_finite_json')
        # Imported runtimes may raise the process recursion limit. Both a
        # decoded non-object and a decoder recursion failure must fail closed.
        with self.assertRaises(verdict.VerdictRejected):verdict.parse('['*1500+'0'+']'*1500,self.packet)
        with patch.object(verdict.json,'loads',side_effect=RecursionError):
            self.rejected(text,'invalid_json')

    def test_fixed_categories_for_contract_fields_not_private_error_content(self):
        for changes,category in [({'extra':'private-fixture'},'verdict_fields'),
                ({'action':'private-fixture'},'invalid_action'),({'reason':' '},'invalid_reason'),
                ({'manifest_sha256':'0'*64},'snapshot_binding_mismatch'),
                ({'criteria':['A01','A01']},'criteria_mismatch'),
                ({'findings':{}},'invalid_findings'),({'findings':[{}]},'approval_has_findings')]:
            with self.subTest(category=category):self.rejected(json.dumps({**self.choice,**changes}),category)
        self.rejected('','output_type_or_size')
        self.rejected('x'*16385,'output_type_or_size')

    def test_all_existing_actions_preserve_values_and_read_scope(self):
        for action in ('approve_tests','escalate_cto','request_changes'):
            value={**self.choice,'action':action,
                'findings':[dict(path='tests/test_new.py')] if action=='request_changes' else []}
            result=verdict.parse(json.dumps(value),self.packet)
            self.assertEqual(result,value)
            paths=['/delivery/app.py','/delivery/tests/test_new.py']
            self.assertEqual(verdict.required_reads(result,self.packet,paths),
                paths if action!='request_changes' else ['/delivery/tests/test_new.py'])


if __name__=='__main__':unittest.main()
