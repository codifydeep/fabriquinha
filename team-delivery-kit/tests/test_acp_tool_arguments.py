import json
import unittest
from broker.install_acp_tool_arguments import adapt, adapt_tools, upgrade_tools, OLD_DISPLAY, NEW_DISPLAY, ANCHOR, READ_ANCHOR


class ACPArgumentCompatibilityTests(unittest.TestCase):
    def test_installed_formatter_upgrade_is_exact_and_not_repeatable(self):
        self.assertEqual(upgrade_tools(OLD_DISPLAY),NEW_DISPLAY)
        for source in ('drift',OLD_DISPLAY+OLD_DISPLAY,NEW_DISPLAY):
            with self.assertRaises(ValueError):upgrade_tools(source)
    def test_actual_callback_json_strings_are_decoded_before_formatting(self):
        source = 'def callback(tool_info):\n    if True:\n        if True:\n            if True:\n                if True:\n' + ANCHOR + '                    return function_args\n'
        namespace = {'json': json}
        exec(compile(adapt(source), '<pinned-callback>', 'exec'), namespace)
        callback = namespace['callback']
        args = {'path': '/evidence/candidate/test_new.py', 'offset': 1, 'limit': 100}
        self.assertEqual(callback({'arguments': json.dumps(args)}), args)
        self.assertEqual(callback({'arguments': args}), args)
        for malformed in ('broken', '[]', 'null', 42):
            self.assertIsNone(callback({'arguments': malformed}))

    def test_pinned_source_drift_or_double_patch_fails_closed(self):
        for source in ('changed source', ANCHOR + ANCHOR, adapt(ANCHOR)):
            with self.assertRaisesRegex(ValueError, 'callback changed'):
                adapt(source)

    def test_review_evidence_is_not_cut_by_ui_preview_limit(self):
        namespace = {'_truncate_text': lambda text, limit: limit, '_fenced_text': lambda text: text}
        source = 'def format_result(path):\n    header="header"\n    content="content"\n' + READ_ANCHOR
        exec(compile(adapt_tools(source), '<pinned-formatter>', 'exec'), namespace)
        for tree in ('candidate', 'previous'):
            self.assertEqual(namespace['format_result']('/evidence/' + tree + '/test.py'), 131072)
        self.assertEqual(namespace['format_result']('/delivery/app.js'), 131072)
        self.assertEqual(namespace['format_result']('/delivery-not-authorized/app.js'), 5000)
        self.assertEqual(namespace['format_result']('/workspace/test.py'), 5000)
        self.assertEqual(namespace['format_result']('/evidence/candidate-not-authorized/test.py'), 5000)
        with self.assertRaisesRegex(ValueError, 'formatter changed'):
            adapt_tools(adapt_tools(source))
