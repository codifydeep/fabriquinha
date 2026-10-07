import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from remediation_admission_status import project,select_current


class AdmissionStatusTests(unittest.TestCase):
    def record(self,source,issue,phases):
        return dict(intent={'source_task':source},source_issue=issue,phase_issues=phases,state={})

    def test_current_admission_follows_explicit_dependency_not_order(self):
        old=self.record('old','origin',['r1-old','r2-old'])
        new=self.record('new','r2-old',['r1-new','r2-new'])
        for records in ([old,new],[new,old]):
            self.assertIs(select_current(records),new)
        self.assertIsNone(select_current([]))

    def test_parallel_disconnected_or_cyclic_lineages_fail_closed(self):
        old=self.record('old','origin',['r2-old'])
        new=self.record('new','r2-old',['r2-new'])
        for records in ([old,self.record('parallel','origin',['parallel'])],
                [old,new,self.record('unrelated','other',['unrelated'])],
                [self.record('a','b-issue',['a-issue']),self.record('b','a-issue',['b-issue'])],
                [old,old]):
            with self.assertRaises(ValueError):select_current(records)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.value=dict(root_issue='root',stage='awaiting_budget',remaining_calls=206,required_calls=256,
                        next_step='R1',owner='controller',release_homologated=False)
        self.command=Mock(return_value=json.dumps(self.value));self.metadata={};self.writes=[]
        def cli(*args):
            if args[:2]==('metadata','list'):return dict(self.metadata)
            if args[:2]==('metadata','set'):
                self.writes.append(args);self.metadata[args[4]]=args[6];return {}
            raise AssertionError(args)
        self.cli=cli
    def invoke(self):return project(self.root,'root',self.cli,command=self.command)
    def test_current_bounded_status_is_visible_and_deduplicated(self):
        self.assertEqual(self.invoke()['stage'],'published');self.invoke();self.assertEqual(len(self.writes),1)
        self.assertEqual(json.loads(self.metadata['remediation_admission_status']),self.value)
        self.assertNotIn('status',[a[0] for a in self.writes])
    def test_wrong_root_raw_output_or_false_success_never_mutates_board(self):
        for change in (dict(root_issue='other'),dict(stdout='secret'),dict(release_homologated=True),dict(remaining_calls=True)):
            self.command.return_value=json.dumps({**self.value,**change})
            with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.writes,[])
    def test_lost_write_ack_observes_metadata_before_any_repeat(self):
        def uncertain(*args):
            value=self.cli(*args)
            if args[:2]==('metadata','set'):raise TimeoutError()
            return value
        result=project(self.root,'root',uncertain,command=self.command)
        self.assertEqual(result['stage'],'pending');self.assertEqual(self.invoke()['stage'],'published')
        self.assertEqual(len(self.writes),1)
    def test_absent_admission_never_invents_progress(self):
        self.command.return_value='null';self.assertIsNone(self.invoke());self.assertEqual(self.writes,[])
