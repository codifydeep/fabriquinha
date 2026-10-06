import json
import os
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import portable_delivery
from portable_run_spec import load, validate
from test_portable_contract import contract


def spec():
    return {'label': 'DEMO-1', 'title': 'Implement one feature',
            'description': 'Add a tested feature in the assigned repository.',
            'review_instruction': 'Review only /delivery and run the complete suite.',
            'qa_host_port': 19400, 'container_port': 8080,
            'dockerfile': 'Dockerfile',
            'implementer_registry': 'backend-agent.json',
            'reviewer_registry': 'review-agent.json'}


class PortableRunSpecTests(unittest.TestCase):
    def test_bounded_public_runtime_env(self):
        definition = contract()
        definition['files'].append('Dockerfile')
        definition['protected_files'].append('Dockerfile')
        value = {**spec(), 'runtime_env': {'FEEDBACK_DB_PATH': '/tmp/feedback.db'}}
        self.assertEqual(validate(value, definition)['runtime_env'], value['runtime_env'])
        with patch.object(portable_delivery, 'RUN_SPEC', value):
            self.assertEqual(portable_delivery.runtime_env_args(),
                             ['--env', 'FEEDBACK_DB_PATH=/tmp/feedback.db'])
        for name in ('OPENROUTER_API_KEY', 'PASSWORD', 'SOURCE_SHA'):
            with self.assertRaisesRegex(ValueError, 'runtime env'):
                validate({**spec(), 'runtime_env': {name: 'secret'}}, definition)
        with self.assertRaisesRegex(ValueError, 'runtime env'):
            validate({**spec(), 'runtime_env': {'SAFE': 'line\nsecond'}}, definition)

    def test_validates_operator_owned_fields_and_protected_dockerfile(self):
        definition = contract()
        definition['files'].append('Dockerfile')
        definition['protected_files'].append('Dockerfile')
        self.assertEqual(validate(spec(), definition)['label'], 'DEMO-1')
        invalid = {**spec(), 'dockerfile': 'app.py'}
        with self.assertRaisesRegex(ValueError, 'Dockerfile must be protected'):
            validate(invalid, definition)
        invalid = {**spec(), 'label': '../escape'}
        with self.assertRaisesRegex(ValueError, 'label'):
            validate(invalid, definition)

    def test_spec_is_hashed_and_controller_rejects_drift(self):
        definition = contract()
        definition['files'].append('Dockerfile')
        definition['protected_files'].append('Dockerfile')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'run.json'
            source.write_text(json.dumps(spec()))
            with patch.dict(os.environ, {'DELIVERY_KIT_RUN_SPEC': str(source)}):
                selected = load(definition)
                self.assertEqual(len(selected['sha256']), 64)
                with patch.object(portable_delivery, 'REPOSITORY', definition['repository']):
                    with patch.object(portable_delivery, 'PRIVATE', Path(directory)):
                        portable_delivery.configure_run(definition)
                        self.assertEqual(portable_delivery.LABEL, 'DEMO-1')
                        self.assertEqual(portable_delivery.BRANCH, 'codex/demo-1-reviewed')
                        self.assertEqual(portable_delivery.QA_PORT, 19400)
                        self.assertEqual(portable_delivery.DOCKERFILE, 'Dockerfile')
                        self.assertEqual(portable_delivery.CONTAINER_PORT, 8080)
                        context = {'label': 'DEMO-1', 'issue_id': 'issue',
                            'base_sha': 'a' * 40, 'run_spec_sha256': selected['sha256'],
                            'contract_sha256': hashlib.sha256(json.dumps(definition,
                                sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
                        (Path(directory) / 'portable-context-DEMO-1.json').write_text(json.dumps(context))
                        self.assertEqual(portable_delivery.read_context(definition), context)
                        changed = {**spec(), 'qa_host_port': 19401}
                        source.write_text(json.dumps(changed))
                        portable_delivery.configure_run(definition)
                        with self.assertRaisesRegex(ValueError, 'spec changed'):
                            portable_delivery.read_context(definition)
            with patch.dict(os.environ, {'DELIVERY_KIT_RUN_SPEC': ''}):
                portable_delivery.configure_run(definition)
                self.assertIsNone(portable_delivery.RUN_SPEC)
                self.assertEqual(portable_delivery.LABEL, 'PORT-4')

    def test_rejects_symlink_run_spec(self):
        definition = contract()
        definition['files'].append('Dockerfile')
        definition['protected_files'].append('Dockerfile')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'run.json'
            source.write_text(json.dumps(spec()))
            link = Path(directory) / 'link.json'
            link.symlink_to(source)
            with patch.dict(os.environ, {'DELIVERY_KIT_RUN_SPEC': str(link)}):
                with self.assertRaisesRegex(ValueError, 'absolute regular'):
                    load(definition)


if __name__ == '__main__':
    unittest.main()
