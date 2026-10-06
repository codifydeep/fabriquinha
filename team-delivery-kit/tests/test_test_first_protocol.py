import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from broker.test_first_protocol import assess_red, prepare_red, verify_green_tests, save_red_rejection,SnapshotRejection,snapshot_rejection_error
from test_portable_contract import contract


class TestFirstProtocolTests(unittest.TestCase):
    def test_unittest_contract_rejects_pytest_before_snapshot_creation(self):
        for statement in (b'import pytest\n', b'import pytest as pt\n',
                          b'from pytest import mark\n', b'from _pytest import fixtures\n'):
            with self.subTest(statement=statement):
                data = statement + self.new
                (self.work/'tests/test_new.py').write_bytes(data)
                with self.assertRaises(SnapshotRejection) as raised:
                    prepare_red(self.base,self.work,self.red,self.contract)
                receipt = raised.exception.receipt
                self.assertEqual(receipt['category'],'new_test_framework_mismatch')
                self.assertEqual(receipt['files']['tests/test_new.py']['sha256'],
                                 hashlib.sha256(data).hexdigest())
                self.assertEqual(snapshot_rejection_error(receipt),
                                 'test-first NEW test imports an unpinned test framework')
                self.assertEqual(list(self.red.iterdir()),[])

    def test_pytest_text_in_comments_and_literals_is_not_an_import(self):
        data = b'# import pytest\nDESCRIPTION = "from pytest import mark"\n' + self.new
        (self.work/'tests/test_new.py').write_bytes(data)
        self.assertIn('manifest_sha256',prepare_red(self.base,self.work,self.red,self.contract))

    def test_framework_check_is_scoped_to_unittest_command(self):
        from broker.test_first_protocol import validate_test_framework
        data = b'import pytest\ndef test_new(): assert False\n'
        validate_test_framework('tests/new.py',data,['python3','-m','pytest'])
        validate_test_framework('tests/new.py',data,['python3','run_tests.py'])

    def test_empty_new_test_has_durable_hash_bound_rejection(self):
        (self.work/'tests/test_new.py').write_bytes(b'')
        with self.assertRaises(SnapshotRejection) as raised:
            prepare_red(self.base, self.work, self.red, self.contract)
        receipt = raised.exception.receipt
        self.assertEqual(receipt['category'], 'empty_new_test')
        self.assertEqual(receipt['files']['tests/test_new.py'],
                         {'bytes': 0, 'sha256': hashlib.sha256(b'').hexdigest()})
        self.assertEqual(snapshot_rejection_error(receipt), 'test-first NEW test is empty')
        self.assertEqual(list(self.red.iterdir()), [])

    def test_oversized_new_test_is_rejected_before_any_snapshot_is_written(self):
        (self.work/'tests/test_new.py').write_bytes(self.new+b'#'+b'x'*32768)
        with self.assertRaisesRegex(ValueError,'worker snapshot limit'):
            prepare_red(self.base,self.work,self.red,self.contract)
        self.assertEqual(list(self.red.iterdir()),[])

    def test_oversized_receipt_is_not_a_path_correction(self):
        data=self.new+b'#'+b'x'*32768
        (self.work/'tests/test_new.py').write_bytes(data)
        with self.assertRaises(SnapshotRejection) as raised:
            prepare_red(self.base,self.work,self.red,self.contract)
        receipt=raised.exception.receipt
        self.assertEqual(receipt['files']['tests/test_new.py']['bytes'],len(data))
        self.assertEqual(receipt['files']['tests/test_new.py']['sha256'],hashlib.sha256(data).hexdigest())
        self.assertEqual(snapshot_rejection_error(receipt),'test-first NEW test exceeds worker snapshot limit')
        self.assertEqual(snapshot_rejection_error({'kind':'rejected_snapshot','category':'unknown'}),'test-first snapshot rejected')

    def test_only_missing_new_test_with_extra_test_can_be_path_mismatch(self):
        (self.work/'tests/test_new.py').rename(self.work/'tests/test_wrong.py')
        with self.assertRaises(SnapshotRejection) as raised:
            prepare_red(self.base,self.work,self.red,self.contract)
        self.assertEqual(raised.exception.receipt['category'],'test_path_mismatch')
        (self.work/'tests/test_old.py').unlink()
        with self.assertRaises(SnapshotRejection) as raised:
            prepare_red(self.base,self.work,self.red,self.contract)
        self.assertEqual(raised.exception.receipt['category'],'source_layout')

    def test_exact_worker_size_boundary_is_admissible(self):
        data=self.new+b'#'+b'x'*(32768-len(self.new)-1)
        (self.work/'tests/test_new.py').write_bytes(data)
        prepared=prepare_red(self.base,self.work,self.red,self.contract)
        self.assertEqual(prepared['test_sha256']['tests/test_new.py'],hashlib.sha256(data).hexdigest())

    def test_historical_oversized_test_cannot_reuse_hash_as_green_approval(self):
        (self.green/'tests').mkdir()
        data=self.new+b'#'+b'x'*32768
        (self.green/'tests/test_new.py').write_bytes(data)
        with self.assertRaisesRegex(ValueError,'worker snapshot limit'):
            verify_green_tests(self.green,{'test_sha256':{'tests/test_new.py':hashlib.sha256(data).hexdigest()}})

    def test_rejected_red_diagnostic_is_durable_bounded_and_not_approval(self):
        issue = '11111111-1111-4111-8111-111111111111'
        task = '22222222-2222-4222-8222-222222222222'
        prepared = {'manifest_sha256': 'a' * 64, 'test_sha256': {'new.py': 'b' * 64},
                    'command': ['python3', '-m', 'unittest']}
        with tempfile.TemporaryDirectory() as directory:
            record = save_red_rejection(directory, issue, task, 0, 'x' * 7000,
                                        prepared, 'suite already Green')
            self.assertEqual(record['kind'], 'rejected_red')
            self.assertEqual(record['exit_code'], 0)
            self.assertEqual(len(record['output_excerpt']), 6000)
            self.assertTrue(record['output_truncated'])
            self.assertNotIn('red', record)
            self.assertEqual(json.loads((Path(directory) / (task + '.json')).read_text()), record)
            self.assertEqual(save_red_rejection(directory, issue, task, 0, 'retry',
                                               prepared, 'same failure'), record)
            with self.assertRaisesRegex(ValueError, 'identity drift'):
                save_red_rejection(directory, issue, task, 0, '',
                                   dict(prepared, manifest_sha256='c' * 64), 'failure')
            with self.assertRaises(ValueError):
                save_red_rejection(directory, issue, '../escape', 0, '', prepared, 'failure')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.base, self.work, self.red, self.green = (root / name for name in
                                                       ('base', 'work', 'red', 'green'))
        for path in (self.base, self.work, self.red, self.green):
            path.mkdir()
        self.contract = contract()
        self.old = {'AGENTS.md': b'Policy\n', 'app.py': b'VALUE = 0\n',
                    'tests/test_old.py': b'import unittest\nclass Old(unittest.TestCase):\n'
                                         b' def test_old(self): self.assertTrue(True)\n'}
        self.new = b'import unittest\nimport app\nclass New(unittest.TestCase):\n' \
                   b' def test_new(self): self.assertEqual(app.VALUE, 1)\n'
        for name, data in self.old.items():
            for root in (self.base, self.work):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        (self.work / 'tests/test_new.py').write_bytes(self.new)
        (self.base / 'contract.json').write_text(json.dumps(self.contract))
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in self.old.items()}
        hashes['contract.json'] = hashlib.sha256((self.base / 'contract.json').read_bytes()).hexdigest()
        (self.base / 'manifest.json').write_text(json.dumps({'base_sha': 'a' * 40,
                                                              'files': hashes}))

    def test_captures_only_new_tests_and_verifies_red_then_identical_green_tests(self):
        prepared = prepare_red(self.base, self.work, self.red, self.contract)
        self.assertEqual(prepare_red(self.base, self.work, self.red, self.contract, resume=True),
                         prepared)
        self.assertEqual(prepared['test_sha256']['tests/test_new.py'],
                         hashlib.sha256(self.new).hexdigest())
        self.assertEqual((self.red / 'app.py').read_bytes(), self.old['app.py'])
        output = ('FAIL: test_new (tests.test_new.New.test_new)\n'
                  'Ran 2 tests in 0.001s\n\nFAILED (failures=1)\n')
        receipt = assess_red(1, output, prepared)
        self.assertEqual(receipt['exit_code'], 1)
        (self.green / 'tests').mkdir()
        (self.green / 'tests/test_new.py').write_bytes(self.new)
        self.assertTrue(verify_green_tests(self.green, receipt))
        (self.green / 'tests/test_new.py').write_text('def test_new(): pass\n')
        with self.assertRaisesRegex(ValueError, 'test changed after'):
            verify_green_tests(self.green, receipt)

    def test_rejects_code_change_before_red(self):
        (self.work / 'app.py').write_text('VALUE = 1\n')
        with self.assertRaisesRegex(ValueError, 'base file changed before Red'):
            prepare_red(self.base, self.work, self.red, self.contract)

    def test_new_red_receipt_binds_actual_baseline_count_and_pinned_suite(self):
        prepared=prepare_red(self.base,self.work,self.red,self.contract)
        output='FAIL: test_new (tests.test_new.New.test_new)\nRan 2 tests in 0.001s\nFAILED (failures=1)\n'
        receipt=assess_red(1,output,prepared)
        self.assertEqual(receipt['evidence_version'],2)
        self.assertEqual(receipt['test_count'],2)
        self.assertEqual(receipt['base_manifest_sha256'],hashlib.sha256((self.base/'manifest.json').read_bytes()).hexdigest())
        self.assertEqual(receipt['baseline_test_sha256'],{'tests/test_old.py':hashlib.sha256(self.old['tests/test_old.py']).hexdigest()})
        self.assertEqual(receipt['test_image'],self.contract['test_image'])
        with self.assertRaisesRegex(ValueError,'unambiguous'):
            assess_red(1,output+'Ran 1 tests in 0.002s\n',prepared)

    def test_legacy_prepared_red_does_not_gain_checkpoint_evidence(self):
        prepared=prepare_red(self.base,self.work,self.red,self.contract)
        del prepared['base_manifest_sha256'];del prepared['baseline_test_sha256']
        output='FAIL: test_new (tests.test_new.New.test_new)\nRan 2 tests in 0.001s\nFAILED (failures=1)\n'
        self.assertNotIn('evidence_version',assess_red(1,output,prepared))

    def test_accepts_only_the_pinned_workspace_base_marker(self):
        marker = self.work / '.delivery-kit-base.json'
        marker.write_text(json.dumps({
            'base_sha': 'a' * 40,
            'manifest_sha256': hashlib.sha256((self.base / 'manifest.json').read_bytes()).hexdigest(),
        }))
        self.assertIn('manifest_sha256', prepare_red(self.base, self.work, self.red,
                                                      self.contract))
        self.assertFalse((self.red / marker.name).exists())
        marker.write_text(json.dumps({'base_sha': 'b' * 40,
                                      'manifest_sha256': '0' * 64}))
        with self.assertRaisesRegex(ValueError, 'base marker mismatch'):
            prepare_red(self.base, self.work, self.red, self.contract, resume=True)

    def test_rejects_extra_code_and_missing_test(self):
        (self.work / 'extra.py').write_text('pass\n')
        with self.assertRaisesRegex(ValueError, 'workspace changed code'):
            prepare_red(self.base, self.work, self.red, self.contract)
        (self.work / 'extra.py').unlink()
        (self.work / 'tests/test_new.py').unlink()
        with self.assertRaisesRegex(ValueError, 'omitted tests'):
            prepare_red(self.base, self.work, self.red, self.contract)

    def test_rejects_fake_red_and_collection_error(self):
        prepared = prepare_red(self.base, self.work, self.red, self.contract)
        output = 'Ran 2 tests in 0.001s\n\nFAILED (failures=1)\n'
        with self.assertRaisesRegex(ValueError, 'new test method'):
            assess_red(1, output, prepared)
        with self.assertRaisesRegex(ValueError, 'executed failing'):
            assess_red(0, 'FAIL: test_new (tests.test_new.New.test_new)\n' + output,
                       prepared)

    @unittest.skipUnless(os.environ.get('RUN_TEST_FIRST_DOCKER') == '1',
                         'explicit offline Docker smoke only')
    def test_controller_copy_and_red_execute_offline(self):
        self.red.chmod(0o777)
        image = os.environ['TEST_FIRST_BROKER_IMAGE']
        copied = subprocess.run([
            'docker', 'run', '--rm', '--network', 'none', '--read-only',
            '--label','com.docker.compose.project=delivery-kit-port2',
            '--label','com.docker.compose.service=incremental-red-copy-smoke',
            '--user', '10000:10000', '--cap-drop', 'ALL', '--security-opt',
            'no-new-privileges', '--mount', f'type=bind,source={self.base},target=/base,readonly',
            '--mount', f'type=bind,source={self.work},target=/workspace,readonly',
            '--mount', f'type=bind,source={self.red},target=/snapshot',
            '--entrypoint', 'python', image, '/test_first_copy.py'],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(copied.returncode, 0, copied.stderr)
        prepared = json.loads(copied.stdout)
        result = subprocess.run([
            'docker', 'run', '--rm', '--network', 'none', '--read-only',
            '--label','com.docker.compose.project=delivery-kit-port2',
            '--label','com.docker.compose.service=incremental-red-suite-smoke',
            '--user', '10000:10000', '--cap-drop', 'ALL', '--security-opt',
            'no-new-privileges', '--tmpfs', '/tmp:rw,nosuid,nodev,size=32m',
            '--env', 'PYTHONDONTWRITEBYTECODE=1',
            '--mount', f'type=bind,source={self.red},target=/delivery,readonly',
            '--workdir', '/delivery', '--entrypoint', 'python3',
            image, '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
            capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        red = assess_red(result.returncode, result.stdout + '\n' + result.stderr, prepared)
        self.assertEqual(red['exit_code'], result.returncode)
        self.assertEqual(red['evidence_version'],2)
        self.assertEqual(red['test_count'],2)
        (self.green / 'tests').mkdir()
        for name, data in self.old.items():
            target = self.green / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (self.green / 'app.py').write_text('VALUE = 1\n')
        (self.green / 'tests/test_new.py').write_bytes(self.new)
        self.assertTrue(verify_green_tests(self.green, red))
        green = subprocess.run([
            'docker', 'run', '--rm', '--network', 'none', '--read-only',
            '--label','com.docker.compose.project=delivery-kit-port2',
            '--label','com.docker.compose.service=incremental-green-suite-smoke',
            '--user', '10000:10000', '--cap-drop', 'ALL', '--security-opt',
            'no-new-privileges', '--tmpfs', '/tmp:rw,nosuid,nodev,size=32m',
            '--env', 'PYTHONDONTWRITEBYTECODE=1',
            '--mount', f'type=bind,source={self.green},target=/delivery,readonly',
            '--workdir', '/delivery', '--entrypoint', 'python3', image,
            '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(green.returncode, 0, green.stderr)
        self.assertIn('OK', green.stderr)
        verified = subprocess.run([
            'docker', 'run', '--rm', '--network', 'none', '--read-only',
            '--user', '10000:10000', '--cap-drop', 'ALL', '--security-opt',
            'no-new-privileges',
            '--env', 'TEST_FIRST_TEST_HASHES=' + json.dumps(red['test_sha256']),
            '--env', 'TEST_FIRST_RED_MANIFEST_SHA256=' + red['manifest_sha256'],
            '--mount', f'type=bind,source={self.red},target=/red,readonly',
            '--mount', f'type=bind,source={self.green},target=/delivery,readonly',
            '--entrypoint', 'python', image, '/test_first_verify.py'],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(json.loads(verified.stdout)['tests_unchanged'], True)
