"""Narrow observer repair contract; no product workspaces or live receipts."""
import unittest
from types import SimpleNamespace
from fabriquinha.observer_maintenance import observer_diff
from fabriquinha.browser import AcceptanceTest

BEFORE = '''from fabriquinha_acceptance import AcceptanceTest
class Demo(AcceptanceTest):
    def open_home(self):
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        return page, errors
    def full_room_pair(self):
        return {'errors': creator_errors + joiner_errors}
    def test_ready(self):
        pair = self.full_room_pair()
        self.assertEqual(pair['errors'], [])
'''
AFTER = BEFORE.replace('errors = []', 'errors = self._browser_errors').replace(
    "        page.on('pageerror', lambda error: errors.append(str(error)))\n", '').replace(
    "        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)\n", '').replace(
    'creator_errors + joiner_errors', 'self._browser_errors')

class ObserverMaintenanceTests(unittest.TestCase):
    def test_exact_repair_preserves_tests(self):
        self.assertTrue(observer_diff(BEFORE, AFTER)['semantic_review_required'])

    def test_rejects_other_changes(self):
        candidates = [AFTER.replace("pair['errors'], []", '[], []'),
            AFTER.replace('self._browser_errors', '[]'),
            AFTER.replace('return page, errors', 'errors.clear()\n        return page, errors'),
            AFTER.replace('def test_ready', 'def disabled_ready'),
            AFTER + '\nload_tests = lambda *args: None\n',
            AFTER.replace('self.assertEqual', 'self.skipTest'), BEFORE]
        for candidate in candidates:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                observer_diff(BEFORE, candidate)

    def test_late_errors_from_both_pages_reach_shared_observer(self):
        class Events:
            def __init__(self): self.handlers = {}
            def on(self, event, callback): self.handlers[event] = callback
            def route(self, *args): pass
            def route_web_socket(self, *args): pass
            def close(self): pass
        contexts = []
        def new_context(**kwargs):
            context = Events(); contexts.append(context); return context
        case = AcceptanceTest()
        case.target = 'http://localhost:8000'
        case._browser_errors = []
        case._browser = SimpleNamespace(new_context=new_context)
        pages = []
        for _ in range(2):
            context = case.new_context(); page = Events(); context.handlers['page'](page); pages.append(page)
        copied = case._browser_errors + []
        live = case._browser_errors
        pages[0].handlers['pageerror']('late JavaScript error')
        pages[1].handlers['console'](SimpleNamespace(type='error', text='late console error'))
        self.assertEqual(copied, [])
        self.assertEqual(live, ['late JavaScript error', 'late console error'])
        case.doCleanups()

class ObserverSnapshotTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from fabriquinha.artifacts import Store
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name); self.store = Store(root/'private'); self.work = root/'work'
        (self.work/'tests').mkdir(parents=True)
        self.path = 'tests/acceptance_observer.py'
        (self.work/self.path).write_text(BEFORE)
        (self.work/'app.py').write_text('VALUE=1\n')
        self.before = self.store.capture(self.work)
        (self.work/self.path).write_text(AFTER)
        self.after = self.store.capture(self.work)

    def check(self, snapshot, paths=None):
        from fabriquinha.observer_maintenance import snapshot_diff
        return snapshot_diff(self.store,self.before,snapshot,paths if paths is not None else [self.path])

    def test_exact_snapshot_and_immutable_origin(self):
        self.assertEqual(set(self.check(self.after)),{self.path})
        self.assertEqual((self.store.tree(self.before)/self.path).read_text(), BEFORE)

    def test_cannot_smuggle_product_config_or_another_test(self):
        for path in ['app.py','tests/acceptance_extra.py','tests/coverage.json','pyproject.toml']:
            with self.subTest(path=path):
                original = (self.work/path).read_bytes() if (self.work/path).exists() else None
                (self.work/path).write_text('changed')
                with self.assertRaises(ValueError): self.check(self.store.capture(self.work))
                if original is None: (self.work/path).unlink()
                else: (self.work/path).write_bytes(original)

    def test_scope_and_inventory_cannot_be_reduced(self):
        for paths in [[], [self.path,self.path], ['tests/../tests/acceptance_observer.py'], ['app.py']]:
            with self.subTest(paths=paths), self.assertRaises(ValueError): self.check(self.after,paths)
        (self.work/self.path).unlink()
        with self.assertRaises(ValueError): self.check(self.store.capture(self.work))
