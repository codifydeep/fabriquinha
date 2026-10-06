import unittest

from test_runner_policy import (unacceptable_output, validate_argv,
                                validate_workspace_command, workspace_command)


class TestRunnerPolicyTests(unittest.TestCase):
    def test_exact_unittest_and_node_commands(self):
        for argv, root in (
            (['python3', '-m', 'unittest', 'discover', '-s', 'tests', '-q'], 'tests'),
            (['node', '--test'], 'tests'),
            (['python3', '-m', 'unittest', 'discover', '-s', '.', '-q'], '.'),
        ):
            command = workspace_command(argv, [root])
            self.assertEqual(validate_workspace_command(command), argv)

    def test_shell_injection_and_unavailable_runner_rejected(self):
        unsafe = (
            'cd /workspace && node --test; id 2>&1',
            'cd /workspace && node --test ../tests 2>&1',
            'cd /workspace && node --test tests/../private 2>&1',
            'cd /workspace && python3 -m pytest -q tests 2>&1',
            'cd /workspace && python3 -m unittest discover -s tests -q 2>&1; true',
        )
        for command in unsafe:
            with self.subTest(command=command), self.assertRaises(ValueError):
                validate_workspace_command(command)
        with self.assertRaises(ValueError):
            validate_argv(['node', '-e', 'process.exit(0)'], ['tests'])
        with self.assertRaises(ValueError):
            validate_argv(['node', '--test'], ['tests', 'other'])

    def test_node_skips_are_not_green(self):
        self.assertFalse(unacceptable_output('TAP version 13\n# tests 2\n# pass 2\n# skipped 0'))
        self.assertTrue(unacceptable_output('TAP version 13\n# tests 2\n# pass 1\n# skipped 1'))


if __name__ == '__main__':
    unittest.main()
