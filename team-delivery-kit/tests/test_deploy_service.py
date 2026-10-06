import unittest

from deploy.serve_calc import dispatch


class DeployServiceTests(unittest.TestCase):
    def test_health_reports_exact_source(self):
        status, payload = dispatch('/health', lambda a, b: a * b, lambda x: x * x, 'a' * 40)
        self.assertEqual(status, 200)
        self.assertEqual(payload, {'status': 'ok', 'source_sha': 'a' * 40})

    def test_multiply_uses_deployed_implementation(self):
        status, payload = dispatch('/multiply?left=-7&right=3', lambda a, b: a * b, lambda x: x * x, 'a' * 40)
        self.assertEqual(status, 200)
        self.assertEqual(payload, {'result': -21, 'source_sha': 'a' * 40})

    def test_invalid_input_does_not_execute(self):
        status, payload = dispatch('/multiply?left=abc&right=3', lambda *_: self.fail(), lambda *_: self.fail(), 'a' * 40)
        self.assertEqual(status, 400)
        self.assertIn('error', payload)

    def test_unknown_route(self):
        status, payload = dispatch('/other', lambda *_: self.fail(), lambda *_: self.fail(), 'a' * 40)
        self.assertEqual(status, 404)
        self.assertIn('error', payload)

    def test_square_negative_uses_deployed_feature(self):
        status, payload = dispatch('/square?value=-3', lambda *_: self.fail(), lambda x: x * x, 'a' * 40)
        self.assertEqual(status, 200)
        self.assertEqual(payload, {'result': 9, 'source_sha': 'a' * 40})

    def test_optional_square_absent_in_second_fixture(self):
        status, payload = dispatch('/cube?value=-2', lambda *_: self.fail(),
                                   None, 'a' * 40, lambda x: x * x * x)
        self.assertEqual((status, payload['result']), (200, -8))
        square_status, _ = dispatch('/square?value=2', lambda *_: self.fail(),
                                    None, 'a' * 40, lambda *_: self.fail())
        self.assertEqual(square_status, 404)

    def test_square_rejects_non_integer_input(self):
        status, payload = dispatch('/square?value=nope', lambda *_: self.fail(), lambda *_: self.fail(), 'a' * 40)
        self.assertEqual(status, 400)
        self.assertIn('error', payload)

    def test_cube_negative_uses_deployed_feature(self):
        status, payload = dispatch('/cube?value=-2', lambda *_: self.fail(),
                                   lambda *_: self.fail(), 'a' * 40, lambda x: x * x * x)
        self.assertEqual(status, 200)
        self.assertEqual(payload, {'result': -8, 'source_sha': 'a' * 40})

    def test_cube_rejects_non_integer_input(self):
        status, payload = dispatch('/cube?value=oops', lambda *_: self.fail(),
                                   lambda *_: self.fail(), 'a' * 40, lambda *_: self.fail())
        self.assertEqual(status, 400)
        self.assertIn('error', payload)

    def test_negate_negative_uses_deployed_feature(self):
        status, payload = dispatch('/negate?value=-2', lambda *_: self.fail(),
                                   lambda *_: self.fail(), 'a' * 40,
                                   lambda *_: self.fail(), lambda x: -x)
        self.assertEqual(status, 200)
        self.assertEqual(payload, {'result': 2, 'source_sha': 'a' * 40})

    def test_absolute_negative_uses_deployed_feature(self):
        status, payload = dispatch('/absolute?value=-2', lambda *_: self.fail(),
                                   lambda *_: self.fail(), 'a' * 40,
                                   lambda *_: self.fail(), lambda *_: self.fail(), abs)
        self.assertEqual(status, 200)
        self.assertEqual(payload, {'result': 2, 'source_sha': 'a' * 40})

    def test_double_negative_uses_deployed_feature(self):
        status, payload = dispatch('/double?value=-2', lambda *_: self.fail(),
                                   lambda *_: self.fail(), 'a' * 40,
                                   lambda *_: self.fail(), lambda *_: self.fail(),
                                   lambda *_: self.fail(), lambda x: x * 2)
        self.assertEqual(status, 200)
        self.assertEqual(payload, {'result': -4, 'source_sha': 'a' * 40})
