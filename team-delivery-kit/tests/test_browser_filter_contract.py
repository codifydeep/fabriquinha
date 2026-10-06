"""Behavioral unit checks of the trusted scenario's observation order."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


def observer():
    source = Path(__file__).resolve().parents[1] / 'browser_feedback_acceptance.py'
    tree = ast.parse(source.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == 'observe_filtered_submission')
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
    return namespace[node.name]


class FilterScenarioContractTests(unittest.TestCase):
    def fixture(self, *, selection='Completed', incorrectly_visible=False):
        events = []
        state = {'selection': selection}
        page = SimpleNamespace(locator=lambda selector: SimpleNamespace(
            filter=lambda **kwargs: 'created-item'))
        def selected(page, name):
            events.append(('selected', name))
            if state['selection'] != name:
                raise AssertionError('selection did not survive POST')
        def choose(page, name):
            events.append(('choose', name))
            state['selection'] = name
        class Expectation:
            def to_have_count(self, count):
                events.append(('count', count))
                if incorrectly_visible or state['selection'] != 'Completed':
                    raise AssertionError('open item leaked into Completed')
            def to_be_visible(self):
                events.append(('visible',))
                if state['selection'] != 'All':
                    raise AssertionError('item not visible in All')
        return page, selected, choose, lambda locator: Expectation(), events

    def test_open_item_is_excluded_until_driver_explicitly_selects_all(self):
        page, selected, choose, expect, events = self.fixture()
        observer()(page, 'created', selected=selected, choose=choose, expect=expect)
        self.assertEqual(events, [('selected', 'Completed'), ('count', 0),
                                  ('choose', 'All'), ('visible',)])

    def test_reset_filter_on_success_is_rejected_before_selecting_all(self):
        page, selected, choose, expect, events = self.fixture(selection='All')
        with self.assertRaisesRegex(AssertionError, 'survive'):
            observer()(page, 'created', selected=selected, choose=choose, expect=expect)
        self.assertNotIn(('choose', 'All'), events)

    def test_open_item_leak_is_rejected_before_selecting_all(self):
        page, selected, choose, expect, events = self.fixture(incorrectly_visible=True)
        with self.assertRaisesRegex(AssertionError, 'leaked'):
            observer()(page, 'created', selected=selected, choose=choose, expect=expect)
        self.assertNotIn(('choose', 'All'), events)
