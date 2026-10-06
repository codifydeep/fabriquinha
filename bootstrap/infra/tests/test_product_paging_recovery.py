import json,unittest
from unittest.mock import Mock
from product_reading import compact,page
from product_recovery import ready_dependencies
from product_rework import Rework

class PagingTests(unittest.TestCase):
    def test_large_lockfile_never_hides_source_or_edit_hash(self):
        files={'package-lock.json':'x'*149000,'server/ws.ts':'source','tests/ws.test.ts':'assert'}
        result=compact(files)
        self.assertLess(len(json.dumps(result)),10000)
        self.assertEqual(result['files']['server/ws.ts'],'source')
        self.assertFalse(result['file_manifest']['package-lock.json']['inline'])
        chunks=[];offset=0
        while offset is not None:
            p=page(files,'package-lock.json',offset);chunks.append(p['content']);offset=p['next_offset']
        self.assertEqual(''.join(chunks),files['package-lock.json'])
    def test_pages_bounded_and_invalid_offsets_rejected(self):
        for offset in (-1,True,1.2,5001):
            with self.assertRaises(ValueError):page({'file':'a'*5000},'file',offset)
        self.assertEqual(len(page({'file':'a'*5000},'file',0)['content']),2000)
        with self.assertRaises(PermissionError):page({'file':'a'},'../secret',0)

class PrerequisitesTests(unittest.TestCase):
    def test_empty_maps_cannot_defer_required_package(self):
        with self.assertRaises(ValueError):ready_dependencies({'package.json':'{}'},dict(dependencies={},devDependencies={}),{'dependencies':['ws']})
    def test_existing_or_proposed_dependencies_satisfy_requirement(self):
        ready_dependencies({'package.json':'{"dependencies":{"ws":"8.21.3"}}'},dict(dependencies={},devDependencies={'@types/ws':'8.5.13'}),{'dependencies':['ws'],'devDependencies':['@types/ws']})
    def test_failure_creates_evidence_bound_recovery_without_retrying_job(self):
        c=Rework();c.recovery=Mock();c.notice=Mock()
        pub={'pr':24,'head':'a'};spec=dict(dependencies={'ws':'8.18.0'},devDependencies={})
        c.preparation_failure(pub,{},dict(draft_task='original',recovery_depth=2),dict(task='ctocard',specification=spec),'job','npm audit high; remediation ws@8.21.3')
        args=c.recovery.call_args.args;cause=args[2]
        self.assertEqual(cause['kind'],'preparation_failure');self.assertEqual(cause['draft_task'],'original')
        self.assertEqual(cause['failed_job'],'job');self.assertEqual(cause['rejected_dependencies'],[spec])
        self.assertIn('8.21.3',cause['error']);c.notice.assert_not_called()
