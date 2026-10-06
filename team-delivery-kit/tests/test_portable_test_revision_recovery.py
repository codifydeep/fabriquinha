import json
import hashlib
import tempfile
from pathlib import Path
import unittest
from portable_test_revision_recovery import child_spec, publish_recovered_parent, next_revision_depth, reconcile_ancestors


class RevisionRecoveryTests(unittest.TestCase):
    def test_completion_reconciles_two_ancestors_and_restart_is_idempotent(self):
        context, child, receipt = self.proof()
        metadata = {'child': {}, 'parent': {'test_revision_child_issue': 'child'},
                    'root': {'test_revision_child_issue': 'parent'}}
        states = {'child': 'done', 'parent': 'blocked', 'root': 'blocked'}
        mutations = []
        def cli(*args):
            if args[:2] == ('metadata', 'list'): return dict(metadata[args[2]])
            if args[0] == 'get': return {'status': states[args[1]]}
            mutations.append(args)
            if args[:2] == ('metadata', 'set'):
                metadata[args[2]][args[args.index('--key') + 1]] = args[args.index('--value') + 1]
            else:
                self.assertEqual(args[-1], '--no-start')
                states[args[1]] = args[2]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for directory in ('release-receipts', 'test-revision-recovery', 'autonomy-status'):
                (root / directory).mkdir()
            for issue in ('child', 'parent', 'root'):
                spec = {'label': issue}
                value = {**context, 'issue_id': issue, 'label': issue,
                         'run_spec_sha256': hashlib.sha256(json.dumps(spec,
                            sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
                (root / ('portable-context-' + issue + '.json')).write_text(json.dumps(value))
            for parent, descendant in (('parent', 'child'), ('root', 'parent')):
                (root / 'test-revision-recovery' / (parent + '.json')).write_text(json.dumps({
                    'parent_issue': parent, 'child_issue': descendant, 'label': descendant,
                    'spec': {'label': descendant}, 'stage': 'test_revision_child_running'}))
            (root / 'release-receipts' / 'child.json').write_text(json.dumps({**receipt, 'label': 'child'}))
            self.assertEqual(len(reconcile_ancestors(root, 'child', cli)), 2)
            self.assertEqual(states, dict.fromkeys(states, 'done'))
            count = len(mutations)
            reconcile_ancestors(root, 'child', cli)
            self.assertEqual(len(mutations), count)
            self.assertFalse((root / 'release-receipts' / 'parent.json').exists())
            metadata['parent']['recovery_receipt_sha'] = 'b' * 40
            with self.assertRaisesRegex(ValueError, 'drift'):
                reconcile_ancestors(root, 'child', cli)

    def test_transitive_recovery_requires_proven_direct_link(self):
        context, child, receipt = self.proof()
        receipt['issue_id'] = 'leaf'
        cli, _, _, mutations = self.fake_cli()
        with self.assertRaisesRegex(ValueError, 'unproven'):
            publish_recovered_parent(cli, context, child, receipt, lineage=['leaf'])
        self.assertEqual(mutations, [])

    def test_additional_revision_requires_bound_complete_replan_and_is_not_recursive(self):
        managed = self.managed()
        managed['state']['source_task'] = 'source'
        context = {'issue_id': 'parent'}
        self.assertEqual(next_revision_depth(context, managed, '0'), '1')
        with self.assertRaisesRegex(ValueError, 'technical replan'):
            next_revision_depth(context, managed, '1')
        data = json.loads(managed['state']['data'])
        data['test_revision_proposal']['output_sha256'] = 'green-failure'
        data['technical_replan_certificate'] = {
            'version': 'complete-source-replan-v1', 'issue_id': 'parent',
            'source_task': 'source', 'decision_task': 'decision',
            'output_sha256': 'green-failure', 'read_contract': 'complete-lines-v2',
            'read_evidence': {'candidate': {'lines': 10, 'total_lines': 10}},
            'required_read_paths': ['candidate'],
            'baseline_edits_allowed': False}
        managed['state']['data'] = json.dumps(data)
        self.assertEqual(next_revision_depth(context, managed, '1'), '2')
        with self.assertRaisesRegex(ValueError, 'technical replan'):
            next_revision_depth(context, managed, '2')
        for key, value in (('decision_task', 'stale'), ('issue_id', 'other'),
                           ('read_contract', 'old'), ('baseline_edits_allowed', True),
                           ('read_evidence', {}), ('required_read_paths', []),
                           ('read_evidence', {'candidate': {'lines': 9, 'total_lines': 10}})):
            changed = json.loads(managed['state']['data'])
            changed['technical_replan_certificate'][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'technical replan'):
                next_revision_depth(context, {'state': {'source_task': 'source',
                    'data': json.dumps(changed)}}, '1')

    def proof(self):
        sha = 'a' * 40
        context = {'issue_id': 'parent', 'base_sha': 'base', 'contract_sha256': 'contract'}
        child = {'issue_id': 'child'}
        receipt = {'issue_id': 'child', 'base_sha': 'base', 'contract_sha256': 'contract',
                   'merge_sha': sha, 'stage': 'deployed_qa_passed', 'board': {'status': 'done'},
                   'browser_qa': {'status': 'passed', 'cleanup': 'passed', 'automated': True,
                     'identity': {'source_sha': sha}, 'result': {'source_sha': sha, 'status': 'passed'}},
                   'deployment': {'status': 'passed', 'source_sha': sha, 'url': 'http://local'},
                   'main_ci_run': 'https://ci', 'pr_url': 'https://pr'}
        return context, child, receipt

    def fake_cli(self, status='todo'):
        metadata = {'test_revision_child_issue': 'child',
                    'delivery_handoff': 'original rejected snapshot',
                    'browser_acceptance': 'pending_real_browser'}
        states = {'parent': status, 'child': 'done'}
        mutations = []
        def cli(*args):
            if args[:2] == ('metadata', 'list'):
                return dict(metadata)
            if args[0] == 'get':
                return {'status': states[args[1]]}
            mutations.append(args)
            if args[:2] == ('metadata', 'set'):
                metadata[args[args.index('--key') + 1]] = args[args.index('--value') + 1]
            elif args[0] == 'status':
                self.assertEqual(args[-1], '--no-start')
                states[args[1]] = args[2]
        return cli, metadata, states, mutations

    def test_proven_child_closes_parent_idempotently_without_reapproving_snapshot(self):
        cli, metadata, states, mutations = self.fake_cli()
        result = publish_recovered_parent(cli, *self.proof())
        self.assertEqual(result['via'], 'test_revision_child')
        self.assertEqual(states['parent'], 'done')
        self.assertEqual(metadata['delivery_handoff'], 'original rejected snapshot')
        self.assertEqual(metadata['browser_acceptance'], 'pending_real_browser')
        count = len(mutations)
        publish_recovered_parent(cli, *self.proof())
        self.assertEqual(len(mutations), count)

    def test_incomplete_or_wrong_child_proof_cannot_close_parent(self):
        for damage in ('sha', 'base', 'contract', 'cleanup', 'automated', 'ci', 'stage', 'child'):
            context, child, receipt = self.proof()
            if damage == 'sha': receipt['browser_qa']['identity']['source_sha'] = 'b' * 40
            elif damage == 'base': receipt['base_sha'] = 'other'
            elif damage == 'contract': receipt['contract_sha256'] = 'other'
            elif damage == 'cleanup': receipt['browser_qa']['cleanup'] = 'failed'
            elif damage == 'automated': receipt['browser_qa']['automated'] = False
            elif damage == 'ci': receipt.pop('main_ci_run')
            elif damage == 'stage': receipt['stage'] = 'accepted'
            else: receipt['issue_id'] = 'other'
            cli, _, _, mutations = self.fake_cli()
            with self.assertRaisesRegex(ValueError, 'exact child'):
                publish_recovered_parent(cli, context, child, receipt)
            self.assertEqual(mutations, [])

    def test_parent_cancellation_or_evidence_drift_cannot_be_overridden(self):
        cli, metadata, _, mutations = self.fake_cli(status='cancelled')
        with self.assertRaisesRegex(ValueError, 'cancellation'):
            publish_recovered_parent(cli, *self.proof())
        self.assertEqual(mutations, [])
        cli, metadata, _, mutations = self.fake_cli()
        metadata['recovery_receipt_sha'] = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'drift'):
            publish_recovered_parent(cli, *self.proof())
        self.assertEqual(mutations, [])

    def managed(self):
        return {'route': {'cto': 'cto', 'test_first': True, 'test_first_files': ['test_new.py']},
                'state': {'stage': 'test_revision_required', 'data': json.dumps({
                    'target': 'cto', 'source_task': 'source',
                    'decision': {'action': 'request_test_revision', 'optional_files': []},
                    'test_revision_proposal': {'decision_task': 'decision', 'source_task': 'source',
                        'new_test_files': ['test_new.py'], 'reason': 'Incorrect mock commit order.'}})}}

    def test_child_preserves_scope_and_requires_new_independent_review(self):
        spec = {'label': 'DEMO-1', 'description': 'Original scope', 'browser_qa': {'fixed': True},
                'runtime_env': {'public': 'value'}, 'sha256': 'old'}
        result = child_spec({'issue_id': 'parent'}, spec, self.managed())
        self.assertNotEqual(result['label'], spec['label'])
        self.assertEqual(result['browser_qa'], spec['browser_qa'])
        self.assertIn('BEFORE implementation', result['description'])
        self.assertNotIn('sha256', result)
        self.assertEqual(result, child_spec({'issue_id': 'parent'}, spec, self.managed()))
        older = {**spec, 'description': spec['description'] +
                 '\nCTO-SPONSORED NEW TEST REVISION: obsolete unsupported diagnosis'}
        self.assertEqual(child_spec({'issue_id': 'parent'}, older, self.managed()), result)

    def test_wrong_sponsor_or_source_cannot_grant_test_mutation(self):
        for key, value in (('target', 'author'), ('source_task', 'other')):
            managed = self.managed()
            data = json.loads(managed['state']['data'])
            data[key] = value
            managed['state']['data'] = json.dumps(data)
            with self.assertRaisesRegex(ValueError, 'CTO-sponsored'):
                child_spec({'issue_id': 'parent'}, {'description': 'Scope'}, managed)

    def test_semantic_child_uses_mechanical_findings_not_false_sponsor_prose(self):
        from broker.candidate_qualification import experiment_hash
        managed = self.managed()
        data = json.loads(managed['state']['data'])
        fact = {'file': 'test_new.py', 'query_line': 187, 'query': 'fix',
                'title': 'prefix', 'casefold_substring': True}
        proof = {'facts': [fact], 'manifest_sha256': 'a' * 64, 'output_sha256': 'b' * 64}
        ack = {'experiment_sha256': experiment_hash(proof),
               'semantic_checks': [{'fact_index': 0, 'casefold_substring': True}]}
        data['test_revision_proposal']['reason'] = 'Wrong sponsor prose must not instruct the author'
        data.update(semantic_fixture_experiment=proof, candidate_qualification={
            'stage': 'semantic_test_revision_qualified', 'sponsor_task': 'decision',
            'review_decision': ack, 'sponsor_decision': ack})
        managed['state']['data'] = json.dumps(data)
        with self.assertRaises(ValueError):
            child_spec({'issue_id': 'parent'}, {'description': 'Original scope'}, managed)
        data['semantic_repair_findings'] = {'experiment_sha256': experiment_hash(proof),
            'manifest_sha256': 'a' * 64, 'output_sha256': 'b' * 64,
            'status': 'findings_only_not_approval', 'contradictions': [{**fact, 'asserted_match': False}]}
        managed['state']['data'] = json.dumps(data)
        child = child_spec({'issue_id': 'parent'}, {'description': 'Original scope'}, managed)
        self.assertNotIn('Wrong sponsor prose', child['description'])
        self.assertIn('SOURCE-BOUND ASSERTION FINDINGS', child['description'])
        self.assertIn('187', child['description'])
