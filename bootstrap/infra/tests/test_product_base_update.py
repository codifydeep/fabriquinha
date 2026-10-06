import unittest
from product_base_update import merge,baseline_image
from product_workspace import digest
from product_recovery import CONFIGS

class BaseUpdateTests(unittest.TestCase):
    def test_baseline_uses_qualified_old_config_not_candidate_image(self):
        files={n:'old' for n in CONFIGS};cfg={'enabled_capabilities':{'backend':dict(image='old-image',config_sha256=digest(files),validated_receipt='proof')}}
        self.assertEqual(baseline_image(cfg,files,dict(files={n:'new' for n in CONFIGS},validation_image='candidate')), 'old-image')
        with self.assertRaises(PermissionError):baseline_image({},files,dict(files={},validation_image='candidate'))
    def test_disjoint_changes_keep_both(self):
        self.assertEqual(merge({'a':'old','b':'old'},{'a':'author','b':'old'},{'a':'old','b':'other'}),{'a':'author','b':'other'})
    def test_conflict_is_not_automatically_overwritten(self):
        with self.assertRaises(PermissionError):merge({'a':'old'},{'a':'author'},{'a':'other'})
    def test_same_change_is_not_conflict(self):
        self.assertEqual(merge({'a':'old'},{'a':'new'},{'a':'new'}),{'a':'new'})
    def test_approved_deletion_and_new_base_file(self):
        self.assertEqual(merge({'a':'old'},{},{'a':'old','b':'new'}),{'b':'new'})
