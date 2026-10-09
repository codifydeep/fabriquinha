import hashlib
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
import uuid
from unittest.mock import patch

from broker import seed_workspace as seed
from test_portable_contract import contract


class RevisionSeedTests(unittest.TestCase):
    def candidate_selection(self, products):
        files={self.name:self.data, **products}
        for name,data in products.items():
            path=self.previous/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(data)
        encoded=json.dumps({'files':{name:{'sha256':hashlib.sha256(data).hexdigest(),
            'bytes':len(data)} for name,data in files.items()}}).encode()
        (self.previous/'manifest.json').write_bytes(encoded)
        return {**self.selection,'manifest_sha256':hashlib.sha256(encoded).hexdigest(),
            'product_sha256':{name:hashlib.sha256(data).hexdigest() for name,data in products.items()},
            'bounded_execution':{'operation':'reviewed_failed_candidate_seed_v1',
                'source_task':'source-1','plan_sha256':'a'*64}}

    def test_reviewed_candidate_seeds_product_and_preserves_baseline_and_frozen_tests(self):
        product=b'# partial product\n'+b'x'*40000
        selection=self.candidate_selection({'app.py':product})
        with patch.dict(os.environ,{'REVISION_SEED_JSON':json.dumps(selection)}):
            seed.main()
            self.assertEqual((self.work/'app.py').read_bytes(),product)
            self.assertEqual((self.work/self.name).read_bytes(),self.data)
            self.assertEqual((self.work/'tests/test_old.py').read_bytes(),
                             b'def test_old(): assert True')
            (self.work/'app.py').write_bytes(b'new author progress')
            seed.main()
            self.assertEqual((self.work/'app.py').read_bytes(),b'new author progress')
        self.assertEqual((self.previous/'app.py').read_bytes(),product)

    def test_product_seed_cannot_replace_tests_policy_or_undeclared_files(self):
        for name in ('tests/test_old.py',self.name,'AGENTS.md','unknown.py'):
            selection=self.candidate_selection({name:b'forbidden'})
            with patch.dict(os.environ,{'REVISION_SEED_JSON':json.dumps(selection)}):
                with self.assertRaises(ValueError):seed.main()
            self.assertEqual(list(self.work.iterdir()),[])

    def test_candidate_product_hash_drift_and_missing_execution_binding_rejected(self):
        selection=self.candidate_selection({'app.py':b'partial'})
        for invalid in ({**selection,'product_sha256':{'app.py':'b'*64}},
                        {k:v for k,v in selection.items() if k!='bounded_execution'},
                        {**selection,'bounded_execution':{}}):
            with patch.dict(os.environ,{'REVISION_SEED_JSON':json.dumps(invalid)}):
                with self.assertRaises(ValueError):seed.main()
            self.assertEqual(list(self.work.iterdir()),[])

    def test_candidate_product_symlink_and_oversize_rejected_before_copy(self):
        selection=self.candidate_selection({'app.py':b'partial'})
        (self.previous/'app.py').unlink()
        (self.previous/'app.py').symlink_to(self.base/'app.py')
        with patch.dict(os.environ,{'REVISION_SEED_JSON':json.dumps(selection)}):
            with self.assertRaisesRegex(ValueError,'unsafe revision'):seed.main()
        self.assertEqual(list(self.work.iterdir()),[])
        (self.previous/'app.py').unlink()
        selection=self.candidate_selection({'app.py':b'x'*(seed.MAX_FILE_BYTES+1)})
        with patch.dict(os.environ,{'REVISION_SEED_JSON':json.dumps(selection)}):
            with self.assertRaisesRegex(ValueError,'unsafe revision'):seed.main()
        self.assertEqual(list(self.work.iterdir()),[])

    def test_oversized_historical_input_requires_explicit_hash_bound_repair_admission(self):
        data=self.data+b'#'+b'x'*38000
        (self.previous/self.name).write_bytes(data)
        manifest=json.dumps({'files':{self.name:{'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}}}).encode()
        (self.previous/'manifest.json').write_bytes(manifest)
        selection={'manifest_sha256':hashlib.sha256(manifest).hexdigest(),
                   'test_sha256':{self.name:hashlib.sha256(data).hexdigest()}}
        with patch.dict(os.environ,{'REVISION_SEED_JSON':json.dumps(selection)}):
            with self.assertRaisesRegex(ValueError,'unsafe revision'):seed.main()
        selection['repair_input_bytes']={self.name:len(data)}
        with patch.dict(os.environ,{'REVISION_SEED_JSON':json.dumps(selection)}):
            seed.main()
        self.assertEqual((self.work/self.name).read_bytes(),data)
        self.assertEqual((self.previous/self.name).read_bytes(),data)
        self.assertEqual((self.work/'app.py').read_bytes(),b'original product')

    def test_repair_admission_cannot_expand_arbitrary_files_or_exceed64k(self):
        for limits in ({'app.py':40000},{self.name:65537},{self.name:32768}):
            with patch.dict(os.environ,{'REVISION_SEED_JSON':json.dumps({**self.selection,'repair_input_bytes':limits})}):
                with self.assertRaisesRegex(ValueError,'bounded historical'):seed.main()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.base, self.work, self.previous = (root / x for x in ('base', 'work', 'previous'))
        for directory in (self.base, self.work, self.previous):
            directory.mkdir()
        spec = contract()
        contents = {'AGENTS.md': b'policy', 'app.py': b'original product',
                    'tests/test_old.py': b'def test_old(): assert True',
                    'contract.json': json.dumps(spec).encode()}
        for name, data in contents.items():
            target = self.base / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        manifest = json.dumps({'base_sha': 'a' * 40, 'files': {
            name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}}).encode()
        (self.base / 'manifest.json').write_bytes(manifest)
        self.name = 'tests/test_new.py'
        self.data = b'def test_new(): assert False\n'
        (self.previous / 'tests').mkdir()
        (self.previous / self.name).write_bytes(self.data)
        prior_manifest = json.dumps({'files': {self.name: {
            'sha256': hashlib.sha256(self.data).hexdigest(), 'bytes': len(self.data)}}}).encode()
        (self.previous / 'manifest.json').write_bytes(prior_manifest)
        self.selection = {'manifest_sha256': hashlib.sha256(prior_manifest).hexdigest(),
                          'test_sha256': {self.name: hashlib.sha256(self.data).hexdigest()}}
        self.env = {'BASE_MANIFEST_SHA256': hashlib.sha256(manifest).hexdigest(),
                    'REVISION_SEED_JSON': json.dumps(self.selection)}
        self.patchers = [patch.object(seed, 'BASE', self.base), patch.object(seed, 'WORK', self.work),
                        patch.object(seed, 'PREVIOUS', self.previous), patch.dict(os.environ, self.env)]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_seed_only_new_test_and_never_reset_author_on_restart(self):
        (self.previous / 'app.py').write_bytes(b'forbidden product implementation')
        seed.main()
        self.assertEqual((self.work / self.name).read_bytes(), self.data)
        self.assertEqual((self.work / 'app.py').read_bytes(), b'original product')
        self.assertEqual((self.work / 'tests/test_old.py').read_bytes(),
                         b'def test_old(): assert True')
        (self.work / self.name).write_bytes(b'author correction')
        seed.main()
        self.assertEqual((self.work / self.name).read_bytes(), b'author correction')

    def test_interrupted_seed_resumes_before_marker(self):
        (self.work / 'tests').mkdir()
        (self.work / self.name).write_bytes(b'partial seed')
        seed.main()
        self.assertEqual((self.work / self.name).read_bytes(), self.data)

    def test_tampered_source_rejected_before_any_copy(self):
        (self.previous / self.name).write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'revision seed'):
            seed.main()
        self.assertEqual(list(self.work.iterdir()), [])

    def test_manifest_drift_and_baseline_replacement_rejected(self):
        with patch.dict(os.environ, {'REVISION_SEED_JSON': json.dumps({
                **self.selection, 'manifest_sha256': 'b' * 64})}):
            with self.assertRaisesRegex(ValueError, 'revision seed'):
                seed.main()
        with patch.dict(os.environ, {'REVISION_SEED_JSON': json.dumps({
                **self.selection, 'test_sha256': {'tests/test_old.py': 'a' * 64}})}):
            with self.assertRaisesRegex(ValueError, 'revision seed'):
                seed.main()

    def test_parent_directory_symlink_rejected(self):
        (self.work / 'tests').symlink_to(self.previous / 'tests', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            seed.main()

    @unittest.skipUnless(os.environ.get('RUN_REVISION_SEED_DOCKER_TEST') == '1',
                         'Docker oversized seed smoke runs explicitly')
    def test_real_offline_container_repairs_only_selected_oversized_historical_input(self):
        self.data=self.data+b'#'+b'x'*38000
        (self.previous/self.name).write_bytes(self.data)
        encoded=json.dumps({'files':{self.name:{'sha256':hashlib.sha256(self.data).hexdigest(),
                                               'bytes':len(self.data)}}}).encode()
        (self.previous/'manifest.json').write_bytes(encoded)
        selection={'manifest_sha256':hashlib.sha256(encoded).hexdigest(),
                   'test_sha256':{self.name:hashlib.sha256(self.data).hexdigest()},
                   'repair_input_bytes':{self.name:len(self.data)}}
        self.env['REVISION_SEED_JSON']=json.dumps(selection)
        self.test_real_offline_container_seeds_and_resumes_without_overwrite()

    @unittest.skipUnless(os.environ.get('RUN_REVISION_SEED_DOCKER_TEST') == '1',
                         'Docker seed smoke runs explicitly')
    def test_real_offline_container_seeds_and_resumes_without_overwrite(self):
        self.base.chmod(0o755)
        self.previous.chmod(0o755)
        self.work.chmod(0o777)
        image = os.environ['REVISION_SEED_TEST_IMAGE']
        def run(command):
            args = ['docker', 'run', '--rm', '--name',
                    'delivery-kit-port2-revision-seed-' + uuid.uuid4().hex[:12],
                    '--label', 'com.docker.compose.project=delivery-kit-port2-tests',
                    '--label', 'com.docker.compose.service=revision-seed-smoke',
                    '--network', 'none', '--read-only', '--user', '10000:10000',
                    '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                    '--memory', '96m', '--pids-limit', '16',
                    '--mount', f'type=bind,source={self.base},target=/base,readonly',
                    '--mount', f'type=bind,source={self.previous},target=/previous,readonly',
                    '--mount', f'type=bind,source={self.work},target=/workspace']
            for key, value in self.env.items():
                args += ['--env', key + '=' + value]
            args += ['--entrypoint', 'python', image, *command]
            result = subprocess.run(args, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        run(['/seed_workspace.py'])
        self.assertEqual((self.work / self.name).read_bytes(), self.data)
        run(['-c', 'from pathlib import Path; '
             'p=Path("/workspace/tests/test_new.py"); p.write_text("author correction"); '
             'assert Path("/workspace/app.py").read_text()=="original product"\n'
             'try:\n Path("/previous/tests/test_new.py").write_text("bad")\n'
             'except OSError: pass\nelse: raise AssertionError("source writable")'])
        run(['/seed_workspace.py'])
        self.assertEqual((self.work / self.name).read_bytes(), b'author correction')
        self.assertEqual((self.previous / self.name).read_bytes(), self.data)
