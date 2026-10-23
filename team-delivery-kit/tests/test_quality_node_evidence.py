"""Pure Node facts do not authenticate their own provenance."""
import copy
import unittest
import quality_node_baseline as runner
import quality_node_evidence as evidence
import test_quality_node_baseline as fixtures


class NodeEvidenceTests(unittest.TestCase):
    def prepare(self):
        f=fixtures.NodeBaselineTests();f.setUp();self.addCleanup(f.doCleanups);f.prepare()
        self.f=f;self.value=runner.run(f.root,f.manifest,f.tests)

    def test_passed_facts_require_all_frozen_files_and_bound_manifest(self):
        self.prepare()
        self.assertEqual(evidence.validate(self.value,self.f.tests,manifest=self.f.manifest),self.value)
        with self.assertRaises(ValueError):evidence.validate(self.value,self.f.tests,manifest='0'*64)

    def test_old_diagnostic_unknown_fields_bool_counts_skips_or_claimed_authority_are_rejected(self):
        self.prepare()
        for mutation in ('old','extra','bool','skip','authority','hash','member','version'):
            value=copy.deepcopy(self.value)
            if mutation=='old':value['operation']='full_node_baseline_observation_v1'
            elif mutation=='extra':value['approved']=True
            elif mutation=='bool':value['counts']['fail']=False
            elif mutation=='skip':value['counts']['skipped']=1
            elif mutation=='authority':value['delivery_approval']=True
            elif mutation=='hash':value['captured_output_sha256']='not-a-hash'
            elif mutation=='member':value['inventory'][0]['path']='outside.test.js'
            else:value['node_version']='20.1.0'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):evidence.validate(value,self.f.tests)

    def test_equal_count_different_membership_and_runtime_drift_are_not_frozen_inventory(self):
        self.prepare()
        for mutation in ('member','runtime','line'):
            value=copy.deepcopy(self.value)
            if mutation=='member':value['inventory'][0]['name_sha256']='a'*64
            elif mutation=='line':value['inventory'][0]['line']+=1
            else:value['node_version']='22.0.0' if self.value['node_version'].startswith('24.') else '24.0.0'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):evidence.validate(value,self.f.tests,frozen=self.value)


if __name__=='__main__':unittest.main()
