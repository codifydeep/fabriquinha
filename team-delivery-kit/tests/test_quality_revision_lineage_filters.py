"""Real lineage tables and native identity fixtures, never blanket history skips."""
import contextlib
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from broker import quality_test_revision as revision


class RevisionLineageFilterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'native.json').write_text('{}')
        self.b=SimpleNamespace(PREFIX='delivery-kit-test',STATE=self.root,db=self.db)
        self.parent='b0000000-0000-4000-8000-000000000001'
        self.source='b0000000-0000-4000-8000-000000000002'
        self.old_author=self.task('b0000000-0000-4000-8000-000000000003','author')
        self.old_reviewer=self.task('b0000000-0000-4000-8000-000000000004','reviewer')
        self.new_author=self.task(self.source,'author')
        self.new_reviewer=self.task('b0000000-0000-4000-8000-000000000005','reviewer')
        self.items=[self.old_author,self.old_reviewer,self.new_author,self.new_reviewer]
        self.records={r['id']:copy.deepcopy(r) for r in self.items}
        context=dict(namespace=self.b.PREFIX,source_task=self.parent,issue_id='fixture',author='author',reviewer='reviewer',
            request=dict(tests_approved=False,verdict=dict(action='request_changes')),
            prior_runs=[revision.identity(self.old_author),revision.identity(self.old_reviewer)])
        state=dict(stage='admitted',task_id=self.source,tests_approved=False,delivery_approval=False)
        claim=dict(task_id=self.source,revision_source=self.parent)
        with self.db() as con:
            revision.initialize(con)
            con.execute('INSERT INTO quality_test_revisions VALUES(?,?,?,?,?)',
                (self.parent,json.dumps(context),json.dumps(state),revision.quality.digest(context),revision.quality.digest(state)))
            con.execute('INSERT INTO quality_revision_author_admissions VALUES(?,?,?,?,?)',
                (self.parent,self.source,'request',json.dumps(claim),revision.quality.digest(claim)))
        for name,fn in (('issue_task_runs',lambda *_:self.items),
                ('task_record',lambda settings,task,agent:self.records[task])):
            p=patch.object(revision.native,name,side_effect=fn);p.start();self.addCleanup(p.stop)

    @contextlib.contextmanager
    def db(self):
        con=sqlite3.connect(self.root/'state.sqlite')
        try:
            with con:yield con
        finally:con.close()

    def task(self,task,agent):
        return dict(id=task,agent_id=agent,issue_id='fixture',workspace_id='workspace',runtime_id='runtime',
            status='completed',wakeup_id=task,handoff_note='preserved fixture')

    def test_both_roles_filter_only_their_exact_authenticated_predecessors(self):
        authors=[r for r in self.items if r['agent_id']=='author']
        reviewers=[r for r in self.items if r['agent_id']=='reviewer']
        self.assertEqual(revision.exclude_prior_authors(self.b,self.source,authors),[self.new_author])
        self.assertEqual(revision.exclude_prior_reviews(self.b,self.source,reviewers),[self.new_reviewer])

    def test_changed_terminal_identity_is_rejected_instead_of_being_ignored(self):
        for key,value in (('status','running'),('wakeup_id','foreign'),('handoff_note','changed')):
            old=self.records[self.old_author['id']][key];self.records[self.old_author['id']][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                revision.exclude_prior_reviews(self.b,self.source,[self.old_reviewer,self.new_reviewer])
            self.records[self.old_author['id']][key]=old

    def test_unregistered_completed_task_is_not_excluded_by_status_or_role(self):
        foreign=self.task('b0000000-0000-4000-8000-000000000099','reviewer');self.items.append(foreign)
        result=revision.exclude_prior_reviews(self.b,self.source,[self.old_reviewer,self.new_reviewer,foreign])
        self.assertEqual(result,[self.new_reviewer,foreign])

    def test_missing_historical_record_or_corrupt_lineage_remains_a_blocker(self):
        self.items.remove(self.old_author)
        with self.assertRaises(ValueError):revision.exclude_prior_authors(self.b,self.source,[self.new_author])
        self.items.append(self.old_author)
        with self.db() as con:con.execute("UPDATE quality_test_revisions SET context_sha256=?",('0'*64,))
        with self.assertRaises(ValueError):revision.exclude_prior_reviews(self.b,self.source,[self.old_reviewer,self.new_reviewer])


if __name__=='__main__':unittest.main()
