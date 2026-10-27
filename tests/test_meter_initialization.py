import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('meter_init',Path(__file__).resolve().parents[1]/'scripts/initialize_provider_meter.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class NewMeter(unittest.TestCase):
    def test_storage_bootstrap_rejects_existing_state_before_touching_either_directory(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(module.os,'geteuid',return_value=0):
            root=Path(temporary);meter=root/'meter';secret=root/'secret'
            meter.mkdir();secret.mkdir();(secret/'preserve').write_text('existing')
            with self.assertRaises(ValueError):module.initialize_storage(meter,secret,b'fake-only-key')
            self.assertEqual(list(meter.iterdir()),[])
            self.assertEqual((secret/'preserve').read_text(),'existing')
            with self.assertRaises(ValueError):module.initialize_storage(meter,meter,b'fake-only-key')
            with self.assertRaises(ValueError):module.initialize_storage(meter,secret,b'bad\nvalue')

    def test_new_meter_and_refusal_to_reset_existing_or_partial_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            self.assertEqual(module.initialize(root)['calls'],0)
            counter=root/'calls.json';counter.write_text('{"calls":6953}')
            with self.assertRaises(ValueError):module.initialize(root)
            self.assertEqual(json.loads(counter.read_text())['calls'],6953)
            counter.unlink()
            with self.assertRaises(ValueError):module.initialize(root)
            self.assertFalse(counter.exists())

    def test_symlink_or_public_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);meter=root/'meter';meter.mkdir(mode=0o700)
            alias=root/'alias';alias.symlink_to(meter,target_is_directory=True)
            with self.assertRaises(ValueError):module.initialize(alias)
            meter.chmod(0o755)
            with self.assertRaises(ValueError):module.initialize(meter)
            self.assertEqual(list(meter.iterdir()),[])
