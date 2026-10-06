"""One-time scoped cleanup. No prune, force removal, running stops or volume deletion."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import hashlib

ROOT = Path(__file__).resolve().parent
TARGETS = [
 'truco-online-homologation-3b4b8d90a81ab927', 'truco-online-homologation-4b704e0058d80c25',
 'truco-online-adapter-failed-candidate-01', 'truco-online-node-qa-worker',
 'truco-online-node-qa-controller', 'truco-online-pr21-review-worker',
 'truco-online-pr21-review-controller', 'truco-online-adapter-workers-02',
 'truco-online-adapter-workers-01', 'truco-online-adapter-executor',
 'truco-online-adapter-readiness', 'truco-online-adapter-controller',
 'truco-online-rehearsal-ds1-api', 'truco-online-rehearsal-r3-api',
 'truco-online-rehearsal-api', 'dreamy_lamarr',
]
REPOS = {'delivery-kit-eval-broker', 'estudo-hermes-product', 'estudo-hermes-product-trial',
         'estudo-hermes-saas', 'truco-online-rehearsal', 'truco-online-rehearsal-r3',
         'truco-online-rehearsal-ds1', 'truco-online-rehearsal-acceptance'}
KEEP = {'delivery-kit-eval-broker:20260921.6', 'delivery-kit-eval-broker:20260923.3',
        'delivery-kit-hermes-wrapper:20260923.3', 'delivery-kit-eval-model-proxy:20260923.4',
        'estudo-hermes-product:20260921.3',
        'estudo-hermes-product:20260921.2', 'estudo-hermes-product-trial:0.5',
        'estudo-hermes-saas:0.21.50', 'estudo-hermes-saas:0.21.49'}


def output(*args):
    return subprocess.check_output(['docker', *args], text=True)


def containers():
    ids = output('ps', '-aq').split()
    return json.loads(output('inspect', *ids)) if ids else []


def protected(c):
    return c['Name'].lstrip('/').startswith('toso-') or (c['Config'].get('Labels') or {}).get('com.docker.compose.project', '').startswith('toso-')


def save(path, content):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        stream.write(content)


def main():
    before = containers()
    selected = [c for c in before if c['Name'].lstrip('/') in TARGETS]
    for c in selected:
        project = (c['Config'].get('Labels') or {}).get('com.docker.compose.project', '')
        if protected(c) or not project.startswith('truco-online') or c['State']['Status'] not in ('exited', 'created'):
            raise ValueError('unsafe cleanup target: ' + c['Name'])
    # Operational source references, plus a recent rollback image, remain available.
    pattern = re.compile(r'(?:estudo-hermes-[\w-]+|truco-online-[\w-]+|truco-github-runner|delivery-kit-[\w-]+):[A-Za-z0-9_.-]+')
    for folder in (ROOT.parent / 'bootstrap/infra', ROOT):
        for path in folder.rglob('*'):
            if ('.local' in path.parts or '.git' in path.parts or path.is_symlink()
                    or not path.is_file() or path.stat().st_size > 2_000_000):
                continue
            if path.suffix in ('.yaml', '.yml') or path.name.startswith('Dockerfile'):
                KEEP.update(pattern.findall(path.read_text(errors='replace')))
    selected_ids = {c['Id'] for c in selected}
    retained = [c for c in before if c['Id'] not in selected_ids]
    image_refs = {c['Config']['Image'] for c in retained}
    used_image_ids = {c['Image'] for c in retained}
    rows = [json.loads(line) for line in output('image', 'ls', '--no-trunc', '--format', '{{json .}}').splitlines()]
    images = []
    for row in rows:
        ref = row['Repository'] + ':' + row['Tag']
        if row['Repository'] in REPOS and ref not in KEEP and ref not in image_refs:
            details = json.loads(output('image', 'inspect', ref))[0]
            tags = details.get('RepoTags') or []
            if details['Id'] in used_image_ids or any(t.startswith('toso-') for t in tags):
                continue
            images.append(ref)
    print(json.dumps({'containers': [c['Name'].lstrip('/') for c in selected], 'image_tags': images,
                      'volumes_deleted': 0, 'build_cache_deleted': False}, indent=2), flush=True)
    if '--apply' not in sys.argv:
        return
    archive = ROOT / '.local' / ('docker-cleanup-' + time.strftime('%Y%m%d-%H%M%S'))
    archive.mkdir(mode=0o700)
    save(archive / 'inventory.json', json.dumps(before))  # private: may contain environment values
    save(archive / 'plan.json', json.dumps({'containers': TARGETS, 'images': images}))
    save(archive / 'df-before.txt', output('system', 'df'))
    removed, failures = [], []
    for c in selected:
        name = c['Name'].lstrip('/')
        current = json.loads(output('inspect', c['Id']))[0]
        if current['State']['Status'] not in ('exited', 'created') or protected(current):
            raise ValueError('container changed state; stopping cleanup')
        logs = subprocess.run(['docker', 'logs', '--timestamps', c['Id']], capture_output=True, text=True)
        save(archive / (name + '.log'), logs.stdout + logs.stderr)
        diff = output('diff', c['Id'])
        save(archive / (name + '.diff'), diff)
        # Preserve changed leaf paths only; all bind mounts and volumes are retained.
        # Avoid copying entire multi-GB base images merely to retire a test container.
        changes = [(line[0], line[2:]) for line in diff.splitlines() if len(line) > 2]
        mounts = [m['Destination'].rstrip('/') for m in current.get('Mounts', [])]
        copied = []
        for kind, path in changes:
            if kind == 'D' or any(path == m or path.startswith(m + '/') for m in mounts):
                continue
            if any(other.startswith(path.rstrip('/') + '/') for _, other in changes if other != path):
                continue
            filename = name + '.' + hashlib.sha256(path.encode()).hexdigest()[:16] + '.tar.gz'
            with open(archive / filename, 'xb') as target:
                os.chmod(target.name, 0o600)
                exporter = subprocess.Popen(['docker', 'cp', c['Id'] + ':' + path, '-'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                compressor = subprocess.run(['gzip', '-1'], stdin=exporter.stdout, stdout=target)
                exporter.stdout.close()
                if exporter.wait() or compressor.returncode:
                    raise RuntimeError('changed-path archive failed; target not deleted')
            subprocess.run(['gzip', '-t', str(archive / filename)], check=True)
            copied.append({'path': path, 'archive': filename})
        save(archive / (name + '.changed-paths.json'), json.dumps(copied))
        subprocess.run(['docker', 'rm', c['Id']], check=True, stdout=subprocess.DEVNULL)
        removed.append(name)
        print('Removed archived stopped container: ' + name, flush=True)
    for ref in images:
        current = containers()
        image_id = json.loads(output('image', 'inspect', ref))[0]['Id']
        if any(c['Image'] == image_id or c['Config']['Image'] == ref for c in current):
            continue
        result = subprocess.run(['docker', 'image', 'rm', ref], capture_output=True, text=True)
        if result.returncode:
            failures.append(ref)
        else:
            removed.append(ref)
    after = containers()
    original_protected = {(c['Id'], c['Image'], c['State']['Status']) for c in before if protected(c)}
    final_protected = {(c['Id'], c['Image'], c['State']['Status']) for c in after if protected(c)}
    assert original_protected == final_protected, 'protected project changed'
    original_running = {c['Id'] for c in before if c['State']['Running']}
    assert original_running <= {c['Id'] for c in after if c['State']['Running']}, 'running service changed'
    save(archive / 'result.json', json.dumps({'removed': removed, 'image_removal_conflicts_preserved': failures,
                                          'toso_unchanged': True, 'running_services_unchanged': True}))
    save(archive / 'df-after.txt', output('system', 'df'))
    print(json.dumps({'archive': str(archive), 'removed_containers': len(selected),
                      'removed_image_tags': len(removed) - len(selected), 'conflicts_preserved': len(failures),
                      'toso_unchanged': True, 'running_services_unchanged': True}), flush=True)


if __name__ == '__main__':
    main()
