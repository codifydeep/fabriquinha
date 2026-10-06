import unittest
from broker import u3_negative_controls as controls


class NegativeControlTests(unittest.TestCase):
    def test_only_fixed_unique_source_mutations_are_allowed(self):
        source=controls.NEEDLE+'\n'+controls.GUARD+'\nreturn;\n}'
        self.assertEqual(controls.mutate(source,'baseline'),source)
        for mode in controls.MODES[1:]:self.assertNotEqual(controls.mutate(source,mode),source)
        with self.assertRaises(ValueError):controls.mutate(source,'shell')
        with self.assertRaises(ValueError):controls.mutate(source+controls.GUARD,'allow_stale_status')
        with self.assertRaises(ValueError):controls.mutate('', 'retain_query')

    def test_status_mutation_preserves_query_guard_and_query_preserves_status(self):
        source=controls.NEEDLE+'\n'+controls.GUARD
        self.assertIn('if (requestedSearch !== currentSearchNeedle()) {',controls.mutate(source,'allow_stale_status'))
        self.assertIn('if (requestedFilter !== currentFilter) {',controls.mutate(source,'allow_stale_query'))
