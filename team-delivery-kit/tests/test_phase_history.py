import json
import unittest
from broker.phase_history import decode,ENVELOPES


class PhaseHistoryTests(unittest.TestCase):
    def test_quoted_markers_and_unicode_are_preserved_for_each_allowed_envelope(self):
        for prefix,marker in ENVELOPES.items():
            history='Dados íntegros.\n'+marker+'"quoted older history"'
            text=prefix+'Criteria may mention '+marker+'as DATA.\n'+marker+json.dumps(history,ensure_ascii=False)
            self.assertEqual(decode(text,prefix,marker),history)

    def test_foreign_prefix_malformed_non_string_or_trailing_records_rejected(self):
        prefix='CURRENT TASK: R2 PRODUCT ONLY.\n';marker=ENVELOPES[prefix]
        for payload in ('{}','null','""','"text" trailing','"text"\n'+marker+'{}',
                        '"text"\n'+marker+'"another record"','"unfinished'):
            with self.subTest(payload=payload),self.assertRaises(ValueError):decode(prefix+marker+payload,prefix,marker)
        with self.assertRaises(ValueError):decode('foreign\n'+marker+'"data"',prefix,marker)
        with self.assertRaises(ValueError):decode(prefix+marker+'"data"',prefix,'OTHER: ')
