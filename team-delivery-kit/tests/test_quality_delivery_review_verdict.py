"""Snapshot-bound verdict/read fixtures, not native provenance or approval."""
import copy
import hashlib
import json
import unittest
from broker import quality_lifecycle_v2 as q
import quality_delivery_review_verdict as verdict
import test_quality_delivery_review_policy as fixtures


class DeliveryVerdictTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.QualityDeliveryReviewPolicyTests();f.setUp();self.plan=f.plan;self.evidence=f.evidence;self.validation=f.validation
        content='def feature():\n    return False\n';raw=content.encode()
        self.files={'app.py':dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))}
        manifest=q.digest({'files':self.files})
        # This fixture uses a self-consistent candidate manifest throughout.
        self.evidence['green']['manifest_sha256']=manifest
        self.evidence['sensitivity']['manifest_sha256']=manifest
        self.evidence['sensitivity']['green_sha256']=q.digest(self.evidence['green'])
        self.evidence['sensitivity']['positive_sha256']=q.digest(self.evidence['green'])
        self.validation.update(manifest_sha256=manifest,quality_evidence_sha256=q.digest(self.evidence))
        self.value=dict(action='approve_delivery',reason='All acceptance criteria met',manifest_sha256=manifest,
            commit_sha=self.evidence['green']['commit_sha'],plan_sha256=q.digest(self.plan),
            quality_evidence_sha256=q.digest(self.evidence),validation_sha256=q.digest(self.validation),
            criteria=list(self.plan['criteria']),findings=[])
        self.paths=['/delivery/app.py']
        self.messages=[dict(type='tool_use',tool='read_file',call_id='read-1',input=dict(path=self.paths[0],offset=1,limit=100)),
            dict(type='tool_result',tool='read_file',call_id='read-1',output=json.dumps(dict(total_lines=2,content='1|def feature():\n2|    return False')))]

    def parse(self,value=None):return verdict.parse(json.dumps(self.value if value is None else value),self.plan,self.evidence,self.validation)

    def test_exact_approval_and_read_coverage_yield_policy_facts_not_merge_authority(self):
        value=self.parse();observed=verdict.inspect_reads(value,self.files,self.paths,self.messages)
        decision,facts=verdict.approval(self.plan,self.evidence,self.validation,value,observed)
        self.assertEqual(decision['task_id'],self.validation['task_id']);self.assertTrue(decision['complete_reads'])
        self.assertEqual(facts['manifest_sha256'],self.value['manifest_sha256'])
        self.assertFalse(facts['merge_authorized']);self.assertFalse(facts['delivery_approval'])

    def test_changes_need_real_citation_in_the_exact_snapshot(self):
        finding=dict(criterion=self.plan['criteria'][0],path='app.py',line=2,quote='return False',
            expected='Return correct feature value',observed='Constant false result')
        value=self.parse({**self.value,'action':'request_changes','findings':[finding]})
        observed=verdict.inspect_reads(value,self.files,self.paths,self.messages)
        self.assertEqual(observed[self.paths[0]]['line_content'][2],'    return False')
        for change in (dict(line=True),dict(line=3),dict(quote='invented'),dict(path='../secret'),
                dict(criterion='unknown'),dict(expected=''),dict(severity='critical')):
            with self.subTest(change=change),self.assertRaises(ValueError):
                bad=self.parse({**value,'findings':[{**finding,**change}]})
                verdict.inspect_reads(bad,self.files,self.paths,self.messages)

    def test_partial_or_byte_divergent_reads_cannot_support_final_approval(self):
        for messages in ([],self.messages[:1],copy.deepcopy(self.messages)):
            if len(messages)==2:messages[1]['output']=json.dumps(dict(total_lines=2,content='1|def feature():\n2|    return True'))
            with self.subTest(length=len(messages)),self.assertRaises(ValueError):verdict.inspect_reads(self.parse(),self.files,self.paths,messages)

    def test_prior_phase_stale_sha_unknown_authority_or_missing_criteria_rejected(self):
        for change in (dict(action='approve_tests'),dict(action='complete'),dict(commit_sha='0'*40),
                dict(validation_sha256='0'*64),dict(quality_evidence_sha256='0'*64),dict(plan_sha256='0'*64),
                dict(manifest_sha256='0'*64),dict(criteria=[]),dict(merge_authorized=True),dict(reason=' ')):
            with self.subTest(change=change),self.assertRaises(ValueError):self.parse({**self.value,**change})

    def test_duplicate_keys_nonfinite_json_prose_and_large_output_rejected(self):
        for output in ('prose '+json.dumps(self.value),json.dumps(self.value)[:-1]+',"reason":"duplicate"}',
                json.dumps(self.value).replace('"All acceptance criteria met"','NaN'),'x'*16385):
            with self.subTest(length=len(output)),self.assertRaises(ValueError):verdict.parse(output,self.plan,self.evidence,self.validation)

    def test_changes_without_findings_and_approval_with_findings_rejected(self):
        for change in (dict(action='request_changes'),dict(findings=[{}])):
            with self.assertRaises(ValueError):self.parse({**self.value,**change})

    def test_escalation_is_not_an_approval_or_change_request(self):
        value=self.parse({**self.value,'action':'escalate_cto','reason':'Infrastructure evidence needs CTO diagnosis'})
        observed=verdict.inspect_reads(value,self.files,self.paths,self.messages)
        with self.assertRaises(ValueError):verdict.approval(self.plan,self.evidence,self.validation,value,observed)

    def test_prompt_specifies_same_exact_schema_and_frozen_validation_without_approving(self):
        text=verdict.instruction(self.plan,self.evidence,self.validation)
        for key in self.value:self.assertIn(key,text)
        self.assertIn(self.value['validation_sha256'],text)
        self.assertIn(self.value['commit_sha'],text)
        self.assertNotIn('approve_tests',text)
        self.assertNotIn('PLACEHOLDER',text)


if __name__=='__main__':unittest.main()
