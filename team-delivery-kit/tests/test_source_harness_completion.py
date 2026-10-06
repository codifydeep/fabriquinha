import hashlib
import tempfile
import unittest
from pathlib import Path

from broker.source_harness_completion import analyze,qualify,IncompleteHarness,proof_digest,validate_diagnosis


class SourceHarnessCompletionTests(unittest.TestCase):
    def test_controls_completion_preserves_existing_driver_not_needless_rewrite(self):
        trial={'issue_id':'issue','controls_completion_only':True,'qualified_driver_sha256':'d'*64,
            'old_red':{'red':{'test_sha256':{'tests/new.py':'b'*64}}}}
        red={'red':{'test_sha256':{'tests/new.py':'a'*64}}}
        proof={**self.proof(),'driver_changed':False,'candidate_driver_sha256':'d'*64,'previous_driver_sha256':'d'*64}
        self.assertIsNone(qualify(proof,trial,red))
        for k,v in [('added_methods',[]),('candidate_driver_sha256','e'*64),('previous_driver_sha256','e'*64),('driver_changed',True)]:
            with self.subTest(k=k),self.assertRaises(IncompleteHarness):qualify({**proof,k:v},trial,red)
    def diagnosis(self):
        proof={**self.proof(),'driver_changed':False}
        return dict(validation_failure={'volume':'frozen','source_task':'author','output_sha256':proof_digest(proof)},
            harness_diagnosis={'file_sha256':{'tests/new.py':'a'*64}},
            source_harness_admission={'proof':proof,'candidate_volume':'frozen','source_task':'author',
                'trial':{'issue_id':'issue','old_red':{'red':{'test_sha256':{'tests/new.py':'b'*64}}}},
                'red':{'issue_id':'issue','volume':'frozen','red':{'test_sha256':{'tests/new.py':'a'*64}}}})

    def test_admission_diagnosis_requires_exact_blocked_frozen_proof(self):
        route={'issue_id':'issue','test_first_files':['tests/new.py']}
        self.assertIsNone(validate_diagnosis(self.diagnosis(),route))
        for field,value in [('volume','other'),('output_sha256','d'*64)]:
            data=self.diagnosis();data['validation_failure'][field]=value
            with self.assertRaises(ValueError):validate_diagnosis(data,route)
        data=self.diagnosis();data['source_harness_admission']['proof']['driver_changed']=True
        data['validation_failure']['output_sha256']=proof_digest(data['source_harness_admission']['proof'])
        with self.assertRaises(ValueError):validate_diagnosis(data,route)
        data=self.diagnosis();data['source_harness_admission']['red']['issue_id']='other'
        with self.assertRaises(ValueError):validate_diagnosis(data,route)
        data=self.diagnosis();data.pop('source_harness_admission')
        with self.assertRaises(ValueError):validate_diagnosis(data,route)
    def test_identical_driver_is_blocked_despite_changed_preamble_and_preserved_assertions(self):
        with tempfile.TemporaryDirectory() as folder:
            old=Path(folder)/'old.py';new=Path(folder)/'new.py'
            text='DRIVER_BODY="out.genA_newer = genAIdx > genBIdx;"\nclass Case:\n def test_x(self): assert True\n'
            old.write_text(text);new.write_text(text+'PREAMBLE="now patched"\n')
            proof=analyze(old,new)
            self.assertNotEqual(proof['candidate_test_sha256'],proof['previous_test_sha256'])
            self.assertFalse(proof['driver_changed']);self.assertTrue(proof['inverted_chronology'])
            self.assertFalse(proof['approval'])
            trial={'issue_id':'issue','old_red':{'red':{'test_sha256':{'tests/new.py':proof['previous_test_sha256']}}}}
            red={'red':{'test_sha256':{'tests/new.py':proof['candidate_test_sha256']}}}
            with self.assertRaises(IncompleteHarness) as error:qualify(proof,trial,red)
            self.assertEqual(error.exception.incident['owner'],'cto')

    def proof(self):
        return dict(operation='source_harness_structure_v1',approval=False,
            candidate_test_sha256='a'*64,previous_test_sha256='b'*64,
            driver_changed=True,added_methods=['test_negative_query','test_negative_stale'],
            removed_methods=[],inverted_chronology=False,current_first_fifo=False)

    def test_structural_pass_is_nonapproving_and_each_missing_requirement_blocks(self):
        trial={'issue_id':'issue','old_red':{'red':{'test_sha256':{'tests/new.py':'b'*64}}}}
        red={'red':{'test_sha256':{'tests/new.py':'a'*64}}}
        self.assertIsNone(qualify(self.proof(),trial,red))
        for field,value in [('driver_changed',False),('added_methods',[]),('removed_methods',['test_existing']),
                            ('inverted_chronology',True),('current_first_fifo',True)]:
            with self.subTest(field=field),self.assertRaises(IncompleteHarness):
                qualify({**self.proof(),field:value},trial,red)
        for field,value in [('approval',True),('candidate_test_sha256','c'*64)]:
            with self.subTest(field=field),self.assertRaises(ValueError):
                qualify({**self.proof(),field:value},trial,red)
