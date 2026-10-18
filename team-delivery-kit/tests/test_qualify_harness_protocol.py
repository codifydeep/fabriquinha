import copy
import unittest
import qualify_harness_protocol as qualification


class ProtocolQualificationTests(unittest.TestCase):
    def setUp(self):
        self.identity=dict(source_sha256='a'*64,hold_sha256='b'*64,script_sha256='c'*64,image='sha256:'+'d'*64)
        self.source=dict(prepared=dict(manifest_sha256='e'*64,test_sha256={'test.py':'f'*64}))
        self.facts=dict(operation='frozen_harness_protocol_counterexample_v1',candidate_manifest_sha256='e'*64,
            test_sha256={'test.py':'f'*64},probe_sha256='c'*64,snapshot_unchanged=True,frozen_node_harness_executed=True,
            model_calls=0,measurements={k:False for k in qualification.FALSE_FLAGS},
            **{k:False for k in qualification.FALSE_FLAGS})
        self.receipt=dict(operation='qualified_frozen_harness_protocol_counterexample_v1',identity=self.identity,
            facts=self.facts,**{k:False for k in qualification.FALSE_FLAGS})

    def test_exact_source_bound_diagnostic_receipt_is_not_delivery_authority(self):
        self.assertEqual(qualification.validate(self.receipt,self.identity,self.source),self.receipt)

    def test_foreign_probe_snapshot_or_claimed_approval_is_refused(self):
        for mutate in (lambda r:r['facts'].update(probe_sha256='0'*64),
                lambda r:r['facts'].update(candidate_manifest_sha256='0'*64),
                lambda r:r['facts'].update(model_calls=True),
                lambda r:r.update(delivery_approval=True),
                lambda r:r['facts']['measurements'].update(product_green=True),
                lambda r:r.update(extra='untrusted')):
            bad=copy.deepcopy(self.receipt);mutate(bad)
            with self.assertRaises(ValueError):qualification.validate(bad,self.identity,self.source)
