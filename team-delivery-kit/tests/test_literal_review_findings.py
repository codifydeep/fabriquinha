import unittest
import literal_review_findings as contract
import test_literal_review_claims as fixture


class ReviewFindingTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.LiteralReviewClaimsTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def decision(self,line=8,quote='stale();',expected='seed_to_candidate.line_changed=true',observed='seed_to_candidate.line_changed=false'):
        return dict(action='request_review_reconsideration',reason='Investigate a source-bound disagreement, not approve',optional_files=[],findings=[
            dict(kind='review_disagreement',tree='candidate',path='tests/test.py',test='__module__',line=line,
                quote=quote,expected=expected,observed=observed)])

    def assess(self,value):
        return contract.assess(*(self.f.root/n for n in ('original','seed','candidate')),self.f.manifests,'tests/test.py',value)

    def test_cited_unchanged_line_yields_verified_factual_disagreement_not_approval(self):
        value=self.decision();result=self.assess(value)
        self.assertTrue(result['factual_disagreement_verified']);self.assertEqual(result['decision_sha256'],contract.digest(value))
        for flag in contract.FALSE_FLAGS:self.assertFalse(result[flag])

    def test_observation_contradicted_by_source_is_reported_not_promoted_to_approval(self):
        result=self.assess(self.decision(line=4,quote='tick();'))
        self.assertFalse(result['factual_disagreement_verified']);self.assertEqual(result['contradicted_findings'],[0])

    def test_no_free_text_inference_unknown_token_or_mixed_bases(self):
        for change in (dict(expected='looks outside'),dict(observed='original_to_candidate.line_changed=false'),
                dict(observed='seed_to_candidate.line_changed=true'),dict(test='invented'),dict(kind='invalid_harness')):
            value=self.decision();value['findings'][0].update(change)
            with self.assertRaises(ValueError):self.assess(value)

    def test_source_quotes_are_exact_and_ambiguous_quotes_are_rejected(self):
        value=self.decision(quote='not observed')
        with self.assertRaises(ValueError):self.assess(value)
        for name,raw in self.f.raw.items():
            changed=raw.replace(b'stale();',b'stale(); stale();');self.f.raw[name]=changed;self.f.save(name,changed)
        with self.assertRaises(ValueError):self.assess(self.decision())

    def test_previous_tree_is_mapped_to_explicit_original_or_seed_not_guessed(self):
        value=self.decision();value['findings'][0].update(tree='previous',path='seed/tests/test.py',line=5,
            quote='inherited();',expected='original_to_seed.line_changed=false',observed='original_to_seed.line_changed=true')
        self.assertTrue(self.assess(value)['factual_disagreement_verified'])
        value['findings'][0]['path']='tests/test.py'
        with self.assertRaises(ValueError):self.assess(value)
