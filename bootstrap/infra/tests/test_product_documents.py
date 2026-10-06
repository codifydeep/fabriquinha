import unittest
from product_documents import validate_replacements

class DocumentTests(unittest.TestCase):
    def test_design_artifacts(self):
        self.assertTrue(validate_replacements({'design/lobby.html':'<h1>Prototype</h1>','docs/acceptance.md':'# Acceptance'}))
    def test_cannot_change_product_or_tests(self):
        for path in ('server/api.ts','tests/api.test.ts','package.json','AGENTS.md'):
            with self.subTest(path=path),self.assertRaises(PermissionError):validate_replacements({path:'modified'})
