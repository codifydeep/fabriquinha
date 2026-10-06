import unittest,tempfile
from unittest.mock import patch
from pathlib import Path
from product_deployment import validate,compose

class DeploymentTests(unittest.TestCase):
    def test_existing_immutable_snapshot_is_verified_not_rewritten(self):
        from product_deployment import immutable_file
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source';immutable_file(path,'preserved')
            with patch.object(Path,'write_text',side_effect=AssertionError('must not rewrite')):
                immutable_file(path,'preserved')
                with self.assertRaises(PermissionError):immutable_file(path,'changed')
    def setUp(self):
        self.packet=dict(head='a'*40,integration=dict(state='INTEGRATED',merge='a'*40),ci=dict(conclusion='success'),files={'server/index.ts':'app'})
        self.spec=dict(entry='dist/server/index.js',health_path='/health',checks=[dict(path='/health',status=200,contains='ok')],reason='Deploy the integrated exact commit using fixed local resources; QA must check the actual HTTP result and restoration. '*2)
    def test_exact_integrated_source_required(self):
        validate(self.spec,self.packet)
        for delta in (dict(ci=dict(conclusion='failure')),dict(head='b'*40),dict(integration=dict(state='CI_WAIT',merge='a'*40))):
            with self.subTest(delta=delta),self.assertRaises(PermissionError):validate(self.spec,dict(self.packet,**delta))
    def test_no_arbitrary_commands_urls_or_traversal(self):
        for delta in (dict(entry='../../bin/bash'),dict(entry='dist/index.js;curl'),dict(health_path='https://example.com'),dict(health_path='//example.com'),dict(checks=[dict(path='//evil',status=200,contains='')])):
            with self.subTest(delta=delta),self.assertRaises((PermissionError,ValueError)):validate(dict(self.spec,**delta),self.packet)
    def test_compose_local_isolated_and_no_privileged_mounts(self):
        value=compose(Path('/allowed'), 'sha256:'+'b'*64,'c'*16,'a'*40,self.spec['entry'],'/health')
        service=next(iter(value['services'].values()))
        self.assertNotIn('ports',service)
        proxy=value['services']['homologation-'+'c'*16+'-ingress']
        self.assertEqual(proxy['ports'],['127.0.0.1::8080'])
        self.assertEqual(set(proxy['environment']),{'APP_SERVICE'})
        self.assertEqual({v['target'] for v in proxy['volumes']},{'/ingress'})
        self.assertTrue(service['read_only']);self.assertEqual(service['cap_drop'],['ALL'])
        self.assertTrue(all(value['networks'][n]['internal'] for n in service['networks']))
        self.assertEqual(len(proxy['networks']),2)
        self.assertTrue(all(v['read_only'] for v in service['volumes']))
        self.assertEqual({v['target'] for v in service['volumes']},{'/workspace','/operation'})
        self.assertEqual(set(service['environment']),{'APP_ENTRY','APP_COMMIT'})
