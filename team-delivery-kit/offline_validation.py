"""Run deterministic tests with only public source fixtures mounted into Docker."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
from docker_grouping import args as docker_group_args

ROOT = Path(__file__).resolve().parent
PUBLIC_EVIDENCE = ('evaluation/SURGICAL-DRIVER-V3-QUALIFICATION-2026-10-04.json',)


def copy_sources(root, destination):
    for pattern in ('*.py', '*.yaml', 'Dockerfile*', 'team.example.json'):
        for path in root.glob(pattern):
            if path.is_file() and not path.is_symlink():
                shutil.copy2(path, destination / path.name)
    for name in ('broker', 'tests', 'projects', 'deploy'):
        if any(path.is_symlink() for path in (root / name).rglob('*')):
            raise ValueError('source fixture symlinks forbidden')
        shutil.copytree(root / name, destination / name,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in PUBLIC_EVIDENCE:
        path = root / name
        if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            raise ValueError('required public test evidence missing or symlinked')
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    if any(path.is_symlink() for path in destination.rglob('*')):
        raise ValueError('source fixture symlinks forbidden')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    if not args.image.startswith('sha256:') or len(args.image) != 71:
        raise ValueError('immutable locally built image required')
    with tempfile.TemporaryDirectory(prefix='delivery-kit-public-tests-') as directory:
        copy_sources(ROOT, Path(directory))
        subprocess.run(['docker', 'run', '--rm', '--name', 'delivery-kit-port2-offline-validation',
            *docker_group_args('offline-validation',namespace='delivery-kit-port2'), '--network', 'none',
            '--read-only', '--user', '10000:10000', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--memory', '512m', '--cpus', '1', '--pids-limit', '64',
            '--tmpfs', '/tmp:size=128m,mode=1777', '--mount', f'type=bind,source={directory},target=/source,readonly',
            '--workdir', '/source', '--env', 'PYTHONDONTWRITEBYTECODE=1', '--env', 'HOME=/tmp',
            '--entrypoint', 'python', args.image, '-m', 'unittest', 'discover', '-s', 'tests', '-q'], check=True)


if __name__ == '__main__':
    main()
