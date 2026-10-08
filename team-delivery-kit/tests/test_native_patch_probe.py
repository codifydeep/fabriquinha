import inspect
import unittest
from probe_native_patch import native_case,remote_probe,valid_result,native_program


class NativePatchProbeTests(unittest.TestCase):
    def result(self):
        return dict(uid=10000,writer_sha256='a'*64,invalid_patch_rejected=True,
            fixed_syntax_error=True,rejected_patch_preserved_bytes=True,valid_patch_success=True,
            exact_quotes_preserved=True,baseline_unchanged=True,credentials_absent=True)

    def test_every_installed_handler_invariant_is_required(self):
        result=self.result();self.assertTrue(valid_result(result,'a'*64))
        for key in result:
            changed=dict(result);changed[key]=False
            self.assertFalse(valid_result(changed,'a'*64),key)
        self.assertFalse(valid_result(result,'b'*64));self.assertFalse(valid_result({},'a'*64))

    def test_remote_native_programs_compile_and_use_real_backend_without_model(self):
        for function in (native_case,remote_probe,valid_result):
            compile(inspect.getsource(function),'fixed-native-probe','exec')
        source=inspect.getsource(native_case)
        self.assertIn('LocalEnvironment',source);self.assertIn('ShellFileOperations',source)
        self.assertEqual(source.count('ops.patch_replace('),2)
        self.assertNotIn('mock',source);self.assertNotIn('ACP',source)
        remote=inspect.getsource(remote_probe)
        for term in ("NetworkMode='none'","User='10000:10000'",'model_calls=0',
                     'synthetic-probe-evidence','?force=false'):
            self.assertIn(term,remote)
        self.assertNotIn('session/prompt',remote)

    def test_bootstrap_compiles_with_exception_boundary_and_native_import_path(self):
        program=native_program();compile(program,'installed-native-program','exec')
        self.assertIn('native_failure_category',program)
        self.assertIn('PYTHONPATH=/opt/hermes:/',inspect.getsource(remote_probe))
