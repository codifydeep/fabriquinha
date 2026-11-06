import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.quality import validate_control_targets


class ControlTargetPlan(unittest.TestCase):
    def test_all_frozen_targets_must_be_planned_before_execution(self):
        targets=[{'play':'Server accepts a play after the hand ends; expected refusal fails.'},
                 {'card':'Server accepts an unheld card; expected 409 fails.'}]
        validate_control_targets(['play','card'],2,targets)
        for invalid in (targets[:1],targets[::-1]+targets, [targets[0],targets[0]],
                        [targets[0],{'unknown':'wrong case'}],[targets[0],{'card':' '}]):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                validate_control_targets(['play','card'],2,invalid)
