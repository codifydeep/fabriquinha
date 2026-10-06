import json
from pathlib import Path
import tempfile
import unittest
import hashlib
from unittest.mock import patch

from brief_delivery_supervisor import supervise
from compilation_recovery import qualified_revision, ROOT
from qa_postmerge_trial import digest


class CompilationRecoveryTests(unittest.TestCase):
    def test_installed_proof_requires_idle_matching_code_and_blocked_cards(self):
        with tempfile.TemporaryDirectory() as folder:
            private = Path(folder)
            for directory in ('planning-intake', 'planned-cards'):
                (private / directory).mkdir()
            plan = {'exact': 'plan'}
            config = dict(name='TEST-1', sha256='a'*64,
                          selection=dict(configuration_sha256='b'*64, base_sha='c'*40))
            state = dict(stage='plan_ready', configuration_sha256='b'*64, base_sha='c'*40)
            mapped = dict(plan_sha256=digest(plan), cards=dict(C1='one', C2='two'))
            (private / 'planning-intake/TEST-1.json').write_text(json.dumps(state))
            (private / 'planned-cards/TEST-1.json').write_text(json.dumps(mapped))
            installed = dict(active=0, hashes={remote: hashlib.sha256((ROOT / local).read_bytes()).hexdigest()
                for remote, local in {'/broker.py':'broker/server.py', '/execution_context.py':'execution_context.py',
                                      '/handoff_runtime.py':'broker/handoff_runtime.py'}.items()})
            with patch('evalctl.PROJECT', 'delivery-kit-port2'), patch('materialize_plan.plan_from_ledger', return_value=plan), \
                 patch('start_eval.cli', return_value=dict(status='blocked', assignee_id=None)) as cli, \
                 patch('compilation_recovery.subprocess.check_output', return_value=json.dumps(installed)) as probe:
                proof = qualified_revision(config, private)
                self.assertEqual(len(proof), 64)
                installed['active'] = 1
                probe.return_value = json.dumps(installed)
                with self.assertRaises(ValueError): qualified_revision(config, private)
                installed['active'] = 0
                installed['hashes']['/broker.py'] = 'd'*64
                probe.return_value = json.dumps(installed)
                with self.assertRaises(ValueError): qualified_revision(config, private)
                cli.return_value = dict(status='in_progress', assignee_id='author')
                with self.assertRaises(ValueError): qualified_revision(config, private)

    def test_verified_new_revision_resumes_only_compilation_then_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ledger.json'
            path.write_text(json.dumps(dict(identity='a'*64, stage='blocked', active='compiling',
                completed=['planning','materializing'], category='brief_delivery_compiling_not_qualified')))
            calls = []
            self.assertEqual(supervise(path, 'a'*64, lambda s: calls.append(s) or 0,
                                      compilation_revision='b'*64), 0)
            self.assertEqual(calls, ['compiling','executing'])
            state = json.loads(path.read_text())
            self.assertEqual(state['compilation_recovery_revisions'], ['b'*64])
            self.assertEqual(state['prior_incidents'][0]['category'], 'brief_delivery_compiling_not_qualified')

    def test_same_revision_cannot_retry_failed_compilation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ledger.json'
            path.write_text(json.dumps(dict(identity='a'*64, stage='blocked', active='compiling',
                completed=['planning','materializing'])))
            calls = []
            run = lambda s: calls.append(s) or 1
            self.assertEqual(supervise(path, 'a'*64, run, compilation_revision='b'*64), 1)
            self.assertEqual(supervise(path, 'a'*64, run, compilation_revision='b'*64), 1)
            self.assertEqual(calls, ['compiling'])

    def test_no_proof_or_invalid_proof_never_dispatches(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ledger.json'
            path.write_text(json.dumps(dict(identity='a'*64, stage='blocked', active='compiling',
                completed=['planning','materializing'])))
            self.assertEqual(supervise(path, 'a'*64, lambda s: self.fail('dispatch')), 1)
            with self.assertRaises(ValueError):
                supervise(path, 'a'*64, lambda s: self.fail('dispatch'), compilation_revision='claimed fixed')
