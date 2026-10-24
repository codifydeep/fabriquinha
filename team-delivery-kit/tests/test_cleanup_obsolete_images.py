import unittest
from cleanup_obsolete_images import select,protected_tag,plan_digest


class ImageSelectionTests(unittest.TestCase):
    def rows(self):return [{'ID':'sha256:'+str(n)*64,'Repository':'delivery-kit-model-proxy','Tag':str(n)} for n in (4,3,2,1)]
    def test_preserves_used_referenced_and_two_newest(self):
        self.assertEqual([s['tags'] for s in select(self.rows(),set(),set())],
            [['delivery-kit-model-proxy:1'],['delivery-kit-model-proxy:2']])
        self.assertEqual(select(self.rows(),{'sha256:'+'2'*64},{'delivery-kit-model-proxy:1'}),[])

    def test_runtime_selected_helpers_are_protected_even_without_a_live_job(self):
        import cleanup_obsolete_images as cleanup
        refs=cleanup.runtime_references([dict(Config=dict(Env=[
            'BROKER_QUALITY_RED_IMAGE=sha256:'+'1'*64,
            'BROKER_QUALITY_GREEN_JOB_IMAGE=delivery-kit-green:3',
            'OPENROUTER_API_KEY=synthetic',
            'BROKER_QUALITY_CTO=not-an-image']))])
        self.assertEqual(refs,{'sha256:'+'1'*64,'delivery-kit-green:3'})
        self.assertNotIn('sha256:'+'1'*64,[r['id'] for r in select(self.rows(),set(),refs)])

    def test_small_hermes_lane_source_images_are_preserved(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import cleanup_obsolete_images as cleanup
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);kit=root/'team-delivery-kit';kit.mkdir()
            source=root/'src/fabriquinha';source.mkdir(parents=True)
            (root/'Dockerfile.validation').write_text('FROM python@sha256:'+'a'*64+'\n')
            (source/'config.py').write_text('IMAGE="delivery-kit-validator:20261024.1"\n')
            with patch.object(cleanup,'ROOT',kit):refs=cleanup.references()
        self.assertIn('python@sha256:'+'a'*64,refs)
        self.assertIn('delivery-kit-validator:20261024.1',refs)
    def test_preserves_toso_aliases_external_and_dangling(self):
        self.assertTrue(protected_tag('registry.example/toso-old:latest'))
        for repo,tag in [('toso-old','latest'),('reforma-api','old'),('<none>','<none>')]:
            rows=self.rows()+[dict(ID='sha256:'+'2'*64,Repository=repo,Tag=tag)]
            self.assertNotIn('sha256:'+'2'*64,[s['id'] for s in select(rows,set(),set())])

    def test_plan_is_independent_of_docker_list_order(self):
        import itertools
        expected=select(self.rows(),set(),set())
        for rows in itertools.permutations(self.rows()):
            observed=select(rows,set(),set())
            self.assertEqual(observed,expected)
            self.assertEqual(plan_digest(observed),plan_digest(expected))

    def test_opaque_probe_tags_and_unordered_aliases_cannot_establish_retirement_age(self):
        rows=[dict(ID='sha256:'+str(i)*64,Repository='delivery-kit-quality-author-probe',Tag=tag)
            for i,tag in enumerate(('d61ea43a','216a5a23','4c1ad484'))]
        self.assertEqual(select(rows,set(),set()),[])

    def test_numeric_version_order_preserves_two_newest_regardless_of_engine_order(self):
        rows=[dict(ID='sha256:'+str(i)*64,Repository='delivery-kit-worker',Tag=tag)
            for i,tag in enumerate(('20261022.1','20261021.9','20261022.2'))]
        self.assertEqual(select(rows,set(),set()),[dict(id='sha256:'+'1'*64,tags=['delivery-kit-worker:20261021.9'])])

    def test_apply_without_matching_preview_hash_stops_before_any_removal(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        import cleanup_obsolete_images as cleanup
        with patch('sys.argv',['cleanup','--apply','--expect-plan','wrong']),\
                patch.object(cleanup,'containers',return_value=[]),\
                patch.object(cleanup,'references',return_value=set()),\
                patch.object(cleanup,'docker',return_value=SimpleNamespace(stdout='')) as docker:
            with self.assertRaisesRegex(ValueError,'nothing removed'):cleanup.main()
        self.assertFalse(any('rm' in c.args for c in docker.call_args_list))
