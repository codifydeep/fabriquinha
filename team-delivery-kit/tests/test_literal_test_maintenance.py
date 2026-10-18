import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import literal_test_maintenance as gate


class LiteralMaintenanceTests(unittest.TestCase):
    SOURCE='''# café: preserve UTF-8 byte offsets
PREFIX = "Expected "
NODE_HARNESS = r"""const value = 1;
console.log(value);
"""
class Checks:
 def test_a(self):
  self.assertEqual(1, 2)
'''.encode()

    def repaired(self):return self.SOURCE.replace(b'const value = 1;',b'const value = 2; // corrected driver')

    def test_only_one_literal_can_change_and_all_outside_bytes_are_preserved(self):
        facts=gate.compare(self.SOURCE,self.repaired(),'NODE_HARNESS')
        self.assertTrue(facts['outside_literal_bytes_preserved']);self.assertEqual(facts['test_methods'],['Checks.test_a'])
        self.assertNotEqual(facts['previous_test_sha256'],facts['candidate_test_sha256'])
        self.assertFalse(facts['delivery_approval']);self.assertFalse(facts['functional_red'])

    def test_assertion_method_name_prefix_or_comment_changes_are_rejected(self):
        for bad in (self.repaired().replace(b'assertEqual(1, 2)',b'assertTrue(True)'),
                self.repaired().replace(b'test_a',b'test_b'),
                self.repaired().replace(b'Expected ',b'New '),
                self.repaired().replace(b'preserve UTF-8',b'changed UTF-8')):
            with self.assertRaises(ValueError):gate.compare(self.SOURCE,bad,'NODE_HARNESS')

    def test_unchanged_literal_oversized_file_and_dynamic_replacement_are_refused(self):
        for bad in (self.SOURCE,self.repaired()+b' '*32768,
                self.SOURCE.replace(b'r"""const value = 1;\nconsole.log(value);\n"""',b'load()')):
            with self.assertRaises(ValueError):gate.compare(self.SOURCE,bad,'NODE_HARNESS')

    def test_unknown_or_duplicate_literal_cannot_expand_scope(self):
        with self.assertRaises(ValueError):gate.compare(self.SOURCE,self.repaired(),'PREFIX;other')
        for old in (self.SOURCE+b'NODE_HARNESS="extra"\n',self.SOURCE.replace(b'NODE_HARNESS =',b'OTHER =')):
            with self.assertRaises(ValueError):gate.compare(old,self.repaired(),'NODE_HARNESS')

    def snapshots(self,weak=False,changed_product=False):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);root=Path(temporary.name)
        harness=gate.protocol.RACE.replace("fs.readFileSync(process.argv[2], 'utf8')","fs.readFileSync(%(source_path)s, 'utf8')")
        harness=harness.replace("const line = {textContent: ''};","const line = {textContent: ''}; let initialCount;")
        harness=harness.replace('  complete(0,7);','  initialCount = requests.length; complete(0,7);')
        harness=harness.replace('JSON.stringify({requests:requests.length,fresh_text:fresh,after_late_text:line.textContent})',
            'JSON.stringify({executed:true,initial_requests:initialCount,poll_requests:requests.length,stale_guard_text:line.textContent})')
        template=('PREFIX = "Newest matching: "\nNODE_HARNESS = {harness}\nclass Checks:\n'
            ' def test_stale_response_never_overwrites_newer_query(self):\n'
            '  self.assertEqual(self.report["stale_guard_text"], PREFIX + "#11")\n'
            ' def test_poll_and_filter_change_request_latest(self):\n'
            '  self.assertEqual(self.report["initial_requests"], 1)\n'
            '  self.assertGreaterEqual(self.report["poll_requests"], 3)\n')
        old=template.format(harness=repr(harness))
        revised=harness+'\n// separate author maintenance\n'
        if weak:revised=revised.replace('stale_guard_text:line.textContent','stale_guard_text:"Newest matching: #11"')
        new=template.format(harness=repr(revised));identities=[]
        for name,source,product in (('previous',old,'unchanged'),('candidate',new,'changed' if changed_product else 'unchanged')):
            directory=root/name;directory.mkdir();(directory/'tests').mkdir();(directory/'tests/test.py').write_text(source);(directory/'app.js').write_text(product)
            files={p:{'sha256':hashlib.sha256((directory/p).read_bytes()).hexdigest(),'bytes':(directory/p).stat().st_size}
                for p in ('tests/test.py','app.js')};encoded=json.dumps({'files':files},sort_keys=True).encode()
            (directory/'manifest.json').write_bytes(encoded);identities.append(hashlib.sha256(encoded).hexdigest())
        return root,identities

    def test_real_node_selectivity_is_required_in_addition_to_static_preservation(self):
        root,hashes=self.snapshots();result=gate.inspect(root/'previous',root/'candidate',*hashes,'tests/test.py','NODE_HARNESS')
        self.assertTrue(result['stale_witness_selectivity_passed']);self.assertTrue(result['non_target_files_unchanged'])
        self.assertEqual(result['reports']['unguarded']['stale_guard_text'],'Newest matching: #4')
        self.assertEqual(result['reports']['guarded']['stale_guard_text'],'Newest matching: #11')
        self.assertFalse(result['delivery_approval']);self.assertFalse(result['product_green'])

    def test_hardcoded_success_cannot_pass_the_selectivity_gate(self):
        root,hashes=self.snapshots(weak=True);result=gate.inspect(root/'previous',root/'candidate',*hashes,'tests/test.py','NODE_HARNESS')
        self.assertFalse(result['stale_witness_selectivity_passed'])

    def test_product_or_other_baseline_bytes_cannot_change(self):
        root,hashes=self.snapshots(changed_product=True)
        with self.assertRaises(ValueError):gate.inspect(root/'previous',root/'candidate',*hashes,'tests/test.py','NODE_HARNESS')
