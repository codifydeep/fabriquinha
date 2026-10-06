import unittest
from product_technical_contract import validate

class TechnicalContractTests(unittest.TestCase):
    def test_requires_explicit_scope_exact_draft_and_complete_brief(self):
        p=dict(technical_contract_revision_allowed=True,target_task='t1',draft_sha256='sha')
        s=dict(target_task='t1',draft_sha256='sha',brief='Preserve runnable compiled HTTP entry, behavioral TDD, full regression suite, independent review and integration before local deployment. Only remove the optional package start convention; do not waive behavior or grant permissions.')
        validate(p,s)
        for packet,spec in ((dict(p,technical_contract_revision_allowed=False),s),(p,dict(s,draft_sha256='stale')),(p,dict(s,grant=True))):
            with self.assertRaises((ValueError,PermissionError)):validate(packet,spec)
