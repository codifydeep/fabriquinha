import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from e2e_controller import E2E,ATTEMPT,BASE,HEAD
from e2e_policy import BASELINE,NOTES,validate
from review_controller import Controller

TESTS='import unittest\nfrom app import winner\nclass Cases(unittest.TestCase):\n'+''.join(f'    def test_{i}(self): self.assertEqual(winner({a},{b}), {value!r})\n' for i,(a,b,value) in enumerate([(12,0,'A'),(0,12,'B'),(12,13,'A'),(0,0,None),(11,11,None)]))
GOOD='def winner(a, b):\n    return "A" if a >= 12 else "B" if b >= 12 else None\n'


class E2ETests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.board=self.root/ATTEMPT; self.board.mkdir()
        self.private=self.root/'private'; self.private.mkdir()
        (self.private/'e2e-config.json').write_text(json.dumps(dict(attempt=ATTEMPT,cards=dict(build='t_build',deploy='t_deploy',qa='t_qa'))))
        (self.board/'e2e.json').write_text((self.private/'e2e-config.json').read_text())
        self.c=Controller(self.board,self.private,ATTEMPT,'unused','unused'); self.addCleanup(self.c.db.close)
        self.e=self.c.e2e
        self.work=self.board/'workspaces/t_build'; self.work.mkdir(parents=True)
        self.task=dict(id='t_build',assignee='backend_data',workspace_path=str(self.work),title='BUILD')
        (self.work/'app.py').write_text(BASELINE); (self.work/'test_user.py').write_text(TESTS)
    def test_private_identity_drift_rejected_before_generic_delivery_lookup(self):
        path=self.private/'e2e-config.json'
        data=json.loads(path.read_text()); data['attempt']='old-attempt'; path.write_text(json.dumps(data))
        with self.assertRaisesRegex(RuntimeError,'e2e_identity_mismatch'):
            self.c.handle(dict(operation='e2e_status'))
    def test_missing_private_config_fails_startup(self):
        (self.private/'e2e-config.json').unlink()
        with self.assertRaisesRegex(RuntimeError,'e2e_identity_mismatch'):
            E2E(self.c)
    def test_readiness_checks_both_configs_without_delivery(self):
        self.assertTrue(self.c.handle(dict(operation='e2e_readiness'))['ready'])
    def test_policy_rejects_shell_imports_skips_and_paths(self):
        validate('app.py',GOOD); validate('test_user.py',TESTS); validate('NOTES.md',NOTES)
        for name,value in [('app.py','import os\ndef winner(a,b): return os.system("id")'),('../token','secret'),('NOTES.md','Truco is deployed'),('test_user.py',TESTS.replace('def test_0','@unittest.skip("x")\n    def test_0'))]:
            with self.assertRaises((ValueError,SyntaxError)): validate(name,value)
    def test_notes_allow_only_boundary_whitespace(self):
        validate('NOTES.md',NOTES.rstrip())
        with self.assertRaises(ValueError): validate('NOTES.md',NOTES.replace('separate','no'))
    def publish_fixture(self):
        revision=self.e.capture(self.task,1,self.e.files(self.task))
        self.e.put('green',dict(passed=True))
        self.e.put('published',dict(revision=revision,author_run=1,notes=False,head='sha'))
        return revision
    def test_notes_require_current_formal_changes(self):
        rev=self.publish_fixture()
        request=dict(operation='e2e_edit_check',run=1,path='NOTES.md',content=NOTES)
        with self.assertRaises(PermissionError): self.e.handle(self.task,False,request)
        self.e.put('changes',dict(revision=rev))
        self.assertTrue(self.e.handle(self.task,False,request)['allowed'])
    def test_restore_preserves_divergence_and_allows_handoff_on_new_run(self):
        self.publish_fixture(); (self.work/'NOTES.md').write_text(NOTES)
        result=self.e.handle(self.task,False,dict(operation='e2e_restore_published',run=2))
        self.assertEqual(self.e.get(result['backup_id'])['files']['NOTES.md'],NOTES)
        self.assertEqual(self.e.published_diff(self.task)[0]['file'],'NOTES.md')
        for n in result['remove']: (self.work/n).unlink()
        for n,v in result['files'].items(): (self.work/n).write_text(v)
        self.assertTrue(self.e.handle(self.task,False,dict(operation='e2e_restore_confirm',run=2))['passed'])
        self.assertEqual(self.e.handle(self.task,False,dict(operation='freeze',run=2,reviewer='techlead'))['head'],'sha')
    def test_reviewer_cannot_restore(self):
        self.publish_fixture()
        with self.assertRaises(PermissionError): self.e.handle(dict(self.task,assignee='techlead'),True,dict(operation='e2e_restore_published',run=2))
    def test_restore_cannot_discard_requested_rework(self):
        rev=self.publish_fixture(); self.e.put('changes',dict(revision=rev))
        with self.assertRaises(PermissionError): self.e.handle(self.task,False,dict(operation='e2e_restore_published',run=2))
    def test_rework_without_notes_has_no_external_effect(self):
        self.e.put('green',dict(fingerprint=self.e.fingerprint(self.e.files(self.task)),passed=True))
        self.e.put('changes',dict(run=2))
        with patch.object(self.e,'api') as api:
            self.assertTrue(self.e.publish(self.task,3)['block_required'])
            api.assert_not_called()
    def test_duplicate_content_rejected_before_publish(self):
        from e2e_policy import digest
        files=self.e.files(self.task)
        self.e.put('green',dict(fingerprint=self.e.fingerprint(files),passed=True))
        self.e.put('published',dict(content_hash=digest(json.dumps(files,sort_keys=True).encode()),author_run=1))
        with patch.object(self.e,'api') as api:
            self.assertTrue(self.e.publish(self.task,3)['block_required']); api.assert_not_called()
    def test_tdd_requires_real_red_and_preserves_tests(self):
        with patch.object(self.e,'tests',return_value=dict(returncode=1,tests=12,passed=False,output='FAILED (failures=4)')):
            red=self.e.handle(self.task,False,dict(operation='e2e_test',run=1,stage='red'))
        self.assertTrue(red['accepted'])
        (self.work/'app.py').write_text(GOOD)
        with patch.object(self.e,'tests',return_value=dict(returncode=0,tests=12,passed=True,output='OK')):
            self.assertTrue(self.e.handle(self.task,False,dict(operation='e2e_test',run=1,stage='green'))['passed'])
        with self.assertRaises(PermissionError): self.e.handle(self.task,False,dict(operation='e2e_edit_check',run=1,path='test_user.py',content=TESTS))
    def test_red_accepts_formatting_without_mutating_bytes(self):
        for code in [BASELINE.rstrip(), 'def winner(a,b): return None\n', BASELINE.replace('\n','\r\n')]:
            (self.work/'app.py').write_bytes(code.encode())
            self.e.c.db.execute("DELETE FROM e2e_state WHERE key=?",(ATTEMPT+':red',)); self.e.c.db.commit()
            with patch.object(self.e,'tests',return_value=dict(returncode=1,tests=12,passed=False,output='FAILED (failures=4)')):
                self.assertTrue(self.e.handle(self.task,False,dict(operation='e2e_test',run=1,stage='red'))['accepted'])
            self.assertEqual((self.work/'app.py').read_bytes(),code.encode())
    def test_repeated_semantic_mismatch_has_durable_diagnosis(self):
        (self.work/'app.py').write_text(GOOD)
        with patch.object(self.e,'tests') as tests:
            first=self.e.handle(self.task,False,dict(operation='e2e_test',run=1,stage='red'))
            second=self.e.handle(self.task,False,dict(operation='e2e_test',run=1,stage='red'))
            self.assertFalse(first['block_required']); self.assertTrue(second['block_required'])
            self.assertEqual(second['actual'],GOOD); self.assertIsNone(self.e.get('red'))
            tests.assert_not_called()
    def test_wrong_actor_and_unregistered_operations_denied(self):
        with self.assertRaises(PermissionError): self.e.handle(dict(self.task,assignee='techlead'),False,dict(operation='e2e_deploy',run=1))
        with self.assertRaises(PermissionError): self.e.handle(self.task,False,dict(operation='terminal',run=1,command='id'))
        with self.assertRaises(PermissionError): self.e.gh('repos/other/repo/git/refs')
    def ready_merge(self):
        published=dict(revision='r1',head='a'*40,base='b'*40,pr=12,notes=True,author='backend_data',reviewer='techlead')
        self.e.put('published',published); self.e.put('review:2',dict(revision='r1',passed=True)); self.e.put('changes',dict(run=1))
        return published
    def test_merge_without_ci_does_not_write(self):
        published=self.ready_merge()
        with patch.object(self.e,'pull',return_value=dict(base={'sha':published['base']},merged=False)),patch.object(self.e,'api',return_value={'check_runs':[]}) as api:
            self.assertTrue(self.e.merge(dict(self.task,assignee='techlead'),2)['pending'])
            self.assertEqual(api.call_count,1)
        self.assertIsNone(self.e.get('approval'))
    def test_stale_review_blocks_merge(self):
        self.ready_merge(); self.e.put('review:2',dict(revision='old',passed=True))
        with self.assertRaises(ValueError): self.e.merge(dict(self.task,assignee='techlead'),2)
    def test_failed_ci_is_terminal_block_not_pending(self):
        published=self.ready_merge()
        check=dict(id=99,name='e2e-contract',head_sha=published['head'],app={'slug':'github-actions'},status='completed',conclusion='failure')
        with patch.object(self.e,'pull',return_value=dict(base={'sha':published['base']},merged=False)),patch.object(self.e,'api',side_effect=[{'check_runs':[check]},[{'message':'exit 127'}]]) as api:
            result=self.e.merge(dict(self.task,assignee='techlead'),2)
            self.assertFalse(result['pending']); self.assertTrue(result['block_required']); self.assertEqual(result['category'],'ci_failed')
            self.assertEqual(api.call_count,2)
        self.assertIsNone(self.e.get('approval'))
    def test_crash_after_remote_merge_reuses_durable_intent(self):
        published=self.ready_merge(); approval=dict(head=published['head'],review_run=2,author='backend_data',reviewer='techlead')
        self.e.put('approval',approval)
        with patch.object(self.e,'pull',return_value=dict(merged=True,merge_commit_sha='c'*40)),patch.object(self.e,'api',return_value=dict(parents=[{'sha':published['base']},{'sha':published['head']}])) as api:
            result=self.e.merge(dict(self.task,assignee='techlead'),2)
            self.assertTrue(result['merged']); self.assertEqual(api.call_count,1)
    def test_deploy_without_merge_rejected(self):
        self.e.put('published',dict(merged=False))
        with self.assertRaises(ValueError): self.e.deploy()

    def test_deploy_resumes_recorded_phases(self):
        self.e.put('published',dict(merged=True,approval=True,merge_sha='sha'))
        for phase in ('baseline','first','rollback'):
            self.e.put('deploy-phase:sha:'+phase,dict(passed=True,phase=phase))
        import subprocess
        current=dict(Image='image',State=dict(Health=dict(Status='healthy')),Config=dict(Labels={'hermes.commit':'sha'}))
        with patch.object(self.e,'pull'),patch.object(self.e,'runtime_image',return_value=dict(id='image',commit='sha')),patch.object(self.e,'up') as up,patch.object(self.e,'http',return_value=dict(passed=True)) as http,patch('review_controller.bounded_run',return_value=subprocess.CompletedProcess([],0,json.dumps([current]))):
            self.assertTrue(self.e.deploy()['passed']); up.assert_not_called(); http.assert_called_once_with(False)
    def test_qa_cannot_self_approve(self):
        task=dict(id='t_qa',assignee='quality_security')
        with self.assertRaises(PermissionError): self.e.handle(task,False,dict(operation='approve',run=7))
    def test_deploy_review_has_one_explicit_target(self):
        self.e.put('published',dict(revision='old-snapshot',merge_sha='a'*40))
        self.e.put('green',dict(revision='historical-green'))
        task=dict(id='t_deploy',assignee='quality_security')
        result=self.e.handle(task,True,dict(operation='inspect',run=8))
        self.assertEqual(result['delivery']['revision'],'a'*40)
        self.assertNotIn('green',result); self.assertNotIn('published',result)
        self.assertEqual(result['next_operation'],{'tool':'e2e_review_validate','arguments':{}})
        with self.assertRaisesRegex(ValueError,'expected_revision'):
            self.e.handle(task,True,dict(operation='validate',run=8,revision='old-snapshot'))
