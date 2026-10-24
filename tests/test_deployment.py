import sys
import unittest
import tempfile
import subprocess
import json
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.config import Project
from fabriquinha.deployment import web_spec, Deployment
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from test_delivery_core import configuration


class ComposeBoundaries(unittest.TestCase):
    def setUp(self):
        self.project=Project.parse(configuration())
        self.artifact=dict(image='sha256:'+'b'*64,commit='a'*40,snapshot='c'*64,receipt='d'*64,
                           project=self.project.fingerprint())

    def test_homologation_is_grouped_unprivileged_local_and_content_addressed(self):
        spec=web_spec(self.project,self.artifact,'effect')
        web=spec['services']['web']
        self.assertEqual(web['image'],self.artifact['image'])
        self.assertEqual(web['pull_policy'],'never')
        self.assertTrue(web['read_only'])
        self.assertEqual(web['user'],'65534:65534')
        self.assertEqual(web['cap_drop'],['ALL'])
        self.assertEqual(web['ports'][0]['host_ip'],'127.0.0.1')
        self.assertEqual(spec['networks']['default']['driver'],'bridge')
        self.assertTrue(spec['networks']['qa']['internal'])
        self.assertEqual(web['networks'],['default','qa'])
        self.assertNotIn('published',web['ports'][0])
        self.assertNotIn('volumes',web)
        self.assertNotIn('build',web)
        self.assertEqual(web['labels']['delivery-kit.lifecycle'],'homologation')

    def test_tag_or_foreign_artifact_cannot_be_deployed(self):
        for update in ({'image':'python:latest'},{'project':'other'}):
            with self.subTest(update=update),self.assertRaises(ValueError):
                web_spec(self.project,{**self.artifact,**update},'effect')

    def test_author_cannot_sign_the_independent_qa(self):
        delivery=Deployment.__new__(Deployment)
        delivery.board=SimpleNamespace(ensure=lambda run:None)
        for reviewing,actor,author in ((False,'author','author'),(True,'author','author')):
            run=SimpleNamespace(kind='integration',reviewing=reviewing,actor=actor,author=author)
            with self.assertRaises(ValueError):delivery.current(run,review=True)

    def test_deployment_receipt_keeps_overlapping_effect_and_observation_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'private')
            delivery=Deployment(self.project,store,SimpleNamespace(ensure=lambda run:None),None)
            delivery.journal=SimpleNamespace(do=lambda *args,**kwargs:dict(
                artifact=self.artifact['receipt'],container='container',healthy=True,image=self.artifact['image']))
            run=Run('integration',3,'lead','integration',False,'lead','v1','contract')
            key=delivery._up(run,self.artifact,'restore')
            value=store.receipt(key,kind='deployment')['payload']
            self.assertEqual(value['operation'],'restore')
            self.assertEqual(value['artifact'],self.artifact['receipt'])

    def test_failed_cli_stderr_is_archived_before_raising(self):
        with tempfile.TemporaryDirectory() as folder:
            delivery=Deployment.__new__(Deployment)
            result=subprocess.CompletedProcess(['docker','build'],1,stdout='before failure',stderr='build failed')
            with patch('fabriquinha.deployment.subprocess.run',return_value=result):
                with self.assertRaises(subprocess.CalledProcessError):
                    delivery._command(Path(folder),'build-output','build','fixture',timeout=30)
            saved=json.loads((Path(folder)/'build-output.json').read_bytes())
            self.assertEqual(saved['stderr'],'build failed')
            self.assertEqual(saved['returncode'],1)


if __name__=='__main__':unittest.main()
