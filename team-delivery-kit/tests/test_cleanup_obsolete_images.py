import unittest
from cleanup_obsolete_images import select,protected_tag


class ImageSelectionTests(unittest.TestCase):
    def rows(self):return [{'ID':'sha256:'+str(n)*64,'Repository':'delivery-kit-model-proxy','Tag':str(n)} for n in (4,3,2,1)]
    def test_preserves_used_referenced_and_two_newest(self):
        self.assertEqual([s['tags'] for s in select(self.rows(),set(),set())],
            [['delivery-kit-model-proxy:2'],['delivery-kit-model-proxy:1']])
        self.assertEqual(select(self.rows(),{'sha256:'+'2'*64},{'delivery-kit-model-proxy:1'}),[])
    def test_preserves_toso_aliases_external_and_dangling(self):
        self.assertTrue(protected_tag('registry.example/toso-old:latest'))
        for repo,tag in [('toso-old','latest'),('reforma-api','old'),('<none>','<none>')]:
            rows=self.rows()+[dict(ID='sha256:'+'2'*64,Repository=repo,Tag=tag)]
            self.assertNotIn('sha256:'+'2'*64,[s['id'] for s in select(rows,set(),set())])
