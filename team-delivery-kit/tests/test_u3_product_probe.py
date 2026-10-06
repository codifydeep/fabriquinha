import hashlib,json,tempfile,unittest
from pathlib import Path
from broker import u3_product_probe as probe

class ProductProbeTests(unittest.TestCase):
    def test_green_original_is_coverage_not_fabricated_red(self):
        before=dict(tests=255,successful=True,failures=[],errors=[],skipped=0)
        after=dict(before,tests=261)
        self.assertEqual(probe.classify(before,after,after),'existing_behavior_coverage_only')
        for changed in (dict(after,errors=['bad']),dict(after,skipped=1),dict(after,tests=260)):
            with self.assertRaises(ValueError):probe.classify(before,changed,after)

    def test_inventory_denies_product_changes_and_stale_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/'base';candidate=Path(tmp)/'candidate';base.mkdir();candidate.mkdir()
            original={'contract.json':b'{}','app.js':b'original','test_previous.py':b'assert True'}
            old={}
            for n,raw in original.items():(base/n).write_bytes(raw);old[n]=probe.sha(raw)
            bm=json.dumps(dict(base_sha='a'*40,files=old)).encode();(base/'manifest.json').write_bytes(bm)
            files={n:v for n,v in original.items() if n!='contract.json'}
            files.update({n:b'# approved test' for n in probe.TESTS})
            def publish():
                entries={}
                for n,v in files.items():
                    p=candidate/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(v)
                    entries[n]=dict(sha256=probe.sha(v),bytes=len(v))
                raw=json.dumps(dict(files=entries)).encode();(candidate/'manifest.json').write_bytes(raw);return probe.sha(raw)
            cm=publish();facts=probe.inventory(base,candidate,probe.sha(bm),cm)
            self.assertTrue(facts['previous_files_unchanged'])
            with self.assertRaises(ValueError):probe.inventory(base,candidate,probe.sha(bm),'0'*64)
            files['app.js']=b'changed';cm=publish()
            with self.assertRaises(ValueError):probe.inventory(base,candidate,probe.sha(bm),cm)
