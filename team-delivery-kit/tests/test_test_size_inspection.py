import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from broker.test_size_inspection import inspect


class SizeInspectionTests(unittest.TestCase):
    def test_exact_historical_content_measured_without_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'tests').mkdir();data=b'x'*38510
            test=root/'tests/test_large.py';test.write_bytes(data)
            facts={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
            encoded=json.dumps({'files':{'tests/test_large.py':facts}}).encode()
            (root/'manifest.json').write_bytes(encoded)
            selection={'manifest_sha256':hashlib.sha256(encoded).hexdigest(),
                       'test_sha256':{'tests/test_large.py':facts['sha256']}}
            self.assertEqual(inspect(root,selection)['files']['tests/test_large.py'],facts)
            self.assertEqual(test.read_bytes(),data)
            test.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'drift'):inspect(root,selection)
