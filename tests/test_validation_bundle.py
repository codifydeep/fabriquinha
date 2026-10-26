"""A prepared execution keeps its validator even when the checkout changes."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.config import Project
from fabriquinha.effects import write_json
from fabriquinha.executor import Runner,ROOT,preview_drivers
from fabriquinha.quality import CONTROL_CONTRACT,preview_evidence
from fabriquinha.publication import LocalStatus
from test_delivery_core import configuration


class PinnedValidation(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.store=Store(self.root/'private')
        self.project=Project.parse({**configuration(),'browser_tdd':True,'browser_image':'sha256:'+'b'*64,
            'coordination_roles':{'product':'backend','lead':'lead'},'delivery_roles':{'tests':'backend','integration':'lead'}})
        source=self.root/'scripts';source.mkdir()
        for name in ('suite.py','browser.py'):shutil.copyfile(ROOT/'src/fabriquinha'/name,source/name)
        self.bundle=self.store.capture(source)
        write_json(self.root/'installation.json',dict(project=self.project.fingerprint(),upstream='fixture',
            validation_bundle=self.bundle,control_contract=CONTROL_CONTRACT))
        work=self.root/'work';(work/'tests').mkdir(parents=True)
        (work/'tests/qa.json').write_text(json.dumps(dict(version=1,checks=[dict(id='NAME',path='/',
            actions=[dict(action='click',selector='#show')],selector='#result',text='Ada')])))
        self.snapshot=self.store.capture(work)
        drivers={key:self.store.manifest(self.bundle)[name]['sha256'] for key,name in (('driver','browser.py'),('reporter','suite.py'))}
        self.value=dict(identity=dict(validation_bundle=self.bundle,qa_preview=drivers),
            report=dict(qa_preview=dict(status='passed',checks=['NAME'])))

    def test_checkout_edit_does_not_invalidate_the_pinned_preview(self):
        changed=self.root/'changed';folder=changed/'src/fabriquinha';folder.mkdir(parents=True)
        for name in ('suite.py','browser.py'):(folder/name).write_text('# edited after execution started\n')
        with patch('fabriquinha.executor.ROOT',changed):
            preview_evidence(self.project,self.store,self.value,self.snapshot,'green')

    def test_missing_or_foreign_bundle_cannot_upgrade_old_evidence(self):
        for bundle in (None,'e'*64):
            value={**self.value,'identity':{**self.value['identity'],'validation_bundle':bundle}}
            with self.subTest(bundle=bundle),self.assertRaisesRegex(ValueError,'bundle'):
                preview_evidence(self.project,self.store,value,self.snapshot,'green')

    def test_all_phases_mount_the_pinned_reporter_not_mutable_checkout_scripts(self):
        runner=Runner.__new__(Runner);runner.store=self.store;runner.project=self.project
        run=SimpleNamespace(binding=lambda:dict(task='fixture',number=1))
        for phase in ('baseline','red','control','green','delivery','integrated','diagnostic'):
            with patch.object(runner,'_execute',return_value='job') as execute:runner.run(run,self.snapshot,phase)
            _,identity,command=execute.call_args.args
            self.assertEqual(identity['validation_bundle'],self.bundle)
            mounts=[command[i+1] for i,arg in enumerate(command) if arg=='--mount']
            self.assertEqual(len(mounts),3)
            self.assertTrue(any(str(self.store.tree(self.bundle)/'suite.py') in m for m in mounts))
            self.assertFalse(any(str(ROOT/'src/fabriquinha') in m for m in mounts))

    def test_modified_bundle_content_is_rejected_even_with_the_same_pointer(self):
        path=self.store.tree(self.bundle)/'browser.py';path.chmod(0o644);path.write_text('# tampered\n')
        with self.assertRaises(ValueError):preview_evidence(self.project,self.store,self.value,self.snapshot,'green')

    def test_deployed_browser_mounts_the_same_pinned_driver(self):
        runner=Runner.__new__(Runner);runner.store=self.store;runner.project=self.project
        run=SimpleNamespace(binding=lambda:dict(task='fixture',number=1))
        def docker(*args):
            if args[:2]==('image','inspect'):return json.dumps([dict(Id=self.project.browser_image,Config=dict(User='10000:10000',Entrypoint=['python']))])
            if args[:2]==('network','inspect'):return json.dumps([dict(Internal=True,Labels={'com.docker.compose.project':self.project.namespace+'-homologation'})])
            raise AssertionError(args)
        with patch('fabriquinha.executor.docker',docker),patch.object(runner,'_execute',return_value='job') as execute:
            runner.browser(run,self.snapshot,'c'*40)
        _,identity,command=execute.call_args.args
        self.assertEqual(identity['validation_bundle'],self.bundle)
        mounts=[command[i+1] for i,arg in enumerate(command) if arg=='--mount']
        self.assertTrue(any(str(self.store.tree(self.bundle)/'browser.py') in mount and 'dst=/qa.py,readonly' in mount for mount in mounts))

    def test_existing_ci_receipt_keeps_its_bundle_after_a_checkout_edit(self):
        project=replace(self.project,local_ci=dict(context='fabriquinha-local-ci',publisher='publisher'))
        write_json(self.root/'installation.json',dict(project=project.fingerprint(),validation_bundle=self.bundle,control_contract=CONTROL_CONTRACT))
        github=Mock();status=LocalStatus(project,self.store,Mock(),github,Mock())
        identity=status.identity('a'*40,'b'*40,'integrated');binding={**identity,'scope':'local_ci','version':1}
        report=dict(version=1,tests_run=1,cases=['case'],failures=[],errors=[],skips=[],expected_failures=[],unexpected_successes=[],
            qa_preview=dict(version=1,status='passed',source_sha=self.snapshot,checks=['NAME'],errors=[]))
        job=self.store.record('suite_job',binding,dict(identity={**self.value['identity'],'binding':binding,'project':project.fingerprint(),
            'snapshot':self.snapshot,'phase':'integrated'},exit_code=0,report=report))
        receipt=self.store.record('ci_validation',binding,{**identity,'snapshot':self.snapshot,'job':job,'conclusion':'success'})
        github.local_status.return_value=dict(id=1,description='Fabriquinha receipt '+receipt,context='fabriquinha-local-ci',
            state='success',creator={'login':'publisher'})
        with patch('fabriquinha.executor.ROOT',self.root/'missing-checkout'):
            self.assertEqual(status.observe(identity,receipt)['conclusion'],'success')


if __name__=='__main__':unittest.main()
