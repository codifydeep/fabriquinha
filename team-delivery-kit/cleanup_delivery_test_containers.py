"""Retire historical QA containers only; preserve core services and all volumes."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
KEEP = 'delivery-kit-port2-browserfix-2-qa'


def run(*args, check=True):
    return subprocess.run(['docker', *args], check=check, capture_output=True, text=True)


def inventory():
    ids = run('ps', '-aq').stdout.split()
    return json.loads(run('inspect', *ids).stdout) if ids else []


def eligible(c):
    name = c['Name'].lstrip('/')
    labels = c['Config'].get('Labels') or {}
    return (name != KEEP and re.fullmatch(r'delivery-kit-(?:port2|eval)-[a-z0-9-]+', name)
            and not labels.get('com.docker.compose.project')
            and re.fullmatch(r'[a-f0-9]{40}', labels.get('delivery-kit.source-sha', ''))
            and c['HostConfig']['ReadonlyRootfs'])


def main():
    before = inventory()
    selected = [c for c in before if eligible(c)]
    print(json.dumps({'retire': [c['Name'].lstrip('/') for c in selected],
                      'keep_latest': KEEP, 'delete_volumes': False}, indent=2))
    if '--apply' not in sys.argv:
        return
    for broker in ('delivery-kit-port2-execution-broker-1', 'delivery-kit-eval-execution-broker-1'):
        probe = run('exec', broker, 'python', '-c',
                    'import sqlite3;c=sqlite3.connect("/broker-state/leases.sqlite");'
                    'print(c.execute("select count(*) from leases where status in (?,?)",'
                    '("running","creating")).fetchone()[0])')
        if probe.stdout.strip() != '0':
            raise ValueError('active worker; cleanup deferred')
    archive = ROOT / '.local-port2' / 'backups' / ('container-cleanup-' + time.strftime('%Y%m%d-%H%M%S'))
    archive.mkdir(mode=0o700)
    def save(name, value):
        with os.fdopen(os.open(archive / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as f:
            f.write(value)
    save('inventory.json', json.dumps(before))  # Private: inspect may contain env secrets.
    removed = []
    for original in selected:
        c = json.loads(run('inspect', original['Id']).stdout)[0]
        if not eligible(c) or c['Id'] != original['Id']:
            raise ValueError('cleanup target drift')
        name = c['Name'].lstrip('/')
        # SQLite backup is consistent even if an old test app is still serving.
        if c['State']['Running'] and 'FEEDBACK_DB_PATH=/tmp/feedback.db' in c['Config'].get('Env', []):
            run('exec', c['Id'], 'python', '-c',
                'import sqlite3;src=sqlite3.connect("file:/tmp/feedback.db?mode=ro",uri=True);'
                'dst=sqlite3.connect("/tmp/delivery-cleanup-backup.db");src.backup(dst);dst.close();src.close()')
            target = archive / (name + '.sqlite')
            # Docker cp does not reliably see tmpfs contents; exec streams bytes.
            content = subprocess.check_output(['docker', 'exec', c['Id'], 'python', '-c',
                'import sys;from pathlib import Path;sys.stdout.buffer.write('
                'Path("/tmp/delivery-cleanup-backup.db").read_bytes())'])
            with os.fdopen(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as f:
                f.write(content)
            import sqlite3
            with sqlite3.connect(target) as db:
                if db.execute('pragma integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('unreadable database backup')
        log = run('logs', '--timestamps', c['Id'], check=False)
        save(name + '.log', log.stdout + log.stderr)
        save(name + '.diff', run('diff', c['Id']).stdout)
        # Read-only root, retained volumes, archived DB; no force or -v.
        if c['State']['Running']:
            run('stop', '--time', '10', c['Id'])
        current = json.loads(run('inspect', c['Id']).stdout)[0]
        if current['State']['Running'] or not eligible(current):
            raise ValueError('unsafe removal state')
        run('rm', c['Id'])
        removed.append(name)
        print('Removed: ' + name, flush=True)
    after = inventory()
    removed_ids = {c['Id'] for c in selected}
    # The retained homologation may be recreated concurrently solely for grouping.
    # Accept that one exact name only after checking unchanged image and source.
    old_keep = next(c for c in before if c['Name'].lstrip('/') == KEEP)
    new_keep = next(c for c in after if c['Name'].lstrip('/') == KEEP)
    if (new_keep['Image'] != old_keep['Image'] or not new_keep['State']['Running']
            or new_keep['Config']['Labels'].get('delivery-kit.source-sha') !=
               old_keep['Config']['Labels'].get('delivery-kit.source-sha')):
        raise ValueError('retained homologation changed')
    preserved = {c['Id']: (c['Image'], c['State']['Status']) for c in before
                 if c['Id'] not in removed_ids and c['Name'].lstrip('/') != KEEP}
    actual = {c['Id']: (c['Image'], c['State']['Status']) for c in after}
    if any(actual.get(key) != value for key, value in preserved.items()):
        raise ValueError('unrelated service changed')
    save('result.json', json.dumps({'removed': removed, 'volumes_deleted': 0,
                                  'other_containers_unchanged': True}))
    print(json.dumps({'removed_count': len(removed), 'archive': str(archive)}))


if __name__ == '__main__':
    main()
