"""Operator checkpoint. Requires a quiescent, fenced Hermes installation.

Archives credentials privately; never publish these archives to GitHub.
No cleanup or reset is performed by this script.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tarfile
import tempfile
import time

ROOT = Path('/opt/data')
REPO = Path('/Users/weber/Documents/projetos_pessoais_desenv/hermes/truco-online')


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def checkpoint():
    os.umask(0o077)
    if not (ROOT / 'kanban/boards/truco-online/MAINTENANCE').exists():
        raise RuntimeError('maintenance fence required')
    processes = run('ps', '-eo', 'pid,args')
    if any('hermes_cli.kanban_worker' in line for line in processes.splitlines()):
        raise RuntimeError('worker still alive')
    target = ROOT / 'observability' / ('restart-' + time.strftime('%Y%m%d-%H%M%S'))
    target.mkdir(mode=0o700)
    worktrees = run('git', '-C', str(REPO), 'worktree', 'list', '--porcelain')
    paths = [Path(line[9:]) for line in worktrees.splitlines() if line.startswith('worktree ')]
    inventory = {'created_at': time.time(), 'repo': str(REPO), 'worktrees': worktrees,
                 'refs': run('git', '-C', str(REPO), 'show-ref'), 'status': {}, 'databases': []}
    for path in paths:
        if not path.exists():
            supplemental = ROOT / 'observability/external-worktree-backup.tgz'
            if str(path) != '/private/tmp/truco-governance.eAroZk' or not supplemental.is_file():
                raise RuntimeError(f'external worktree must be separately backed up: {path}')
            inventory['status'][str(path)] = 'Host-only worktree; complete supplemental archive included'
            continue
        inventory['status'][str(path)] = run('git', '-C', str(path), 'status', '--porcelain=v1', '--untracked-files=all')
    inventory['open_prs'] = json.loads(run('gh', 'pr', 'list', '--repo', 'codifydeep/truco-online',
        '--state', 'open', '--limit', '1000', '--json', 'number,title,headRefName,headRefOid,baseRefName,url'))
    # SQLite backup API includes WAL contents and validates the restored copy.
    for db in ROOT.rglob('*.db'):
        if 'observability' in db.relative_to(ROOT).parts or not db.is_file():
            continue
        with db.open('rb') as stream:
            if stream.read(16) != b'SQLite format 3\x00':
                continue
        restored = target / 'sqlite' / db.relative_to(ROOT)
        restored.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(f'file:{db}?mode=ro', uri=True) as src, sqlite3.connect(restored) as dst:
            src.backup(dst)
            result = dst.execute('PRAGMA integrity_check').fetchall()
            if result != [('ok',)]:
                raise RuntimeError(f'integrity failure: {db}: {result}')
        inventory['databases'].append(str(db.relative_to(ROOT)))
    with tarfile.open(target / 'hermes-data.tgz', 'w:gz', compresslevel=1) as archive:
        for item in ROOT.iterdir():
            # WAL/SHM are transient; consistent SQLite backups above are the
            # restore source of truth, not a copy of these ephemeral files.
            if item.name != 'observability' and not item.name.endswith(('.db-wal', '.db-shm')):
                archive.add(item, arcname=item.name)
        for item in (ROOT / 'observability').iterdir():
            if item.is_file():
                archive.add(item, arcname='observability/' + item.name)
    with tarfile.open(target / 'repository-worktrees.tgz', 'w:gz', compresslevel=1) as archive:
        archive.add(REPO, arcname='repository')
        for index, path in enumerate(paths):
            if path.exists() and path != REPO and not path.is_relative_to(REPO):
                archive.add(path, arcname=f'external-worktrees/{index}')
    bundle = target / 'repository.bundle'
    run('git', '-C', str(REPO), 'bundle', 'create', str(bundle), '--all')
    run('git', '-C', str(REPO), 'bundle', 'verify', str(bundle))
    with tempfile.TemporaryDirectory(prefix='truco-restore-') as tmp:
        restored_repo = str(Path(tmp) / 'repo.git')
        run('git', 'clone', '--mirror', str(bundle), restored_repo)
        run('git', '-C', restored_repo, 'fsck', '--full')
    for name in ('hermes-data.tgz', 'repository-worktrees.tgz'):
        with tarfile.open(target / name, 'r:gz') as archive:
            for member in archive:
                if member.isfile():
                    with archive.extractfile(member) as stream:
                        while stream.read(1024 * 1024):
                            pass
    inventory['restore_checks'] = ['all SQLite copies integrity_check=ok', 'Git mirror restored and fsck passed', 'all tar file payloads read']
    (target / 'inventory.json').write_text(json.dumps(inventory, indent=2))
    hashes = {}
    for file in target.rglob('*'):
        if file.is_file():
            with file.open('rb') as stream:
                hashes[str(file.relative_to(target))] = hashlib.file_digest(stream, 'sha256').hexdigest()
    (target / 'sha256.json').write_text(json.dumps(hashes, indent=2))
    print(json.dumps({'checkpoint': str(target), 'database_count': len(inventory['databases']),
                      'worktree_count': len(paths), 'open_prs': len(inventory['open_prs']),
                      'verified': True}), flush=True)


if __name__ == '__main__':
    checkpoint()
