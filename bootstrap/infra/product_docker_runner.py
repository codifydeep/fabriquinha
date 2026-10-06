"""Trusted materializer. Root must have identical host/controller Docker path."""
import tempfile
import uuid
from pathlib import Path
from product_workspace import validate_files
from product_test_sandbox import run


class DockerRunner:
    def __init__(self, root, kind='node'):
        self.root = Path(root).resolve(strict=True)
        self.kind = kind

    def __call__(self, files, image):
        if self.kind=='governance':
            expected={'AGENTS.md','scripts/ci/test-integrity-guard.sh','scripts/ci/verify-test-maintenance.py','scripts/ci/test-maintenance-public.pem','.hermes/team/process-policy.json'}
            if set(files) not in (expected,expected|{'.hermes/team/generated-manifest.json'},expected|{'.hermes/team/generated-manifest.json','docs/governance/company-contract.md'}) or any(not isinstance(v,str) for v in files.values()) or sum(len(v.encode()) for v in files.values())>1024*1024:raise PermissionError('exact governance artifact scope required')
        else:validate_files(files)
        with tempfile.TemporaryDirectory(prefix='snapshot-', dir=self.root) as folder:
            root = Path(folder)
            root.chmod(0o755)
            for name, content in files.items():
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
                path.chmod(0o444)
            return run(root, image, uuid.uuid4().hex, self.kind)
