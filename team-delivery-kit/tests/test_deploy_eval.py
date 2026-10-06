import unittest
from unittest.mock import patch

import deploy_eval


SHA = 'a' * 40


class DeployIdentityTests(unittest.TestCase):
    def command(self, *args):
        tail = args[-3:]
        if args[-3:] == ('remote', 'get-url', 'origin'):
            return deploy_eval.REMOTE
        if args[-2:] == ('branch', '--show-current'):
            return 'main'
        if args[-3:] == ('status', '--porcelain', '--untracked-files=no'):
            return ''
        if args[-2:] == ('rev-parse', 'HEAD'):
            return SHA
        self.fail('unexpected command: ' + repr(tail))

    def test_exact_main_and_successful_push_ci(self):
        def response(*args):
            if args[-1].endswith('/git/ref/heads/main'):
                return {'object': {'sha': SHA}}
            return {'workflow_runs': [{'head_sha': SHA, 'event': 'push',
                                      'path': '.github/workflows/ci.yml',
                                      'conclusion': 'success', 'html_url': 'https://example.test/run'}]}
        with patch.object(deploy_eval, 'command', side_effect=self.command), \
                patch.object(deploy_eval, 'json_command', side_effect=response):
            self.assertEqual(deploy_eval.trusted_source(), (SHA, 'https://example.test/run'))

    def test_remote_main_mismatch_fails_closed(self):
        with patch.object(deploy_eval, 'command', side_effect=self.command), \
                patch.object(deploy_eval, 'json_command', return_value={'object': {'sha': 'b' * 40}}):
            with self.assertRaisesRegex(ValueError, 'does not match'):
                deploy_eval.trusted_source()

    def test_success_on_different_sha_does_not_authorize_deploy(self):
        def response(*args):
            if args[-1].endswith('/git/ref/heads/main'):
                return {'object': {'sha': SHA}}
            return {'workflow_runs': [{'head_sha': 'b' * 40, 'event': 'push',
                                      'path': '.github/workflows/ci.yml',
                                      'conclusion': 'success', 'html_url': 'https://example.test/run'}]}
        with patch.object(deploy_eval, 'command', side_effect=self.command), \
                patch.object(deploy_eval, 'json_command', side_effect=response):
            with self.assertRaisesRegex(ValueError, 'CI missing'):
                deploy_eval.trusted_source()
