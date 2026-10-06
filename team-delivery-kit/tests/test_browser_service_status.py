import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from portable_browser_qa import validate


class ServiceStatusQaTests(unittest.TestCase):
    def observer(self):
        path = Path(__file__).resolve().parents[1] / 'browser_feedback_acceptance.py'
        node = next(n for n in ast.parse(path.read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'observe_service_status_api')
        namespace = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
        return namespace[node.name]

    def test_fixed_scenarios_are_selected_without_freeform_code(self):
        for name in ('feedback-board-service-status-api-v1', 'feedback-board-service-status-ui-v1'):
            self.assertEqual(validate({'scenario': name, 'browser_image': 'sha256:' + 'a' * 64})['scenario'], name)
        with self.assertRaises(ValueError):
            validate({'scenario': 'arbitrary-service-status', 'browser_image': 'sha256:' + 'a' * 64})

    def test_real_requests_check_exact_body_and_query_variant(self):
        paths = []
        response = SimpleNamespace(status=200, json=lambda: {'status': 'available'},
                                   headers={'content-type': 'application/json'})
        context = SimpleNamespace(request=SimpleNamespace(get=lambda path: paths.append(path) or response))
        self.observer()(context)
        self.assertEqual(paths, ['http://fixture:8080/service-status', 'http://fixture:8080/service-status?probe=1'])

    def test_missing_route_extra_keys_and_bad_content_type_cannot_pass(self):
        for status, body, content_type in ((404, {}, 'application/json'),
                (200, {'status': 'available', 'source_sha': 'invented'}, 'application/json'),
                (200, {'status': 'unknown'}, 'application/json'),
                (200, {'status': 'available'}, 'text/html')):
            response = SimpleNamespace(status=status, json=lambda: body, headers={'content-type': content_type})
            context = SimpleNamespace(request=SimpleNamespace(get=lambda _: response))
            with self.subTest(status=status, body=body, type=content_type), self.assertRaises(AssertionError):
                self.observer()(context)
