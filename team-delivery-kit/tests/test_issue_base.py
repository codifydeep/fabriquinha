import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'broker' / (name + '.py'))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class IssueBaseTests(unittest.TestCase):
    def test_base_copy_recovers_partial_copy_without_overwrite(self):
        copy = module('base_copy')
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as target:
            with patch.object(copy, 'SOURCE', Path(source)), patch.object(copy, 'TARGET', Path(target)):
                for name in copy.FILES:
                    (Path(source) / name).write_text(name)
                (Path(target) / copy.FILES[0]).write_text(copy.FILES[0])
                copy.main()
                copy.main()
                self.assertEqual({p.name for p in Path(target).iterdir()}, set(copy.FILES))
                (Path(target) / copy.FILES[0]).write_text('tampered')
                with self.assertRaisesRegex(ValueError, 'differs'):
                    copy.main()

    def test_seed_is_idempotent_and_refuses_different_base(self):
        seed = module('seed_workspace')
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as work:
            with patch.object(seed, 'BASE', Path(base)), patch.object(seed, 'WORK', Path(work)):
                files = {}
                for name in seed.FILES:
                    content = name.encode()
                    (Path(base) / name).write_bytes(content)
                    files[name] = hashlib.sha256(content).hexdigest()
                manifest = json.dumps({'base_sha': 'a' * 40, 'files': files}).encode()
                (Path(base) / 'manifest.json').write_bytes(manifest)
                with patch.dict('os.environ', {'BASE_MANIFEST_SHA256': hashlib.sha256(manifest).hexdigest()}):
                    seed.main()
                    (Path(work) / 'calc.py').write_text('implementation')
                    seed.main()
                    self.assertEqual((Path(work) / 'calc.py').read_text(), 'implementation')
                    (Path(work) / '.delivery-kit-base.json').chmod(0o644)
                    (Path(work) / '.delivery-kit-base.json').write_text('{}')
                    with self.assertRaisesRegex(ValueError, 'another base'):
                        seed.main()


if __name__ == '__main__':
    unittest.main()
