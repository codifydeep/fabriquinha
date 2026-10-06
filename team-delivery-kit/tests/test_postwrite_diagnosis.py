import json
import sqlite3
import unittest
from broker.postwrite_diagnosis import validate,qualified


class PostwriteDiagnosisTests(unittest.TestCase):
    def test_patch_repair_has_separate_once_only_certificate_not_a_reset(self):
        c=sqlite3.connect(':memory:');self.addCleanup(c.close)
        for table in ('postwrite_diagnoses','postpatch_diagnoses'):
            c.execute('CREATE TABLE '+table+'(issue_id TEXT PRIMARY KEY,receipt TEXT)')
        first=dict(source_task='first',author_retry_authorized=False,delivery_approval=False)
        second=dict(source_task='second',author_retry_authorized=False,delivery_approval=False,
                    repair_kind='postpatch_transport_v2')
        c.execute('INSERT INTO postwrite_diagnoses VALUES (?,?)',('issue',json.dumps(first)))
        c.execute('INSERT INTO postpatch_diagnoses VALUES (?,?)',('issue',json.dumps(second)))
        self.assertTrue(qualified(c,'issue','first',{'postwrite_diagnosis':first}))
        self.assertTrue(qualified(c,'issue','second',{'postwrite_diagnosis':second}))
        self.assertFalse(qualified(c,'issue','second',{'postwrite_diagnosis':first}))

    def test_integrity_is_not_red_or_approval(self):
        proof=dict(operation='postwrite_snapshot_integrity_v1',verified=True,
            baseline_unchanged=True,changed=True,red_verified=False,delivery_approval=False,
            manifest_sha256='a'*64,new_test_sha256='b'*64,previous_test_sha256='c'*64,
            previous_methods=['test_old'],current_methods=['test_new'])
        validate(proof)
        for field,value in [('baseline_unchanged',False),('delivery_approval',True),
                            ('red_verified',True),('changed',False),('new_test_sha256','wrong')]:
            with self.assertRaises(ValueError):validate({**proof,field:value})

    def test_only_matching_durable_nonapproving_receipt_qualifies(self):
        c=sqlite3.connect(':memory:');self.addCleanup(c.close)
        self.assertFalse(qualified(c,'issue','task',{}))
        c.execute('CREATE TABLE postwrite_diagnoses(issue_id TEXT,receipt TEXT)')
        receipt=dict(source_task='task',author_retry_authorized=False,delivery_approval=False)
        c.execute('INSERT INTO postwrite_diagnoses VALUES (?,?)',('issue',json.dumps(receipt)))
        self.assertTrue(qualified(c,'issue','task',{'postwrite_diagnosis':receipt}))
        self.assertFalse(qualified(c,'issue','other',{'postwrite_diagnosis':receipt}))
        self.assertFalse(qualified(c,'issue','task',{'postwrite_diagnosis':{**receipt,'delivery_approval':True}}))


if __name__=='__main__':unittest.main()
