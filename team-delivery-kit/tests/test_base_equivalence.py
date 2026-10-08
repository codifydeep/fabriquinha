import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from base_equivalence_probe import run
from broker.base_equivalence import validate_bindings,validate_result


class BaseEquivalenceTests(unittest.TestCase):
    def test_only_phase_metadata_may_differ_and_no_general_hash_bypass(self):
        approved=dict(issue_id='old',volume='old-volume',base_sha='a'*40,manifest_sha256='b'*64)
        cfg=dict(base=approved,source_issue='new',amendment=dict(kind='request_scope'),diagnostic_snapshot_kind='completed_frozen_validation')
        current={**approved,'issue_id':'new','volume':'new-volume'};validate_bindings(cfg,current)
        for changes in (dict(base_sha='changed'),dict(manifest_sha256='changed'),dict(issue_id='foreign'),dict(volume='old-volume')):
            with self.assertRaises(ValueError):validate_bindings(cfg,{**current,**changes})
        with self.assertRaises(ValueError):validate_bindings({**cfg,'amendment':{}},current)
        with self.assertRaises(ValueError):validate_bindings(cfg,{**current,'extra':'unreviewed'})

    def test_timer_amendment_requires_the_same_exact_original_base(self):
        approved=dict(issue_id='old',volume='old-volume',base_sha='a'*40,manifest_sha256='b'*64)
        cfg=dict(base=approved,source_issue='new',amendment=dict(kind='timer_provenance'),
            diagnostic_snapshot_kind='completed_frozen_validation')
        current={**approved,'issue_id':'new','volume':'new-volume'}
        validate_bindings(cfg,current)
        for changes in (dict(base_sha='changed'),dict(manifest_sha256='changed'),
                        dict(issue_id='foreign'),dict(volume='old-volume')):
            with self.assertRaises(ValueError):validate_bindings(cfg,{**current,**changes})
        with self.assertRaises(ValueError):validate_bindings({**cfg,'amendment':dict(kind='unapproved')},current)

    def test_complete_bytes_match_and_one_changed_file_is_rejected(self):
        import shutil
        from test_revision_seed import RevisionSeedTests
        f=RevisionSeedTests();f.setUp()
        try:
            a=f.base;c=f.base.parent/'current';shutil.copytree(a,c)
            sha=hashlib.sha256((a/'manifest.json').read_bytes()).hexdigest()
            result=run(a,c,sha);validate_result(result,sha)
            self.assertFalse(result['execution_authorized']);self.assertFalse(result['source_modified'])
            for changes in (dict(files_identical=False),dict(delivery_approval=True),dict(file_count=True)):
                with self.assertRaises(ValueError):validate_result({**result,**changes},sha)
            (c/'app.py').write_bytes(b'different bytes')
            with self.assertRaises(ValueError):run(a,c,sha)
        finally:f.doCleanups()

    def test_uncertain_create_has_deadline_and_never_repeats_post(self):
        import sqlite3
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import patch
        from broker import base_equivalence as module
        approved=dict(issue_id='old',volume='delivery-kit-port2-base-old',base_sha='a'*40,manifest_sha256='b'*64)
        current={**approved,'issue_id':'new','volume':'delivery-kit-port2-base-new'}
        cfg=dict(base=approved,source_issue='new',source_task='source',amendment=dict(kind='request_scope'),
            diagnostic_snapshot_kind='completed_frozen_validation')
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;calls=[]
        @contextmanager
        def db():yield con
        def docker(method,path,body=None):
            calls.append(method)
            if path.startswith('/volumes/'):return dict(Labels={'delivery-kit.owner':'owner'})
            if method=='POST':raise TimeoutError('unknown acknowledgement')
            return None
        b=SimpleNamespace(db=db,docker=docker,OWNER='owner',PREFIX='delivery-kit-port2')
        with patch.object(module.jobs,'image_environment',return_value=[]):
            with self.assertRaises(TimeoutError):module.qualify(b,cfg,current)
            state=json.loads(con.execute('SELECT state FROM original_base_equivalences_v2').fetchone()[0]);state['at']=0
            con.execute('UPDATE original_base_equivalences_v2 SET state=?',(json.dumps(state),))
            with self.assertRaises(ValueError):module.qualify(b,cfg,current)
        self.assertEqual(calls.count('POST'),1)
        self.assertEqual(json.loads(con.execute('SELECT state FROM original_base_equivalences_v2').fetchone()[0])['stage'],'blocked')
        con.close()
