import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import literal_review_claims as facts


class LiteralReviewClaimsTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        original=b'# caf\xc3\xa9\nNODE_HARNESS = r"""\nsetup();\ncapture();\nstale();\n"""\nclass Checks:\n def test_a(self):\n  self.assertEqual(1, 2)\n'
        seed=original.replace(b'stale();',b'inherited();\nstale();')
        candidate=seed.replace(b'capture();',b'tick();\nflush();\ncapture();')
        self.raw=dict(original=original,seed=seed,candidate=candidate);self.manifests={}
        for name,raw in self.raw.items():self.save(name,raw)

    def save(self,name,raw):
        root=self.root/name;(root/'tests').mkdir(parents=True,exist_ok=True)
        (root/'tests/test.py').write_bytes(raw)
        manifest=json.dumps(dict(files={'tests/test.py':dict(bytes=len(raw),sha256=facts.sha(raw))}),sort_keys=True).encode()
        (root/'manifest.json').write_bytes(manifest);self.manifests[name]=facts.sha(manifest)

    def claim(self,text,predicate='line_changed',basis='seed_to_candidate',tree='candidate'):
        lines=self.raw[tree].decode().splitlines();line=next(i+1 for i,v in enumerate(lines) if text in v)
        return dict(basis=basis,tree=tree,path='tests/test.py',line=line,column=lines[line-1].index(text)+1,quote=text,predicate=predicate)

    def inspect(self,claims):
        return facts.assess(*(self.root/n for n in ('original','seed','candidate')),self.manifests,'tests/test.py',claims)

    def test_current_delta_cannot_be_confused_with_an_inherited_change(self):
        claims=[self.claim('tick();'),self.claim('inherited();'),self.claim('inherited();',basis='original_to_candidate')]
        result=self.inspect(claims)
        self.assertEqual([v['supported'] for v in result['claims']],[True,False,True])
        self.assertEqual(result['comparisons']['seed_to_candidate']['new_changed_lines'],[4,5])
        self.assertFalse(result['delivery_approval']);self.assertFalse(result['source_reset']);self.assertEqual(result['model_calls'],0)

    def test_scope_claim_is_checked_against_exact_literal_span_not_section_name(self):
        result=self.inspect([self.claim('stale();','outside_literal'),self.claim('class Checks:','outside_literal')])
        self.assertEqual([v['supported'] for v in result['claims']],[False,True])

    def test_invalid_quote_column_tree_or_basis_cannot_become_negative_delivery_evidence(self):
        base=self.claim('tick();')
        for edit in (dict(quote='fabricated'),dict(column=0),dict(line=True),dict(tree='workspace'),
                dict(path='../secret'),dict(basis='original_to_seed'),dict(predicate='approve'),dict(extra=True)):
            with self.assertRaises(ValueError):self.inspect([dict(base,**edit)])
        with self.assertRaises(ValueError):self.inspect([base]*4)

    def test_manifest_drift_symlink_or_partial_quote_is_rejected_without_source_execution(self):
        base=self.claim('tick();');self.manifests['seed']='a'*64
        with self.assertRaises(ValueError):self.inspect([base])
        self.save('seed',self.raw['seed']);target=self.root/'candidate/tests/test.py';target.unlink();target.symlink_to(self.root/'seed/tests/test.py')
        with self.assertRaises(ValueError):self.inspect([base])

    def test_changed_assertion_is_not_hidden_by_literal_compliance(self):
        changed=self.raw['candidate'].replace(b'assertEqual(1, 2)',b'assertEqual(1, 1)')
        self.save('candidate',changed);self.raw['candidate']=changed
        result=self.inspect([self.claim('assertEqual(1, 1)','outside_literal')])
        self.assertTrue(result['claims'][0]['supported'])
        self.assertFalse(result['comparisons']['seed_to_candidate']['outside_literal_bytes_preserved'])

    def test_original_and_seed_claims_use_their_own_line_numbers(self):
        old=self.claim('capture();',tree='seed')
        self.assertFalse(self.inspect([old])['claims'][0]['supported'])
        inherited=self.claim('inherited();',tree='seed',basis='original_to_seed')
        self.assertTrue(self.inspect([inherited])['claims'][0]['supported'])

    def test_utf8_columns_and_literal_edge_quotes_use_byte_offsets_correctly(self):
        for name,raw in self.raw.items():
            changed=raw.replace(b'setup();','é setup();'.encode());self.save(name,changed);self.raw[name]=changed
        result=self.inspect([self.claim('setup();','outside_literal'),self.claim('NODE_HARNESS','outside_literal')])
        self.assertEqual([r['supported'] for r in result['claims']],[False,True])

    def test_cli_rejects_duplicate_json_keys_without_claiming_success(self):
        with self.assertRaises(ValueError):json.loads('{"line":1,"line":2}',object_pairs_hook=facts.unique)
        output=io.StringIO()
        with contextlib.redirect_stdout(output):status=facts.main([])
        self.assertEqual(status,1);result=json.loads(output.getvalue())
        self.assertEqual(result['failure'],'ValueError');self.assertFalse(result['review_override'])

    def test_exported_schema_agrees_with_bounded_claim_shape(self):
        from jsonschema import Draft202012Validator
        schema=Draft202012Validator(facts.CLAIM_SCHEMA)
        schema.validate([self.claim('tick();')])
        self.assertTrue(list(schema.iter_errors([dict(self.claim('tick();'),line=True)])))
        self.assertTrue(list(schema.iter_errors([dict(self.claim('tick();'),command='anything')])))

    def test_qualification_program_compiles_and_rejects_unrelated_namespace_before_docker(self):
        import qualify_literal_review_claims as qualification
        from unittest.mock import patch
        compile(qualification.PROGRAM,'fixed-qualification-program','exec')
        with patch.object(qualification.subprocess,'check_output') as docker:
            with self.assertRaises(ValueError):qualification.qualify('toso-one','invalid','sha256:'+'a'*64,[])
        docker.assert_not_called()
