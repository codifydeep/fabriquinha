import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import project_selection


class ProjectSelectionTests(unittest.TestCase):
    def test_default_remains_original_sandbox(self):
        with patch.dict('os.environ', {}, clear=True):
            config = project_selection.current()
        self.assertEqual(config['repository'], 'codifydeep/descartavel')
        self.assertEqual(config['checkout'].name, 'sandbox-github')

    def test_second_repository_uses_only_configuration(self):
        path = project_selection.ROOT / 'projects' / 'descartavel2.json'
        with patch.dict('os.environ', {'DELIVERY_KIT_PROJECT_CONFIG': str(path)}):
            config = project_selection.current()
        self.assertEqual(config['repository'], 'codifydeep/descartavel2')
        self.assertEqual(config['checkout'].name, 'sandbox-github2')

    def test_traversal_and_untrusted_fields_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'project.json'
            for value in [
                {'repository': 'codifydeep/descartavel2', 'checkout': '../truco-online'},
                {'repository': 'other.invalid/repo', 'checkout': 'sandbox-github2'},
                {'repository': 'codifydeep/descartavel2', 'checkout': 'sandbox-github2', 'token': 'secret'},
            ]:
                path.write_text(json.dumps(value))
                with patch.dict('os.environ', {'DELIVERY_KIT_PROJECT_CONFIG': str(path)}):
                    with self.assertRaises(ValueError):
                        project_selection.current()
