"""Exact controller-to-handler phase binding; no model or native qualification."""
import asyncio
import copy
import json
import os
import unittest
from unittest.mock import Mock,patch
import quality_phase_tools as phase
from broker import acp_transport as acp,review_tool_policy as handlers


class QualityPhaseToolsTests(unittest.TestCase):
    def setUp(self):
        self.request='60000000-0000-4000-8000-000000000001'
        self.config=dict(version=2,phase='tests_only_v2',request_id=self.request,
            editable_paths=['/workspace/tests/test_new.py'],
            read_paths=['/workspace/tests/test_new.py','/workspace/app.py','/workspace/tests/test_old.py'])
        self.env={phase.KEY:json.dumps(self.config),'DELIVERY_EXECUTION_MODE':'implementation',
            'DELIVERY_MODEL_EXECUTION_ID':self.request}

    def control(self,name,args,env=None):return phase.controlled(name,args,self.env if env is None else env)

    def test_only_exact_registered_reads_and_bounded_new_test_writes_delegate(self):
        for p in self.config['read_paths']:self.assertIsNone(self.control('read_file',dict(path=p,offset=1,limit=200)))
        self.assertIsNone(self.control('write_file',dict(path=self.config['editable_paths'][0],content='test bytes\n')))
        for name,args in [('write_file',dict(path='/workspace/app.py',content='bad')),
                ('write_file',dict(path='/workspace/tests/test_old.py',content='bad')),
                ('write_file',dict(path='/workspace/tests/test_new.py',content='x'*32769)),
                ('read_file',dict(path='/tmp/config')),('read_file',dict(path='/workspace/../tmp/key')),
                ('read_file',dict(path='/workspace/app.py',limit=-1))]:
            self.assertIn('error',json.loads(self.control(name,args)))

    def test_arbitrary_code_and_administrative_tools_never_delegate(self):
        for name in ('terminal','python','delegate_task','patch','patch_file','execute_code','github','kanban','memory'):
            with self.subTest(name=name):self.assertIn('error',json.loads(self.control(name,dict(command='arbitrary'))))

    def test_bad_or_conflicting_phase_never_falls_back_to_implementation_permissions(self):
        variants=[{**self.env,phase.KEY:''},{**self.env,phase.KEY:'{}'},
            {**self.env,'DELIVERY_MODEL_EXECUTION_ID':self.request[:-1]+'2'},
            {**self.env,'DELIVERY_EXECUTION_MODE':'review'}]
        variants.extend({**self.env,k:''} for k in phase.CONFLICTS)
        for env in variants:
            with self.subTest(env_keys=list(env)):
                self.assertIn('error',json.loads(self.control('write_file',dict(path=self.config['editable_paths'][0],content='test'),env)))

    def test_sync_and_async_direct_handlers_are_fenced_before_the_original_handler(self):
        original=Mock(return_value='should not execute')
        with patch.dict(os.environ,self.env,clear=True):
            result=handlers.fence('terminal',original)(dict(command='sh'))
            self.assertIn('error',json.loads(result));original.assert_not_called()
            async def forbidden(args,**kwargs):raise AssertionError('async handler bypassed phase')
            result=asyncio.run(handlers.fence('python',forbidden,True)({}))
            self.assertIn('error',json.loads(result))
            allowed=Mock(return_value='written')
            result=handlers.fence('write_file',allowed)(dict(path=self.config['editable_paths'][0],content='test'))
            self.assertEqual(result,'written');allowed.assert_called_once()

    def test_transport_binds_execution_and_disallows_sessions_or_mixed_capabilities(self):
        values=acp.worker_env('implementation',False,execution_id=self.request,quality_phase_config=self.config)
        self.assertIn(phase.KEY+'='+json.dumps(self.config,sort_keys=True),values)
        for changes in (dict(mode='review'),dict(persistent=True),dict(test_commands=['python -m unittest']),
                dict(execution_id=self.request[:-1]+'2'),dict(review_suite_capability='a'*64)):
            kwargs=dict(mode='implementation',persistent=False,execution_id=self.request,quality_phase_config=self.config)
            kwargs.update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):acp.worker_env(**kwargs)

    def test_transport_editables_drift_is_rejected_before_any_docker_exec(self):
        docker=Mock(side_effect=AssertionError('must reject before Docker'))
        with self.assertRaises(ValueError):acp.Transport(docker,'delivery-kit-test-job-'+self.request,
            mode='implementation',editable_paths=['/workspace/app.py'],quality_phase_config=self.config)
        docker.assert_not_called()

    def test_noncanonical_and_unscoped_config_paths_are_rejected(self):
        for path in ('/workspace/../tmp/key','/workspace//app.py','relative','/tmp/key'):
            c=copy.deepcopy(self.config);c['read_paths'].append(path)
            with self.subTest(path=path),self.assertRaises(ValueError):phase.validate(c,self.request)


if __name__=='__main__':unittest.main()
