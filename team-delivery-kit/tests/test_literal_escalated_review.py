import copy
import json
import unittest
import literal_diagnosis_bundle as bundle
from broker import literal_escalated_review as escalation
import test_literal_review_claims as fixture


class EscalatedReviewTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.LiteralReviewClaimsTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        _,files,_,report=bundle.projection(*(self.f.root/n for n in ('original','seed','candidate')),self.f.manifests,'tests/test.py')
        self.cfg=dict(author='backend',cto='cto',reviewer='lead',test_path='tests/test.py')
        self.s=dict(author_task='author-task',inspection=dict(candidate_manifest_sha256='a'*64,
            stale_witness_selectivity_passed=True,structure=dict(outside_literal_bytes_preserved=True,python_ast_preserved_except_literal=True)),
            diagnosis_bundle=dict(report=report,manifest_sha256='b'*64),finding_audit_decision=dict(value=dict(action='request_review_reconsideration')),
            finding_audit_facts=dict(factual_disagreement_verified=True,facts=dict(claims=[dict(claim=dict(
                basis='seed_to_candidate',tree='candidate',path='tests/test.py',line=8,predicate='line_changed'),supported=False)])),
            reconsideration=dict(task_id='lead-review'))
        self.s['escalated_review_authority']=escalation.authority(self.cfg,self.s)
        self.messages=[]
        texts={'/evidence/candidate/tests/test.py':self.f.raw['candidate'].decode(),
            '/evidence/previous/original/tests/test.py':self.f.raw['original'].decode(),
            '/evidence/previous/seed/tests/test.py':self.f.raw['seed'].decode(),'/evidence/previous/report.json':files['report.json'].decode()}
        # Offline transport fixtures, never native receipts or submitted claims.
        for i,(path,text) in enumerate(texts.items()):
            lines=text.splitlines();identifier='fixture-'+str(i)
            output='Read '+path+' — '+str(len(lines))+' total lines\n\n```text\n'+'\n'.join(str(n+1)+'|'+v for n,v in enumerate(lines))+'\n```'
            self.messages.extend([dict(type='tool_use',tool='read_file',call_id=identifier,input=dict(path=path)),
                dict(type='tool_result',tool='read_file',call_id=identifier,output=output)])

    def value(self,approve=True):
        finding=dict(kind='invalid_harness',tree='candidate',path='tests/test.py',test='__module__',line=4,quote='tick();',expected='real coverage',observed='specific concern')
        return dict(action='approve_test_revision' if approve else 'reject_test_revision',reason='Independent review',optional_files=[],
            manifest_sha256='a'*64,findings=[] if approve else [finding])

    def test_cto_is_distinct_from_author_and_prior_reviewer(self):
        self.assertEqual(self.s['escalated_review_authority']['assigned_reviewer'],'cto')
        for changed in (dict(cto='backend'),dict(cto='lead')):
            with self.assertRaises(ValueError):escalation.authority(dict(self.cfg,**changed),self.s)

    def test_full_durable_reads_bind_exact_bytes_and_approval_has_no_findings(self):
        result=escalation.validate(self.cfg,self.s,self.value(),self.messages)
        self.assertTrue(result['read_bytes_verified']);self.assertFalse(result['delivery_approval'])
        with self.assertRaises(ValueError):escalation.validate(self.cfg,self.s,self.value(),self.messages[:-2])

    def test_changed_transport_bytes_or_stale_manifest_are_not_accepted(self):
        altered=copy.deepcopy(self.messages);altered[1]['output']=altered[1]['output'].replace('tick();','fake();')
        with self.assertRaises(ValueError):escalation.validate(self.cfg,self.s,self.value(),altered)
        value=self.value();value['manifest_sha256']='f'*64
        with self.assertRaises(ValueError):escalation.validate(self.cfg,self.s,value,self.messages)

    def test_rejection_requires_real_citation_and_cannot_claim_removed_protected_tests(self):
        self.assertTrue(escalation.validate(self.cfg,self.s,self.value(False),self.messages)['read_bytes_verified'])
        value=self.value(False);value['findings'][0]['quote']='invented quote'
        with self.assertRaises(ValueError):escalation.validate(self.cfg,self.s,value,self.messages)
        value=self.value(False);value['findings'][0]['kind']='removed_assertion'
        with self.assertRaises(ValueError):escalation.validate(self.cfg,self.s,value,self.messages)
