import copy
import unittest
from broker.patch_observation_replan import validate_probe,qualified
import sqlite3


class ObservationReplanTests(unittest.TestCase):
    def setUp(self):
        self.value=dict(operation='installed_patch_persistence_probe_v1',worker_observation_qualified=True,
            worker_uid=10000,probe_sha256='a'*64,handler_sha256='b'*64,synthetic_only=True,
            historical_cause='unknown',product_files_modified=False,author_retry_authorized=False,delivery_approval=False,
            cases=[dict(kind=kind,before=before,after=after,final=final,
                handler=dict(test_hash_observation=dict(before_sha256=before,after_sha256=after,
                    changed=before!=after,delivery_approval=False,author_retry_authorized=False)))
                for kind,before,after,final in [('observed_persistent_change','c'*64,'d'*64,'d'*64),
                    ('observed_unchanged_success','d'*64,'d'*64,'d'*64),
                    ('observed_later_change','d'*64,'e'*64,'d'*64)]])

    def test_actual_fixed_probe_is_not_retry_authorization(self):
        validate_probe(self.value,'a'*64,'b'*64)
        self.assertFalse(self.value['author_retry_authorized'])

    def test_unqualified_worker_source_scope_or_authority_rejected(self):
        for key,value in [('worker_uid',0),('historical_cause','proved'),('probe_sha256','x'),
                ('worker_observation_qualified',False),('author_retry_authorized',True),('synthetic_only',False)]:
            with self.assertRaises(ValueError):validate_probe(dict(self.value,**{key:value}),'a'*64,'b'*64)
        changed=copy.deepcopy(self.value);changed['cases'][0]['handler']['test_hash_observation']['after_sha256']='f'*64
        with self.assertRaises(ValueError):validate_probe(changed,'a'*64,'b'*64)

    def test_unregistered_proposal_cannot_enable_another_diagnosis(self):
        with sqlite3.connect(':memory:') as c:
            self.assertFalse(qualified(c,'issue','source',{},'image'))
            self.assertFalse(qualified(c,'issue','source',{'patch_observation_replan':self.value},'image'))
