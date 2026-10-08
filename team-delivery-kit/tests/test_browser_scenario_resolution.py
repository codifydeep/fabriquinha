import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import portable_browser_qa as qa


class ScenarioResolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.incident = {'key': 'a' * 16, 'label': 'FILTER-1', 'phase': 'browser',
                         'parent_issue_id': 'parent', 'source_sha': 'b' * 40}
        folder = self.root / 'browser-acceptance/FILTER-1'
        folder.mkdir(parents=True)
        self.old = folder / ('c' * 64 + '.json')
        self.new = folder / ('d' * 64 + '.json')
        identity = {'source_sha': 'b' * 40, 'application_image': 'image',
                    'deployed_container_id': 'container', 'config': {
                        'scenario': 'feedback-board-filter-v1', 'browser_image': 'sha256:'+'f'*64},
                    'runtime_env': {}, 'scenario_sha256': 'old'}
        self.old.write_text(json.dumps({'identity': identity, 'status': 'failed', 'cleanup': 'passed'}))
        self.new.with_suffix('.png').write_bytes(b'png')
        self.passed = {'identity': {**identity, 'scenario_sha256': hashlib.sha256(qa.SCRIPT.read_bytes()).hexdigest()},
                       'status': 'passed', 'cleanup': 'passed', 'automated': True,
                       'result': {'status': 'passed', 'source_sha': 'b' * 40},
                       'screenshot_sha256': hashlib.sha256(b'png').hexdigest()}
        self.new.write_text(json.dumps(self.passed))

    def register(self):
        return qa.register_scenario_resolution(self.root, self.incident, self.old, self.new,
                                               'Corrected contradictory filter observation.')

    def test_resolution_is_durable_without_rewriting_old_failure(self):
        before = self.old.read_bytes()
        registered = self.register()
        self.assertEqual(qa.scenario_resolution(self.root, self.incident), registered)
        self.assertEqual(self.register(), registered)
        self.assertEqual(self.old.read_bytes(), before)

    def test_changed_product_or_cleanup_failure_cannot_resolve(self):
        for field, value in [('application_image', 'other'), ('source_sha', 'e' * 40)]:
            changed = {**self.passed, 'identity': {**self.passed['identity'], field: value}}
            self.new.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                self.register()
        self.new.write_text(json.dumps({**self.passed, 'cleanup': 'failed'}))
        with self.assertRaises(ValueError):
            self.register()

    def test_receipt_or_scenario_drift_after_registration_is_rejected(self):
        self.register()
        self.new.with_suffix('.png').write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            qa.scenario_resolution(self.root, self.incident)

    def test_non_browser_incident_cannot_use_resolution(self):
        with self.assertRaises(ValueError):
            qa.register_scenario_resolution(self.root, {**self.incident, 'phase': 'candidate'},
                                            self.old, self.new, 'reason')

    def test_new_instrumentation_does_not_rewrite_or_invalidate_frozen_resolution(self):
        registered=self.register()
        with patch.object(qa,'SCRIPT',SimpleNamespace(read_bytes=lambda:b'new instrumented scenario')):
            self.assertEqual(qa.scenario_resolution(self.root,self.incident),registered)
            # New registration still requires CURRENT scenario proof. Existing
            # resolution never approves the new scenario or bypasses qualify().
            with self.assertRaises(ValueError):self.register()
