import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import start_c10_correction as launch


class LaunchTests(unittest.TestCase):
    def test_other_instance_cannot_dispatch(self):
        with patch.object(launch,'PROJECT','other'),patch.object(launch,'verify') as verify:
            with self.assertRaises(ValueError):launch.main()
            verify.assert_not_called()

    def test_low_budget_never_creates_launch_intent(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(launch,'PRIVATE',Path(folder)), \
             patch.object(launch,'PROJECT','delivery-kit-port2'),patch.object(launch,'verify',return_value=False), \
             patch.object(launch,'verified_main',return_value=launch.SHA), \
             patch.object(launch,'read_model_budget',return_value={'remaining':31}), \
             patch.object(launch.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'reserve'):launch.main()
            run.assert_not_called();self.assertEqual(list(Path(folder).iterdir()),[])

    def test_existing_uncertain_intent_requires_diagnosis_not_respawn(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'portable-supervisor'/(launch.LABEL+'.launch.json');p.parent.mkdir()
            p.write_text(json.dumps({'base_sha':launch.SHA,'stage':'launch_intent'}))
            with patch.object(launch,'PRIVATE',Path(folder)),patch.object(launch,'PROJECT','delivery-kit-port2'), \
                 patch.object(launch,'verify',return_value=False),patch.object(launch,'verified_main',return_value=launch.SHA), \
                 patch.object(launch.subprocess,'run') as run:
                with self.assertRaisesRegex(ValueError,'reconciliation'):launch.main()
                run.assert_not_called()
